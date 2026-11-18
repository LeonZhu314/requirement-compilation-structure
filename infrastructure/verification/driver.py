"""Finalization and repair driver.

A final reply of the agent is a completion proposal. The host then runs its mandatory
verification, and only that result decides application success. A repairable failure
returns to the same session as compact feedback (symptoms, expectations, evidence);
the conversation, budget, counters and useful processes are preserved. Outcomes keep
success, functional failure, provider failure, environment problems, interruption,
exhausted budget and missing verification apart.
"""

import asyncio
from dataclasses import dataclass, field

from infrastructure.runtime.budget import BudgetExceeded, reached
from .results import ENVIRONMENT, FAILED, MISSING, PASSED
from .verifier import CANDIDATE, INTEGRITY

ACCEPTED, FUNCTIONAL_FAILURE, PROVIDER_ERROR = 'accepted', 'failed', 'provider_error'
ENVIRONMENT_ERROR, INTERRUPTED, BUDGET_EXCEEDED = 'environment_error', 'interrupted', 'budget_exceeded'
VERIFICATION_MISSING = 'verification_missing'
EXIT_CODES = {ACCEPTED: 0, INTERRUPTED: 130}
# A turn that ended without a proposal for these reasons is continued, not verified as done.
CONTINUE = {
    'incomplete': 'Your previous response was cut off by the output limit and none of its tool calls ran. '
        'Continue the work in smaller steps: shorter messages and smaller edits per call.',
    'stagnated': 'The turn was stopped because identical calls kept returning identical results. Do not repeat them. '
        'State a different hypothesis, gather different evidence, then continue.',
    'context_limit': 'The conversation reached its context limit. Rely on your notes and todo list, read only what '
        'is needed with paging, and continue.',
    # A provider timeout on one long response ended a run at minute 6 with an empty application.
    'provider_error': 'Your previous request failed at the model provider (a very long response timed out) and none '
        'of its tool calls ran. Continue in smaller steps: write a few files per call, shorter messages.',
}


def disputed_review(report):
    """The set-aside tests, once, before the end: a review can be wrong in either direction."""
    lines = [f'Every counted acceptance test passed. The host set aside {len(report["disputed"])} generated tests '
        'that their reviews judged wrong, but a review can be mistaken. For each one, compare what it checks with the '
        'requirement text: if the requirement states it (an element, a text, an attribution, a single control with '
        'that name), fix the application; if not, leave it. Then call run_acceptance_tests again or reply with your '
        'completion summary.']
    for item in report['disputed'][:10]:
        error = next((line.strip() for text in item.get('errors') or [] for line in str(text).splitlines()
            if line.strip() and not line.strip().startswith('Error:')), '')
        first = next((line.strip() for text in item.get('errors') or [] for line in str(text).splitlines() if line.strip()), '')
        page = '; '.join(item.get('page_alerts') or [])
        lines.append(f'- [{", ".join(item.get("covers") or [])}] {item.get("title", "")}: {first[:200]} {error[:300]}'
            + (f' The page showed: {page[:200]}.' if page else ''))
    return '\n'.join(lines)


# Model requests after the last new best before the repair stops. Rounds alone did not stop a
# run whose agent read for an hour between rounds (real run: 8 hours on one site).
NO_PROGRESS_REQUESTS = 150


def requests_without_progress(reports, requests):
    """Model requests since the round that last reached a new maximum of passing tests."""
    best, mark = -1, None
    for report in reports:
        passed = report.get('passed', 0) or 0
        if passed > best:
            best, mark = passed, report.get('requests')
    return 0 if mark is None else max(0, requests - mark)


def rounds_without_progress(reports):
    """Verification rounds since the number of passing tests last reached a new maximum."""
    best, since = -1, 0
    for report in reports:
        passed = report.get('passed', 0) or 0
        if passed > best:
            best, since = passed, 0
        else:
            since += 1
    return since


@dataclass
class Outcome:
    status: str
    cause: str | None = None
    agent_status: str | None = None
    content: str = ''
    verification: dict | None = None
    rounds: int = 0
    budget: dict = field(default_factory=dict)
    coverage: dict | None = None

    @property
    def exit_code(self):
        return EXIT_CODES.get(self.status, 1)

    def to_dict(self):
        verification = self.verification and {key: self.verification.get(key) for key in
            ('round', 'clean_state', 'status', 'stage', 'source_revision', 'evidence', 'stages', 'visual',
             'diagnostic', 'generation_error')}
        return {'status': self.status, 'accepted': self.status == ACCEPTED, 'cause': self.cause,
            'agent_status': self.agent_status, 'content': self.content, 'verification_rounds': self.rounds,
            'verification': verification, 'coverage': self.coverage, 'budget': self.budget}


def budget_line(remaining):
    """Only the limits that exist; none is shown when the run has no limit."""
    parts = [f'{remaining["requests"]} model requests' if remaining.get('requests') is not None else '',
        f'{remaining["seconds"]} s of work time' if remaining.get('seconds') is not None else '']
    parts = [part for part in parts if part]
    return f'Remaining budget: {", ".join(parts)}.' if parts else ''


