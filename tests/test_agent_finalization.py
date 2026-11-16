"""Delivery C, steps 16-17: finalization, repair in one session, budgets and stagnation."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.budget import Budget, BudgetExceeded, BudgetSettings, ProgressMonitor
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ModelResponse, ToolCall, ToolResult, Usage
from infrastructure.runtime.model import ProviderError, ScriptedModel
from infrastructure.runtime.state import SessionState
from tests.verification_support import GENERATED, call, make_agent, tools


def write(content, identity='w'):
    return tools(call('write_file', identity, path='behaviors.txt', content=content))


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_agent(self, responses, **changes):
        agent, tooling, log = make_agent(self.root, ScriptedModel(responses), **changes)
        try:
            outcome = await agent.generate(tooling=tooling)
            return agent, tooling, log, outcome
        finally:
            await agent.aclose()

    async def test_proposal_real_failure_repair_and_clean_acceptance_in_one_session(self):
        responses = [write('SCN-A-1'), ModelResponse('Done: registration works.'),
            ModelResponse(GENERATED),                                  # Host: one test for the uncovered scenario.
            ModelResponse('KEEP The application does not show the second account.'),   # Host: review of that test.
            write('SCN-A-1 SCN-A-2 SCN-B-1', 'fix'), ModelResponse('Fixed duplicates and the profile.')]
        agent, tooling, log, outcome = await self.run_agent(responses)
        self.assertEqual((outcome.status, outcome.exit_code), ('accepted', 0))
        self.assertTrue(outcome.verification['clean_state'])
        self.assertEqual(outcome.agent_status, 'proposed')
        # One conversation: the failure came back as a user message of the same session.
        users = [m.content for m in agent.state.messages if m.role == 'user']
        self.assertEqual(len(users), 2)
        feedback = users[1]
        for expected in ('SCN-A-2', 'SCN-B-1', 'read_requirement', 'read_artifact'):  # No limit, so no budget line.
            self.assertIn(expected, feedback)
        self.assertNotIn('page.goto', feedback)                      # Symptoms and evidence, not test source.
        # Budget and counters accumulate over work, host requests and repair.
        budget = outcome.budget
        self.assertEqual(budget['requests'], {'main': 4, 'subagent': 0, 'visual_fallback': 0, 'acceptance_generation': 1,
            'test_review': 1, 'visual_review': 0, 'total': 6, 'limit': agent.profile.max_requests or None})
        self.assertEqual(budget['verifications'], {'incremental': 2, 'clean': 1})
        self.assertEqual(outcome.rounds, 3)
        # Repair round replayed the failing files first, then the whole suite from a clean state.
        self.assertEqual(len(tooling.runs[0]), 2)
        self.assertEqual(log['resets'], 1)
        self.assertEqual(outcome.coverage['functional'], {'passed': 3})
        self.assertEqual(outcome.coverage['omissions'], [])
        self.assertEqual([v['status'] for v in agent.state.verifications], ['failed', 'candidate', 'passed'])

    async def test_first_proposal_is_never_accepted_without_host_verification(self):
        agent, tooling, log, outcome = await self.run_agent([ModelResponse('All done, everything passes.')], generate=False)
        self.assertNotEqual(outcome.status, 'accepted')
        self.assertEqual(outcome.verification['stage'], 'acceptance')
        self.assertEqual(outcome.exit_code, 1)

    async def test_unchanged_sources_after_feedback_stop_as_stagnation(self):
        responses = [write('SCN-A-1'), ModelResponse('Done.'), ModelResponse('It should already work.')]
        agent, tooling, log, outcome = await self.run_agent(responses, generate=False)
        self.assertEqual((outcome.status, outcome.cause), ('failed', 'stagnation: no source change after feedback'))
        self.assertEqual(outcome.rounds, 2)

    async def test_same_failures_after_real_changes_are_redirected_then_stopped(self):
        responses = [write('SCN-A-1'), ModelResponse('Done.')]
        for index in range(6):
            responses += [write(f'SCN-A-1 attempt-{index}', f'w{index}'), ModelResponse('Tried again.')]
        agent, tooling, log, outcome = await self.run_agent(responses, generate=False, stagnation_repeats=2)
        self.assertEqual((outcome.status, outcome.cause), ('failed', 'stagnation: same failures after repeated repairs'))
        users = [m.content for m in agent.state.messages if m.role == 'user']
        self.assertNotIn('change your hypothesis', users[1])
        self.assertIn('change your hypothesis', users[2])           # Reoriented before being stopped.
        self.assertEqual(len(users), 3)

    async def test_provider_environment_missing_and_budget_outcomes_are_distinct(self):
        def provider(messages, schemas):
            raise ProviderError('status=503')
        agent, tooling, log, outcome = await self.run_agent([write('SCN-A-1'), provider], generate=False)
        self.assertEqual((outcome.status, outcome.agent_status), ('provider_error', 'provider_error'))
        self.assertEqual(outcome.verification['status'], 'failed')   # The delivered state was still verified.

    async def test_environment_error_is_not_an_application_failure(self):
        agent, tooling, log = make_agent(self.root, ScriptedModel([ModelResponse('Done.')]), generate=False)
        tooling.environment_error = 'Node.js is required on the host to run acceptance tests'
        try:
            outcome = await agent.generate(tooling=tooling)
        finally:
            await agent.aclose()
        self.assertEqual(outcome.status, 'environment_error')
        self.assertIn('Node.js', outcome.cause)

    async def test_missing_verification_is_neither_success_nor_functional_failure(self):
        agent, tooling, log, outcome = await self.run_agent([ModelResponse('Done.')], external=False, generate=False)
        self.assertEqual(outcome.status, 'verification_missing')
        self.assertEqual(outcome.exit_code, 1)

    async def test_request_budget_is_shared_and_not_reset_by_repairs(self):
        responses = [write('SCN-A-1'), ModelResponse('Done.'), write('SCN-A-1 x', 'w2'), ModelResponse('Again.')]
        agent, tooling, log, outcome = await self.run_agent(responses, generate=False, max_requests=3)
        self.assertEqual((outcome.status, outcome.cause), ('budget_exceeded', 'model_requests'))
        self.assertEqual(agent.state.requests, 3)
        self.assertEqual(outcome.verification['status'], 'failed')

    async def test_truncated_reply_is_continued_and_never_counted_as_done(self):
        responses = [ModelResponse('I will now write', finish_reason='length'),
            write('SCN-A-1 SCN-A-2'), ModelResponse('Done.')]
        agent, tooling, log, outcome = await self.run_agent(responses, generate=False)
        self.assertEqual(outcome.status, 'accepted')
        users = [m.content for m in agent.state.messages if m.role == 'user']
        self.assertIn('cut off by the output limit', users[1])
        # Once by the warm-up at the start, then by each verification round: the cut-off reply
        # itself is never verified.
        self.assertEqual(tooling.ensured, 3)

    async def test_interruption_keeps_writes_and_reports_interrupted(self):
        started = asyncio.Event()
        async def slow_run(*args, **kwargs):
            started.set()
            await asyncio.sleep(60)
        agent, tooling, log = make_agent(self.root, ScriptedModel([write('SCN-A-1'), ModelResponse('Done.')]), generate=False)
        tooling.run = slow_run
        try:
            task = asyncio.create_task(agent.generate(tooling=tooling))
            await asyncio.wait_for(started.wait(), 30)
            task.cancel()
            outcome = await task
            self.assertEqual((outcome.status, outcome.exit_code), ('interrupted', 130))
            self.assertEqual((agent.state.workspace / 'behaviors.txt').read_text(), 'SCN-A-1')
        finally:
            await agent.aclose()
        self.assertTrue(agent.loop.model.closed)                     # Session cleanup still ran.

    async def test_modified_protected_tests_end_as_a_policy_failure(self):
        agent, tooling, log = make_agent(self.root, ScriptedModel([ModelResponse('Done.')]), generate=False)
        try:
            # The verifier snapshots protected files when verification is first set up.
            from infrastructure.verification.verifier import HostVerifier
            agent.verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget,
                agent.loop.model, agent.input_dir, tooling=tooling)
            (agent.state.workspace / 'backend/tests/support/context.ts').write_text('// weakened')
            outcome = await agent.generate(tooling=tooling)
        finally:
            await agent.aclose()
        self.assertEqual((outcome.status, outcome.cause), ('failed', 'protected requirements or tests were modified'))


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    def budget(self, max_requests=5, now=None, **settings):
        state = SessionState(Path('.'))
        clock = (lambda: now[0]) if now else (lambda: 0.0)
        return Budget(state, max_requests, BudgetSettings(**settings), clock), state

    def test_limits_categories_and_tokens_without_double_counting(self):
        budget, state = self.budget(max_requests=3, max_tool_calls=2, max_reported_tokens=100)
        budget.reserve_request('main')
        budget.reserve_request('acceptance_generation')
        budget.record_usage(Usage(40, 10, cached_input_tokens=30, reasoning_tokens=8, retries=2))
        budget.record_usage(Usage())
        self.assertEqual((budget.tokens, budget.usage_missing, budget.retries), (50, 1, 2))
        self.assertEqual((state.requests, state.auxiliary_requests), (2, 1))
        budget.reserve_tool(); budget.reserve_tool()
        with self.assertRaises(BudgetExceeded) as raised:
            budget.reserve_tool()
        self.assertEqual(raised.exception.limit, 'tool_calls')
        budget.record_usage(Usage(60, 0))
        with self.assertRaises(BudgetExceeded) as raised:
            budget.reserve_request('main')
        self.assertEqual(raised.exception.limit, 'reported_tokens')
        report = budget.report()
        self.assertEqual(report['requests']['acceptance_generation'], 1)
        self.assertEqual(report['known_transport_retries'], 2)
        self.assertEqual(report['exhausted'], 'tool_calls')

    def test_work_stops_at_the_reserve_while_final_verification_can_still_run(self):
        now = [0.0]
        budget, _ = self.budget(now=now, wall_seconds=100, verification_reserve_seconds=30)
        budget.reserve_request('main')
        now[0] = 75.0
        with self.assertRaises(BudgetExceeded) as raised:
            budget.reserve_request('main')
        self.assertEqual(raised.exception.limit, 'work_seconds')
        budget.reserve_verification('clean')                         # Inside the reserve.
        budget.reserve_request('test_review', final=True)
        now[0] = 101.0
        with self.assertRaises(BudgetExceeded) as raised:
            budget.reserve_verification('clean')
        self.assertEqual(raised.exception.limit, 'wall_seconds')

    def test_repeated_identical_outcomes_are_noticed_then_stopped_unless_sources_change(self):
        monitor = ProgressMonitor(repeats=3)
        read = ToolCall('c', 'read_file', '{"path":"a.ts"}')
        same = ToolResult('c', 'read_file', {'path': 'a.ts', 'sha256': 'x', 'unchanged': True, 'artifact': 'z'})
        verdicts = [monitor.observe(read, same, 'rev1') for _ in range(6)]
        self.assertEqual([v if v in (None, 'stop') else 'notice' for v in verdicts],
            [None, None, 'notice', None, None, 'stop'])
        # The same failing patch is a repetition too; a source change clears the history.
        patch = ToolCall('p', 'apply_patch', '{"changes":[]}')
        error = ToolResult('p', 'apply_patch', error='Patch requires one exact old_content match')
        self.assertEqual([monitor.observe(patch, error, 'rev2') is None for _ in range(3)], [True, True, False])
        self.assertIsNone(monitor.observe(patch, error, 'rev3'))
        # Progressing work: different calls and successful writes never accumulate.
        fresh = ProgressMonitor(repeats=2)
        for index in range(20):
            write_call = ToolCall('w', 'write_file', json.dumps({'path': 'a.ts', 'content': str(index)}))
            self.assertIsNone(fresh.observe(write_call, ToolResult('w', 'write_file', {'bytes': 1}), f'rev{index}'))
            self.assertIsNone(fresh.observe(read, same, f'rev{index}'))

    async def test_loop_redirects_then_stops_an_injected_repetition(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'app'
            workspace.mkdir()
            (workspace / 'app.ts').write_text('export const value = 1;\n')
            repeated = [tools(call('search_text', f's{index}', query='missing-symbol')) for index in range(8)]
            base = load_profile(environment={})
            agent = ApplicationAgent(workspace, model=ScriptedModel(repeated),
                profile=replace(base, budget=replace(base.budget, stagnation_repeats=2)))
            try:
                result = await agent.run('Find the symbol.')
                self.assertEqual(result.status, 'stagnated')
                self.assertEqual(agent.state.requests, 4)             # Stopped well before the script ended.
                observations = [m.content for m in agent.state.messages if m.role == 'tool']
                self.assertIn('STAGNATION', observations[1])
                self.assertNotIn('STAGNATION', observations[0])
                self.assertEqual(agent.loop.budget.report()['stagnation_notices'], 1)
            finally:
                await agent.aclose()

    async def test_tool_budget_ends_the_turn_explicitly_with_a_balanced_transcript(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'app'
            workspace.mkdir()
            base = load_profile(environment={})
            model = ScriptedModel([tools(call('list_files', 'a'), call('list_files', 'b', prefix='x'), call('list_files', 'c', prefix='y'))])
            agent = ApplicationAgent(workspace, model=model, profile=replace(base, budget=replace(base.budget, max_tool_calls=2)))
            try:
                result = await agent.run('List files.')
                self.assertEqual((result.status, result.limit), ('budget_exceeded', 'tool_calls'))
                calls = [c.id for m in agent.state.messages for c in m.tool_calls]
                self.assertEqual(calls, [m.tool_call_id for m in agent.state.messages if m.role == 'tool'])
            finally:
                await agent.aclose()


if __name__ == '__main__':
    unittest.main()
