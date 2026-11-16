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
}


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
        lines.append(f'- [{covers}] {title}: {errors[:700]}')
    if len(failures) > 8:
        lines.append(f'- and {len(failures) - 8} more failures in the evidence artifact.')
    visual = report.get('visual') or {}
    for image, item in visual.items():
        if item['status'] != 'similar':
            detail = '; '.join(item.get('differences', [])) or item.get('reason') or str(item.get('metrics', ''))
            lines.append(f'- Visual reference {image}: {item["status"]}. {detail[:400]}')
    lines.append('Expectations: the original requirements are the authority. Re-read the listed ids with '
        'read_requirement; the independent tests are host-owned and are not available to you.')
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
        """Incremental first; a candidate success must be confirmed from a clean state."""
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
            result = await self.agent.run(task)
            previous, same, continuations = None, 0, 0
            while True:
                if result.status in CONTINUE and continuations < 2 and self.can_continue():
                    continuations += 1
                    result = await self.agent.loop.run(CONTINUE[result.status])
                    continue
                if result.status == 'proposed':
                    continuations = 0
                # Whatever ended the turn, the delivered state is verified by the host.
                try:
                    report = await self.verify()
                except BudgetExceeded as error:
                    return self.outcome(BUDGET_EXCEEDED, result, cause=f'{error.limit}; verification could not run')
                if report['status'] == PASSED and report['accepted']:
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
                if previous and previous['fingerprint'] == report['fingerprint']:
                    if previous['source_revision'] == report['source_revision']:
                        return self.outcome(FUNCTIONAL_FAILURE, result, report, 'stagnation: no source change after feedback')
                    same += 1
                    if same >= self.profile.budget.stagnation_repeats:
                        return self.outcome(FUNCTIONAL_FAILURE, result, report, 'stagnation: same failures after repeated repairs')
                else:
                    same = 0
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