def feedback(report, *, repeated, remaining):
    """Compact repair feedback: symptoms, expectations and evidence; no test source."""
    lines = [f'Host verification round {report["round"]} did not accept the application '
        f'({"clean delivery state" if report["clean_state"] else "incremental state, new database"}). '
        f'Stage: {report["stage"]}; result: {report["status"]}.']
    failures = report['failures']
    for failure in failures[:8]:
        covers = ', '.join(failure.get('covers') or []) or 'no requirement id'
        title = failure.get('title') or failure.get('key') or failure['stage']
        errors = ' | '.join(error for error in (failure.get('errors') or failure.get('problems') or []) if error)
        shown = failure.get('page_alerts') or []
        page = f' The page showed: {"; ".join(shown)[:300]}.' if shown else ''
        lines.append(f'- [{covers}] {title}: {errors[:700]}{page}')
    if len(failures) > 8:
        lines.append(f'- and {len(failures) - 8} more failures in the evidence artifact.')
    disputed = report.get('disputed') or []
    if disputed:
        lines.append('Set aside, not counted against the application (their reviews judged these generated tests '
            'wrong): ' + ', '.join(','.join(item['covers']) or item['title'] for item in disputed[:12]) + '.')
    visual = report.get('visual') or {}
    for image, item in visual.items():
        if item['status'] != 'similar':
            detail = '; '.join(item.get('differences', [])) or item.get('reason') or str(item.get('metrics', ''))
            lines.append(f'- Visual reference {image}: {item["status"]}. {detail[:400]}')
    lines.append('Expectations: the original requirements are the authority. Re-read the listed ids (in the '
        'requirements you were given, or with read_requirement); the independent tests are host-owned and are not '
        'available to you. A generated test can be wrong: when the page shows your application rightly rejecting '
        'what the test entered, or the test demands something no requirement states, do not bend the application; '
        'call run_acceptance_tests with disputes (scenario and the requirement text it contradicts).')
    lines.append(f'Evidence: read_artifact {report["evidence"]} holds the full report'
        + ''.join(f'; {stage["stage"]} log {stage["artifact"]}' for stage in report['stages']
            if stage.get('artifact') and stage['status'] != PASSED) + '.')
    if report['stopped_services']:
        lines.append('Your services were stopped for the clean validation: ' + ', '.join(report['stopped_services'])
            + '. Restart the ones you still need.')
    if repeated:
        lines.append('These same failures persisted after your previous changes. Do not repeat the previous approach: '
            'obtain different evidence (server logs, http_request, database_query, the browser), widen the area you '
            'inspect across SQL, API and UI, or change your hypothesis about the cause.')
    lines.append('Find the cause in any application layer, correct it, verify locally, then reply when done. '
        + budget_line(remaining))
    return '\n'.join(lines)


