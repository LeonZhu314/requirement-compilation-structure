"""Fixes from a real run that was still self-testing after an hour (2026-11-16)."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.context import size
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall, ToolResult
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.tools import long_running
from tests.verification_support import call, make_agent, tools


class SpeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.agent, _, self.log = make_agent(Path(self.tmp.name), ScriptedModel([]), observation_window=3,
            prune_min_bytes=1000)

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    def batch(self, identity, name, arguments, result):
        request = ToolCall(identity, name, json.dumps(arguments))
        self.agent.state.messages += [Message('assistant', 'thinking about ' + identity, tool_calls=(request,)),
            ToolResult(identity, name, result).message()]

    async def test_old_observations_and_written_text_are_masked_but_recent_ones_and_actions_stay(self):
        body = 'export const line = "' + 'x' * 80 + '";\n'
        self.batch('w', 'write_files', {'files': [{'path': 'a.ts', 'content': body * 60}]}, {'files': [{'path': 'a.ts'}]})
        self.batch('r', 'run_command', {'command': ['npm', 'test']}, {'content': 'log line\n' * 400, 'returncode': 1})
        self.batch('e', 'edit_file', {'path': 'b.ts', 'operation': 'replace', 'old_content': 'o' * 900,
            'new_content': 'n' * 900}, {'path': 'b.ts'})
        for index in range(3):
            self.batch(f'recent{index}', 'search_text', {'query': f'q{index}'}, {'matches': ['m' * 1500]})
        before = size(self.agent.state.messages)
        original = next(m.content for m in self.agent.state.messages if m.tool_call_id == 'r')
        event = self.agent.loop.context.prune()
        self.assertGreater(event['saved_bytes'], 8000)
        self.assertLess(size(self.agent.state.messages), before - 8000)
        messages = {m.tool_call_id: m for m in self.agent.state.messages if m.role == 'tool'}
        calls = {c.id: c for m in self.agent.state.messages for c in m.tool_calls}
        # Old observation: a placeholder that names its artifact; the exact text is still there.
        masked = json.loads(messages['r'].content)['result']
        self.assertIn('masked', masked['pruned'])
        self.assertEqual(self.agent.tools.artifacts.read(masked['artifact'], limit=200000)['content'], original)
        # Old writes keep their paths and operations, not the written text, and stay valid JSON.
        written = json.loads(calls['w'].arguments)['files'][0]
        self.assertEqual(written['path'], 'a.ts')
        self.assertIn('characters omitted', written['content'])
        self.assertEqual(json.loads(calls['e'].arguments)['operation'], 'replace')
        # Reasoning, the latest batches and the call/answer pairing are untouched.
        self.assertIn('thinking about w', [m.content for m in self.agent.state.messages if m.role == 'assistant'][0])
        self.assertEqual(json.loads(messages['recent2'].content)['result'], {'matches': ['m' * 1500]})
        self.assertEqual([c for m in self.agent.state.messages for c in m.tool_calls if c.id == 'recent0'][0].arguments,
            '{"query": "q0"}')
        self.assertIsNone(self.agent.loop.context.prune())

    async def test_a_compaction_leaves_room_instead_of_compacting_again_at_every_request(self):
        agent = self.agent
        agent.loop.context.profile = replace(agent.profile, max_context_bytes=60000, prune_min_bytes=0, observation_window=0)
        for index in range(30):
            self.batch(f'c{index}', 'list_files', {'offset': index}, 'x' * 2000)
        event = agent.loop.context.compact()
        threshold = (60000 - len(json.dumps(agent.tools.schemas()).encode())) * agent.profile.compact_ratio
        self.assertLess(event['after_bytes'], threshold * 0.7)
        self.batch('next', 'list_files', {'offset': 99}, 'x' * 2000)
        self.assertIsNone(agent.loop.context.compact())               # One more batch does not compact again.

    async def test_servers_are_refused_in_run_command_and_commands_default_to_a_short_timeout(self):
        for command in (['npm', 'run', 'start'], ['npm', 'start'], ['node', 'backend/dist/server.js'],
                ['sh', '-c', 'cd frontend && npx vite'], ['npx', 'tsx', 'watch', 'src/server.ts']):
            self.assertTrue(long_running(command), command)
            result = await self.agent.tools.execute(call('run_command', command=command))
            self.assertIn('process_start', result.error)
        for command in (['npm', 'run', 'build'], ['npx', 'tsc', '-p', 'backend'], ['sh', '-c', 'npx vite build'],
                ['node', '-e', 'console.log(1)'], ['curl', 'localhost:3000']):
            self.assertFalse(long_running(command), command)
        seen = {}

        async def run(command, timeout=None, env=None):
            seen['timeout'] = timeout
            return {'status': 'timed_out', 'returncode': None, 'content': '', 'accepted': False}
        self.agent.tools.processes.run = run
        result = (await self.agent.tools.execute(call('run_command', command=['npm', 'ci']))).value
        self.assertEqual(seen['timeout'], 120)
        self.assertIn('process_start', result['notice'])
        await self.agent.tools.execute(call('run_command', command=['npm', 'ci'], timeout=300))
        self.assertEqual(seen['timeout'], 300)

    async def test_the_agent_is_told_once_at_half_and_once_near_the_end_of_its_work_time(self):
        # Only with a time limit (main.py --max-seconds, or wall_seconds in a profile).
        bounded = replace(self.agent.profile, budget=replace(self.agent.profile.budget, wall_seconds=2700))
        self.agent.profile = self.agent.loop.profile = bounded
        self.agent.loop.budget.settings = bounded.budget
        budget = self.agent.loop.budget
        limit = self.agent.profile.budget.wall_seconds - self.agent.profile.budget.verification_reserve_seconds
        clock = [1000.0]
        budget.clock = lambda: clock[0]
        budget.started = 1000.0
        loop = self.agent.loop
        self.assertIsNone(loop.time_notice())
        clock[0] += limit * 0.55
        self.assertIn('Stop manual testing', loop.time_notice())
        self.assertIsNone(loop.time_notice())
        clock[0] += limit * 0.3
        self.assertIn('Finish now', loop.time_notice())
        self.assertIsNone(loop.time_notice())
        # In a session the notice is a user message after the complete tool batch.
        clock[0] = 1000.0
        loop._notices = set()
        self.agent.loop.model = ScriptedModel([lambda messages, schemas: (clock.__setitem__(0, 1000 + limit * 0.6),
            tools(call('list_files', 'l')))[1], ModelResponse('Done.')])
        await self.agent.run('Work.')
        roles = [m.role for m in self.agent.state.messages]
        notice = roles.index('user', roles.index('tool'))
        self.assertEqual(roles[notice - 1], 'tool')
        self.assertIn('half of the work time', self.agent.state.messages[notice].content)

    async def test_without_a_time_limit_nothing_stops_or_announces_a_deadline(self):
        from infrastructure.verification.driver import FinalizationDriver, feedback
        agent = self.agent
        unlimited = replace(agent.profile, budget=replace(agent.profile.budget, wall_seconds=0))
        agent.loop.profile = agent.profile = unlimited
        agent.loop.budget.settings = unlimited.budget
        budget = agent.loop.budget
        budget.clock, budget.started = (lambda: 10_000_000.0), 0.0       # Days of work.
        budget.check_time()
        budget.check_time(final=True)
        budget.reserve_request('main')
        self.assertIsNone(agent.loop.time_notice())
        self.assertIsNone(budget.report()['wall_seconds'])
        driver = FinalizationDriver(agent, verifier=None)
        self.assertTrue(driver.can_continue())
        self.assertIsNone(driver.remaining()['seconds'])
        report = {'round': 1, 'clean_state': False, 'stage': 'build', 'status': 'failed', 'failures': [],
            'evidence': 'e', 'stages': [], 'stopped_services': []}
        text = feedback(report, repeated=False, remaining=driver.remaining())
        self.assertNotIn('Remaining budget', text)          # Nothing to announce without limits.
        self.assertNotIn('None', text)
        from infrastructure.verification.driver import budget_line
        self.assertEqual(budget_line({'requests': None, 'seconds': None}), '')
        self.assertEqual(budget_line({'requests': None, 'seconds': 60}), 'Remaining budget: 60 s of work time.')

    def test_the_shipped_profile_bounds_work_time_and_masks_old_observations(self):
        budget, profile = self.agent.profile.budget, self.agent.profile
        from infrastructure.runtime.config import load_profile
        shipped = load_profile(environment={})
        self.assertEqual(shipped.budget.wall_seconds, 0)                  # No time limit (user's choice).
        self.assertEqual((shipped.max_requests, shipped.budget.max_tool_calls, shipped.budget.max_reported_tokens,
            shipped.budget.max_verification_rounds, shipped.acceptance.max_generated_scenarios), (0, 0, 0, 0, 0))
        self.assertGreater(shipped.budget.stagnation_repeats, 0)            # Kept: it does not grow with size.
        self.assertEqual(shipped.observation_window, 10)
        self.assertLessEqual(shipped.max_context_bytes, 240000)
        self.assertIn('call run_acceptance_tests instead of testing journeys by hand', shipped.workflow)
        self.assertTrue(budget and profile)


if __name__ == '__main__':
    unittest.main()


class WarmUpTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependencies_and_test_runner_are_prepared_while_the_model_works(self):
        with TemporaryDirectory() as tmp:
            calls = []

            def first(messages, schemas):
                calls.append(('model', dict(log)['installs'], tooling.ensured))
                return ModelResponse('Done.')
            agent, tooling, log = make_agent(Path(tmp), ScriptedModel([first]), generate=False)
            async with agent:
                await agent.generate(tooling=tooling)
                events = [line for line in agent.store.events() if line['kind'] == 'warm_up']
            # Started before the first answer of the model was used, without waiting for the agent.
            self.assertEqual(events[0]['data']['steps'], {'dependencies': 'reused', 'test_runner': 'ready'})
            self.assertGreaterEqual(log['installs'], 1)
            self.assertGreaterEqual(tooling.ensured, 1)

    async def test_an_installation_racing_a_manifest_edit_is_not_recorded_as_current(self):
        from infrastructure.runtime.dependencies import DependencyManager
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]))
            manager = agent.tools.dependencies
            manager.toolchain = {'node': 'v22', 'npm': '10'}
            workspace = agent.state.workspace

            async def run(command, timeout=None, env=None):
                # The agent adds a dependency while npm is installing.
                (workspace / 'backend/package.json').write_text('{"name": "@arc/backend", "dependencies": {"x": "1"}}')
                return {'status': 'completed', 'returncode': 0, 'content': 'added', 'accepted': False}

            async def check():
                return 'host'
            manager.processes.run, manager.processes.sandbox.check = run, check
            async with agent:
                result = await DependencyManager.install(manager)
            self.assertTrue(result['stale'])
            self.assertFalse(manager.stamp.exists())
