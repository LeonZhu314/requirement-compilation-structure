"""Run-wide admission, explicit accounting and stagnation detection.

One budget spans the initial work, host verification and every repair in the same
session. Counters are never reset between turns. A part of the wall time is reserved
so the delivered state can still be built and verified after the work deadline.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from time import monotonic


@dataclass(frozen=True)
class BudgetSettings:
    # Initial values derive from the frozen baseline (75 calls, 1.34 M input tokens,
    # 2 966 s for a 5/5 run; 277 calls in an unfinished loop). They bound a free agent
    # that sends more, smaller requests; step 23 measurements must revise them.
    wall_seconds: int = 5400
    verification_reserve_seconds: int = 900
    max_tool_calls: int = 2500
    max_reported_tokens: int = 12_000_000
    max_verification_rounds: int = 8
    stagnation_repeats: int = 3


def reached(count, limit):
    """A limit of 0 (or None) is no limit."""
    return bool(limit) and count >= limit


class BudgetExceeded(RuntimeError):
    def __init__(self, limit):
        super().__init__(f'Budget exceeded: {limit}')
        self.limit = limit


REQUEST_KINDS = ('main', 'subagent', 'visual_fallback', 'acceptance_generation', 'test_review', 'visual_review')


class Budget:
    """Synchronous admission before each request/tool/verification; never reclassifies usage."""

    def __init__(self, state, max_requests, settings=None, clock=monotonic):
        self.state, self.max_requests, self.settings = state, max_requests, settings or BudgetSettings()
        self.clock = clock
        self.started = None
        self.exhausted = None
        self.requests = {kind: 0 for kind in REQUEST_KINDS}
        self.tool_calls = 0
        self.verifications = {}
        self.tokens = self.input_tokens = self.output_tokens = self.cached_tokens = self.reasoning_tokens = 0
        self.pruned = {'passes': 0, 'observations': 0, 'bytes': 0}
        self.usage_missing = 0
        self.retries = 0
        # Where the wall time went: seconds per phase and per tool (calls, seconds).
        self.seconds, self.tool_seconds = {}, {}
        self.stagnation_notices = 0

    def start(self):
        if self.started is None:
            self.started = self.clock()

    def elapsed(self):
        return 0.0 if self.started is None else self.clock() - self.started

    @property
    def time_limited(self):
        """wall_seconds 0 means no time limit (long applications); other limits still apply."""
        return self.settings.wall_seconds > 0

    def remaining_seconds(self, *, final=False):
        if not self.time_limited:
            return float('inf')
        limit = self.settings.wall_seconds - (0 if final else self.settings.verification_reserve_seconds)
        return limit - self.elapsed()

    def _stop(self, limit):
        self.exhausted = self.exhausted or limit
        raise BudgetExceeded(limit)

    def check_time(self, *, final=False):
        """Work stops at the reserve boundary; host verification may use the reserve."""
        self.start()
        if self.remaining_seconds(final=final) <= 0:
            self._stop('wall_seconds' if final else 'work_seconds')

    def reserve_request(self, kind='main', *, final=False):
        if kind not in self.requests:
            raise ValueError(f'Unknown request kind: {kind}')
        self.check_time(final=final)
        if reached(self.state.requests, self.max_requests):
            self._stop('model_requests')
        if reached(self.tokens, self.settings.max_reported_tokens):
            self._stop('reported_tokens')
        self.state.requests += 1
        self.requests[kind] += 1
        if kind != 'main':
            self.state.auxiliary_requests += 1

    def reserve_tool(self):
        self.check_time()
        if reached(self.tool_calls, self.settings.max_tool_calls):
            self._stop('tool_calls')
        self.tool_calls += 1

    def reserve_verification(self, kind):
        self.check_time(final=True)
        self.verifications[kind] = self.verifications.get(kind, 0) + 1

    def record_usage(self, usage):
        # Cached tokens are part of the input and reasoning may be part of the
        # output: only the two totals are added, never their subtotals.
        if usage.input_tokens is None and usage.output_tokens is None:
            self.usage_missing += 1
        self.tokens += (usage.input_tokens or 0) + (usage.output_tokens or 0)
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        # Subtotal of the input: shows whether the provider reuses the conversation prefix.
        self.cached_tokens += getattr(usage, 'cached_input_tokens', 0) or 0
        # Subtotal of the output: the share of generation time spent thinking.
        self.reasoning_tokens += getattr(usage, 'reasoning_tokens', 0) or 0
        self.retries += getattr(usage, 'retries', 0) or 0

    def add_time(self, key, seconds):
        self.seconds[key] = self.seconds.get(key, 0.0) + max(0.0, seconds)

    @contextmanager
    def timed(self, key):
        started = self.clock()
        try:
            yield
        finally:
            self.add_time(key, self.clock() - started)

    def add_tool_time(self, name, seconds):
        entry = self.tool_seconds.setdefault(name, [0, 0.0])
        entry[0] += 1
        entry[1] += max(0.0, seconds)

    def timing(self):
        """Wall time by phase. `model` is the wait for main requests, `tools` the wall
        time of tool execution (calls of one response may overlap, so the per-tool
        seconds can add up to more), `verification` the host rounds. Model requests
        made inside a tool or a verification stage are counted there."""
        get = lambda key: round(self.seconds.get(key, 0.0), 1)
        stages = {key.split('.', 1)[1]: round(value, 1) for key, value in sorted(self.seconds.items())
            if key.startswith('verification.')}
        attributed = get('model.main') + get('tools') + get('verification')
        return {'model_seconds': get('model.main'), 'tools_seconds': get('tools'),
            'verification_seconds': get('verification'), 'other_seconds': round(max(0.0, self.elapsed() - attributed), 1),
            'verification': stages,
            'tools': {name: {'calls': calls, 'seconds': round(seconds, 1)} for name, (calls, seconds)
                in sorted(self.tool_seconds.items(), key=lambda item: -item[1][1])}}

    def report(self):
        return {'elapsed_seconds': round(self.elapsed(), 1), 'wall_seconds': self.settings.wall_seconds or None,
            'verification_reserve_seconds': self.settings.verification_reserve_seconds,
            'requests': {**self.requests, 'total': self.state.requests, 'limit': self.max_requests or None},
            'tool_calls': {'total': self.tool_calls, 'limit': self.settings.max_tool_calls or None},
            'reported_tokens': {'total': self.tokens, 'limit': self.settings.max_reported_tokens or None,
                'input': self.input_tokens, 'output': self.output_tokens, 'cached_input': self.cached_tokens, 'reasoning_output': self.reasoning_tokens,
                'cached_input_ratio': round(self.cached_tokens / self.input_tokens, 3) if self.input_tokens else None,
                'requests_without_usage': self.usage_missing},
            'context_pruning': dict(self.pruned), 'timing': self.timing(),
            'known_transport_retries': self.retries, 'verifications': dict(self.verifications),
            'compactions': len(self.state.compactions), 'stagnation_notices': self.stagnation_notices,
            'exhausted': self.exhausted}


MUTATING = {'run_acceptance_tests', 'delegate_tasks', 'write_file', 'write_files', 'edit_file', 'apply_patch', 'run_command', 'install_dependencies',
    'process_start', 'process_stop', 'todo_write', 'note_write', 'interface_write'}
# Browser interactions and service inspections legitimately repeat with new state.
UNTRACKED = {'browser', 'process_logs', 'process_status', 'http_request'}


class ProgressMonitor:
    """Detect identical calls with identical outcomes while sources stay unchanged.

    A repeated read, error or failing patch earns a redirection notice; persisting
    after the notice ends the turn as stagnated. Any source change resets the
    history, so tasks that progress are never stopped by this monitor.
    """

    def __init__(self, repeats=3):
        self.repeats = max(2, repeats)
        self.history = {}
        self.revision = None
        self.notices = 0

    @staticmethod
    def _digest(value):
        return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def observe(self, call, result, revision):
        """Return None, a redirection notice, or the string 'stop'."""
        if revision != self.revision:
            self.history.clear()
            self.revision = revision
        if call.name in UNTRACKED or (call.name in MUTATING and result.error is None):
            if call.name in MUTATING:
                self.history.clear()
            return None
        outcome = result.error if result.error is not None else result.value
        if isinstance(outcome, dict):
            # Volatile fields do not make an observation new evidence.
            outcome = {k: v for k, v in outcome.items() if k not in {'elapsed_seconds', 'artifact', 'unchanged', 'content'}}
        key = self._digest([call.name, call.arguments])
        signature = self._digest(outcome)
        previous = self.history.get(key)
        count = previous[1] + 1 if previous and previous[0] == signature else 1
        self.history[key] = (signature, count)
        if count >= 2 * self.repeats:
            return 'stop'
        if count == self.repeats:
            self.notices += 1
            return (f'STAGNATION: this exact {call.name} call produced the same outcome {count} times while '
                'application sources did not change. Do not repeat it. Obtain different evidence (logs, an HTTP '
                'request, the database, another file), widen the inspected area, or change your hypothesis.')
        return None