class FinalizationDriver:
    def __init__(self, agent, verifier):
        self.agent, self.verifier = agent, verifier
        self.budget = agent.loop.budget
        self.state, self.profile = agent.state, agent.profile

    def remaining(self):
        return {'requests': max(0, self.profile.max_requests - self.state.requests) if self.profile.max_requests else None,
            'seconds': max(0, int(self.budget.remaining_seconds())) if self.budget.time_limited else None}

    def outcome(self, status, result, report=None, cause=None):
        coverage = self.agent.tools.coverage.summary() if self.agent.tools.coverage else None
        outcome = Outcome(status, cause, result.status if result else None, result.content if result else '',
            report, self.verifier.rounds, self.budget.report(), coverage)
        self.agent.record_outcome(outcome)
        return outcome

    async def verify(self):
        """Incremental first; a candidate success must be confirmed from a clean state. When the
        agent's own last round already passed on these very sources, the clean round comes at once
        (real run: an identical incremental round repeated right after the agent's passing one)."""
        last = self.verifier.last_report
        if last and last['status'] == CANDIDATE and last['source_revision'] == self.agent.tools.processes.mirror.revision():
            report = last
        else:
            report = await self.verifier.verify(clean_state=False)
        if report['status'] == CANDIDATE:
            report = await self.verifier.verify(clean_state=True)
        # Restore point of the files this result was obtained on, then the session.
        self.agent.checkpoint(f'verification round {report["round"]}: {report["status"]}')
        self.agent.save()
        return report

    async def run(self, task=None):
        self.budget.start()
        result = None
        try:
            initial = self.agent.tools.processes.mirror.revision()
            result = await self.agent.run(task)
            previous, same, continuations = None, 0, 0
            while True:
                # A failing provider is retried once only: each failed request already waited
                # through its own timeout and retries.
                limit = 1 if result.status == 'provider_error' else 2
                if result.status in CONTINUE and continuations < limit and self.can_continue():
                    continuations += 1
                    result = await self.agent.loop.run(CONTINUE[result.status])
                    continue
                if result.status == 'proposed':
                    continuations = 0
                last = self.verifier.last_report
                revision = self.agent.tools.processes.mirror.revision()
                if revision == initial and not self.verifier.rounds and result.status != 'proposed':
                    # Nothing was written: generating and reviewing tests against the bare template
                    # cost 7 minutes and 34 requests, and reviews then rewrote correct tests.
                    status = PROVIDER_ERROR if result.status == 'provider_error' else FUNCTIONAL_FAILURE
                    return self.outcome(status, result, cause=f'no application file was written (agent turn ended as '
                        f'{result.status}); verification skipped')
                if last and last['status'] == FAILED and last['source_revision'] == revision:
                    # Nothing changed since the last round, the driver's or the agent's own: running
                    # it again costs minutes and returns the same failures.
                    if previous or getattr(self.agent, 'stuck', False):
                        return self.outcome(FUNCTIONAL_FAILURE, result, last, 'stagnation: no source change after feedback')
                    report = last
                elif last and last.get('accepted') and last['source_revision'] == revision:
                    report = last  # Accepted and unchanged since (e.g. after looking at set-aside tests).
                else:
                    # Whatever ended the turn, the delivered state is verified by the host.
                    try:
                        report = await self.verify()
                    except BudgetExceeded as error:
                        return self.outcome(BUDGET_EXCEEDED, result, cause=f'{error.limit}; verification could not run')
                if report['status'] == PASSED and report['accepted']:
                    if report.get('disputed') and not getattr(self.agent, '_disputed_shown', True) and self.can_continue():
                        self.agent._disputed_shown = True
                        result = await self.agent.loop.run(disputed_review(report))
                        continue
                    return self.outcome(ACCEPTED, result, report)
                if report['status'] == ENVIRONMENT:
                    return self.outcome(ENVIRONMENT_ERROR, result, report, report.get('diagnostic') or report['stage'])
                if report['status'] == INTEGRITY:
                    return self.outcome(FUNCTIONAL_FAILURE, result, report, 'protected requirements or tests were modified')
                # From here the application is not accepted; decide whether repair can continue.
                if result.status == 'provider_error':
                    return self.outcome(PROVIDER_ERROR, result, report, 'model provider failed; application not accepted')
                if result.status == 'budget_exceeded' or not self.can_continue():
                    return self.outcome(BUDGET_EXCEEDED, result, report, result.limit or self.budget.exhausted or 'budget')
                if report['status'] == MISSING and not report['failures'][0].get('key'):
                    # Nothing independent can judge behavior: explicit, neither success nor failure.
                    return self.outcome(VERIFICATION_MISSING, result, report, report['failures'][0]['errors'][0])
                if result.status not in {'proposed', *CONTINUE}:
                    return self.outcome(FUNCTIONAL_FAILURE, result, report, f'agent turn ended as {result.status}')
                # Every round counts, also those the agent started with run_acceptance_tests.
                trailing = 0
                for past in reversed(self.verifier.reports):
                    if past.get('fingerprint') != report['fingerprint']:
                        break
                    trailing += 1
                if trailing >= 2 * self.profile.budget.stagnation_repeats:
                    return self.outcome(FUNCTIONAL_FAILURE, result, report, 'stagnation: same failures after repeated repairs')
                if previous and previous['fingerprint'] == report['fingerprint']:
                    if previous['source_revision'] == report['source_revision']:
                        return self.outcome(FUNCTIONAL_FAILURE, result, report, 'stagnation: no source change after feedback')
                    same += 1
                    if same >= self.profile.budget.stagnation_repeats:
                        return self.outcome(FUNCTIONAL_FAILURE, result, report, 'stagnation: same failures after repeated repairs')
                else:
                    same = 0
                # Failures that change a little each round never repeat exactly (real run: 16, 17,
                # 16, 17, 18 passing over 9 rounds, 99 minutes): rounds that add no passing test count.
                idle = rounds_without_progress(self.verifier.reports)
                if idle and requests_without_progress(self.verifier.reports, self.state.requests) >= NO_PROGRESS_REQUESTS:
                    return self.outcome(FUNCTIONAL_FAILURE, result, report,
                        f'stagnation: no new passing test in the last {NO_PROGRESS_REQUESTS} model requests')
                if idle >= self.profile.budget.stagnation_repeats:
                    return self.outcome(FUNCTIONAL_FAILURE, result, report,
                        f'stagnation: no new passing test in the last {idle} verification rounds')
                # 0: no fixed number of rounds; the stagnation checks above still stop a repair
                # loop that no longer changes the failures.
                if reached(self.verifier.rounds, self.profile.budget.max_verification_rounds):
                    return self.outcome(FUNCTIONAL_FAILURE, result, report, 'verification rounds exhausted')
                previous = report
                # Same session: conversation, budget, counters and services are preserved.
                result = await self.agent.loop.run(feedback(report, repeated=same > 0, remaining=self.remaining()))
        except (asyncio.CancelledError, KeyboardInterrupt):
            return self.outcome(INTERRUPTED, result, cause='interrupted; completed file writes are retained')

    def can_continue(self):
        return (self.budget.remaining_seconds() > 0 and not reached(self.state.requests, self.profile.max_requests)
            and not reached(self.budget.tokens, self.profile.budget.max_reported_tokens)
            and not reached(self.budget.tool_calls, self.profile.budget.max_tool_calls))
