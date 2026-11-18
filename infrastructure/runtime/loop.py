"""Owned async conversation loop; no numbered stages and no automatic acceptance."""

import asyncio
from dataclasses import asdict, dataclass
import json

from .budget import Budget, BudgetExceeded, ProgressMonitor, reached
from .events import AgentEvent
from .messages import Message, ToolResult
from .model import ProviderError
from .context import ContextWindow, size


@dataclass(frozen=True)
class TurnResult:
    status: str
    content: str
    events: tuple[AgentEvent, ...]
    limit: str | None = None  # Which budget stopped the turn, when status is budget_exceeded.


# Calls that produce or check the application; anything else only looks.
PRODUCING = {'write_file', 'write_files', 'edit_file', 'apply_patch', 'delegate_tasks', 'run_acceptance_tests',
    'verify_application', 'interface_write'}
LOOKING_STEPS = 12
# Past this many steps without writing, the turn ends and the host verifies the application as it
# is: its feedback replaces the reading (real run: 96 steps, about an hour, without a write).
LOOKING_LIMIT = 48
LOOKING_NOTICE = ('{steps} steps in a row without writing a file. Reading more does not help: older observations '
    'leave the conversation, so what is not written into code is lost. Write the code of one feature now with '
    'write_files (several files in one call), from what you already know, then continue with the next feature.')


class AgentLoop:
    def __init__(self, state, model, tools, profile):
        self.state, self.model, self.tools, self.profile = state, model, tools, profile
        self.events = []
        self._active = None
        self._closed = False
        self.context = ContextWindow(state, tools, profile)
        # One budget and one progress history for the whole session, repairs included.
        self.budget = Budget(state, profile.max_requests, profile.budget)
        self.progress = ProgressMonitor(profile.budget.stagnation_repeats)
        self.looking = 0
        self.limit = None
        tools.budget = self.budget
        self.on_event = self.on_save = None  # Persistence hooks set by the session owner.

    def emit(self, kind, **data):
        self.events.append(AgentEvent(kind, self.state.id, data))
        if self.on_event:
            self.on_event(kind, data)

    def cancel(self):
        if self._active is not None:
            self._active.cancel()

    async def run(self, prompt, attachments=None):
        if self._closed or self._active is not None:
            raise RuntimeError('Session is closed or already running')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('A nonempty task or correction is required')
        start = len(self.events)
        self._active = asyncio.current_task()
        self.state.status = 'running'
        self.state.messages.append(Message('user', prompt))
        if attachments:
            # A separate message: compaction may drop it, never the task itself.
            text, images = attachments
            self.state.messages.append(Message('user', text, images=tuple(images)))
        pending = []
        content = ''
        stagnated = False
        self.limit = None
        self.budget.start()
        try:
            while True:
                if reached(self.state.requests, self.profile.max_requests):
                    self.state.status, self.limit = 'budget_exceeded', 'model_requests'
                    self.budget.exhausted = self.budget.exhausted or 'model_requests'
                    self.emit('error', code='request_limit')
                    break
                pruned = self.context.prune()
                if pruned:
                    self.budget.pruned['passes'] += 1
                    self.budget.pruned['observations'] += pruned['observations']
                    self.budget.pruned['bytes'] += pruned['saved_bytes']
                    self.emit('pruned', **pruned)
                compacted = self.context.compact()
                if compacted:
                    self.emit('compacted', **compacted)
                context_bytes = size(self.state.messages) + len(json.dumps(self.tools.schemas()).encode())
                if context_bytes > self.context.limit():
                    self.state.status = 'context_limit'
                    self.emit('error', code='context_limit', bytes=context_bytes)
                    break
                self.budget.reserve_request('main')
                with self.budget.timed('model.main'):
                    response = await self.model.respond(list(self.state.messages), self.tools.schemas())
                self.state.usage.append(response.usage)
                self.budget.record_usage(response.usage)
                self.emit('usage', **asdict(response.usage))
                content = response.content
                if response.finish_reason not in {'stop', 'tool_calls'}:
                    self.state.status = 'incomplete'
                    self.emit('error', code='incomplete_response', finish_reason=response.finish_reason)
                    break  # Never run tools from a cut-off or refused batch.
                if response.finish_reason == 'tool_calls' and not response.tool_calls:
                    raise ProviderError('Provider announced tool calls but supplied none')
                if not content and not response.tool_calls:
                    raise ProviderError('Provider returned an empty response')
                if len(response.tool_calls) > self.profile.max_tools_per_response:
                    self.state.status, self.limit = 'budget_exceeded', 'tool_batch'
                    self.emit('error', code='tool_batch_limit')
                    break
                try:
                    message = response.message()
                except ValueError as error:
                    raise ProviderError(str(error)) from error
                self.state.messages.append(message)
                pending = list(response.tool_calls)
                # Steps in a row that only look (reads, listings, commands) without producing
                # anything. Real runs read for an hour and wrote three files.
                nudge = None
                if pending and not any(call.name in PRODUCING for call in pending):
                    self.looking += 1
                    if self.looking % LOOKING_STEPS == 0:
                        nudge = LOOKING_NOTICE.format(steps=self.looking)
                        self.emit('looking', steps=self.looking)
                    if self.looking >= LOOKING_LIMIT and getattr(self.tools, 'acceptance_runner', None):
                        self.tools.finish_requested = True
                        self.tools.finish_note = (f'{self.looking} steps in a row without writing a file; the host '
                            'ended the work turn to verify the application as it is.')
                        self.looking = 0
                elif pending:
                    self.looking = 0
                if content:
                    self.emit('text', content=content)
                if not pending:
                    self.state.status = 'proposed'
                    self.emit('final', content=content, accepted=False)
                    break
                while pending and not stagnated:
                    # Yield between groups so cancellation prevents subsequent effects.
                    await asyncio.sleep(0)
                    # Consecutive read-only calls run together; anything with an effect
                    # runs alone, in the order the model gave.
                    group = [pending[0]]
                    if self.tools.concurrent(pending[0]):
                        for call in pending[1:]:
                            if not self.tools.concurrent(call):
                                break
                            group.append(call)
                    previous_usage = len(self.state.usage)
                    for call in group:
                        self.budget.reserve_tool()
                    for call in group:
                        self.emit('tool_started', call_id=call.id, name=call.name)
                    with self.budget.timed('tools'):
                        if len(group) == 1:
                            results = [await self._execute(group[0])]
                        else:
                            tasks = [asyncio.ensure_future(self._execute(call)) for call in group]
                            try:
                                results = await asyncio.gather(*tasks)
                            except BaseException:
                                # A budget stop or cancellation leaves no call running behind.
                                for task in tasks:
                                    task.cancel()
                                await asyncio.gather(*tasks, return_exceptions=True)
                                raise
                    for usage in self.state.usage[previous_usage:]:
                        self.budget.record_usage(usage)
                        self.emit('usage', source='auxiliary', **asdict(usage))
                    # Observations are recorded in the order of the calls, whatever finished first.
                    for call, result in zip(group, results):
                        verdict = self.progress.observe(call, result, self.tools.processes.mirror.revision())
                        if isinstance(verdict, str) and verdict != 'stop':
                            self.budget.stagnation_notices += 1
                            self.emit('stagnation', call_id=call.id, name=call.name)
                            result = ToolResult(result.call_id, result.name, result.value,
                                (result.error + ' | ' if result.error else '') + verdict)
                        if nudge and len(pending) == 1:
                            # On the last observation of the step, where the model reads next.
                            value = {**result.value, 'host_notice': nudge} if isinstance(result.value, dict) \
                                else {'result': result.value, 'host_notice': nudge}
                            result = ToolResult(result.call_id, result.name, value, result.error)
                        self.state.messages.append(result.message())
                        pending.pop(0)
                        self.emit('tool_finished', **asdict(result))
                        if verdict == 'stop':
                            stagnated = True
                            break
                if stagnated:
                    self.state.status = 'stagnated'
                    self.emit('error', code='stagnation')
                    break
                notice = self.time_notice()
                if notice:
                    self.state.messages.append(Message('user', notice))
                    self.emit('time_notice', content=notice)
                # Multimodal observations follow the whole native-tool batch.
                self.state.messages.extend(self.tools.observations)
                self.tools.observations.clear()
                if self.on_save:
                    self.on_save()  # A complete, balanced transcript.
                if getattr(self.tools, 'finish_requested', False):
                    self.tools.finish_requested = False
                    content = getattr(self.tools, 'finish_note', None) or \
                        'All host acceptance tests passed; the host ended the work turn for final verification.'
                    self.tools.finish_note = None
                    self.state.status = 'proposed'
                    self.emit('final', content=content, accepted=False, ended_by='acceptance')
                    break
        except asyncio.CancelledError:
            self.state.status = 'cancelled'
            self.emit('cancelled', note='Completed file writes are retained')
            await self.tools.cancel_actions()
            raise
        except BudgetExceeded as error:
            self.state.status, self.limit = 'budget_exceeded', error.limit
            self.emit('error', code='budget_exceeded', limit=error.limit)
        except ProviderError as error:
            self.state.status = 'provider_error'
            self.emit('error', code='provider_error', message=str(error))
        except Exception:
            self.state.status = 'failed'
            self.emit('error', code='runtime_error')
            raise
        finally:
            # Preserve a valid transcript for a later correction after cancellation.
            for call in pending:
                self.state.messages.append(ToolResult(call.id, call.name,
                    error='Execution interrupted; inspect files before retrying').message())
            self._active = None
            self.tools.observations.clear()
            if self.on_save:
                self.on_save()
        return TurnResult(self.state.status, content, tuple(self.events[start:]), self.limit)

    def time_notice(self):
        """Tell the agent once at half and once at 80% of its work time. Agents tend to keep
        testing by hand; the host verification is faster and returns precise failures."""
        if not self.profile.budget.wall_seconds:
            return None  # No time limit, so no deadline to announce.
        limit = self.profile.budget.wall_seconds - self.profile.budget.verification_reserve_seconds
        used = self.budget.elapsed() / limit if limit > 0 else 0
        sent = getattr(self, '_notices', set())
        self._notices = sent
        minutes = max(0, int((limit - self.budget.elapsed()) // 60))
        if used >= 0.8 and 0.8 not in sent:
            sent.update({0.5, 0.8})
            return (f'Time check: about {minutes} minutes of work time remain. Finish now: fix only what blocks the '
                'build or startup, run verify_application (kind all), then reply with your completion summary and no '
                'tool call. Unfinished work after the deadline is verified as it stands.')
        if used >= 0.5 and 0.5 not in sent:
            sent.add(0.5)
            return (f'Time check: half of the work time is used ({minutes} minutes remain). Stop manual testing with '
                'curl, the database or the browser. Once verify_application (kind all) passes, reply with your '
                'completion summary and no tool call: the host then runs the acceptance tests and returns precise '
                'failures to fix.')
        return None

    async def _execute(self, call):
        started = self.budget.clock()
        try:
            return await self.tools.execute(call)
        finally:
            self.budget.add_tool_time(call.name, self.budget.clock() - started)

    async def aclose(self):
        if self._active is not None:
            task = self._active
            if task is asyncio.current_task():
                raise RuntimeError('Cannot close a session from inside its own turn')
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not self._closed:
            self._closed = True
            try:
                await self.tools.aclose()
            finally:
                await self.model.aclose()
