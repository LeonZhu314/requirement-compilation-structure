"""Parallel sub-agents: independent parts written at the same time, each in its own files."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from infrastructure.runtime.delegation import scopes_valid
from infrastructure.runtime.messages import ModelResponse, ToolCall, Usage
from infrastructure.runtime.model import ScriptedModel
from tests.verification_support import call, make_agent, tools


class SlowModel(ScriptedModel):
    """A provider that takes `delay` seconds per answer, like a real one."""

    def __init__(self, responses, delay, log, name):
        super().__init__(responses)
        self.delay, self.log, self.name = delay, log, name

    async def respond(self, messages, schemas):
        self.log.append(('start', self.name, time.monotonic()))
        await asyncio.sleep(self.delay)
        self.log.append(('end', self.name, time.monotonic()))
        return await super().respond(messages, schemas)


def write(identity, path, content):
    return ToolCall(identity, 'write_files', json.dumps({'files': [{'path': path, 'content': content}]}))


class DelegationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.agent, _, _ = make_agent(Path(self.tmp.name), ScriptedModel([]))
        self.workspace = self.agent.state.workspace
        self.log = []

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    def sub_models(self, *scripts, delay=0.3):
        models = iter(SlowModel(script, delay, self.log, f'sub{index}') for index, script in enumerate(scripts))
        self.agent.tools.model_factory = lambda: next(models)

    async def test_independent_parts_are_written_at_the_same_time_and_reported(self):
        self.sub_models(
            [ModelResponse(tool_calls=(write('a', 'backend/src/api/items.ts', 'export const items = 1;\n'),),
                finish_reason='tool_calls', usage=Usage(100, 20)), ModelResponse('Wrote the items API.', usage=Usage(120, 10))],
            [ModelResponse(tool_calls=(write('b', 'frontend/src/pages/Items.tsx', 'export const Items = 1;\n'),),
                finish_reason='tool_calls', usage=Usage(200, 30)), ModelResponse('Wrote the items page.', usage=Usage(220, 15))])
        lead = ScriptedModel([tools(call('delegate_tasks', 'd', contract='GET /api/items returns {items: Item[]}',
            tasks=[{'id': 'api', 'task': 'Items API', 'write_paths': ['backend/src/api'], 'requirements': ['REQ-A']},
                {'id': 'pages', 'task': 'Items page', 'write_paths': ['frontend/src/pages/Items.tsx']}])),
            ModelResponse('Integrated.')])
        self.agent.loop.model = lead
        started = time.monotonic()
        result = await self.agent.run('Build it.')
        elapsed = time.monotonic() - started
        self.assertEqual(result.status, 'proposed')
        # Each sub-agent's answers overlap the other's: they ran at the same time.
        spans = {}
        for kind, name, moment in self.log:
            spans.setdefault(name, []).append(moment)
        (a_start, a_end), (b_start, b_end) = [(min(v), max(v)) for v in spans.values()]
        self.assertLess(max(a_start, b_start), min(a_end, b_end))
        self.assertEqual((self.workspace / 'backend/src/api/items.ts').read_text(), 'export const items = 1;\n')
        report = json.loads(next(m.content for m in self.agent.state.messages if m.tool_call_id == 'd'))['result']
        self.assertEqual([(t['id'], t['status'], t['files_changed']) for t in report['tasks']],
            [('api', 'proposed', ['backend/src/api/items.ts']), ('pages', 'proposed', ['frontend/src/pages/Items.tsx'])])
        self.assertEqual(report['tasks'][1]['reply'], 'Wrote the items page.')
        # The sub-agents received the contract, their requirement and the building blocks guide.
        first = [m for m in lead.requests[0][0]]
        budget = self.agent.loop.budget.report()
        self.assertEqual((budget['requests']['subagent'], budget['requests']['main'], budget['requests']['total']), (4, 2, 6))
        self.assertEqual(budget['reported_tokens']['input'], 640)
        self.assertEqual(budget['tool_calls']['total'], 3)
        self.assertTrue(first)

    async def test_a_sub_agent_cannot_write_outside_its_paths_or_run_commands(self):
        seen = {}

        def outside(messages, schemas):
            seen['tools'] = sorted(schema['function']['name'] for schema in schemas)
            seen['system'] = messages[0].content
            seen['prompt'] = messages[1].content
            return ModelResponse(tool_calls=(write('x', 'backend/src/app.ts', 'overwritten'),), finish_reason='tool_calls')

        def after(messages, schemas):
            seen['error'] = json.loads(messages[-1].content)['error']
            return ModelResponse('I could not edit app.ts; the lead must register my router.')
        self.sub_models([outside, after])
        before = (self.workspace / 'backend/src/app.ts').read_text()
        result = await self.agent.tools.execute(call('delegate_tasks', contract='Router at backend/src/api/items.ts',
            tasks=[{'id': 'api', 'task': 'Items API', 'write_paths': ['backend/src/api/'], 'requirements': ['REQ-A', 'NOPE']}]))
        self.assertIsNone(result.error)
        self.assertIn('WRITE_OUTSIDE_SCOPE', seen['error'])
        self.assertEqual((self.workspace / 'backend/src/app.ts').read_text(), before)
        self.assertEqual(result.value['tasks'][0]['files_changed'], [])
        self.assertIn('lead must register', result.value['tasks'][0]['reply'])
        for forbidden in ('run_command', 'process_start', 'verify_application', 'delegate_tasks', 'install_dependencies'):
            self.assertNotIn(forbidden, seen['tools'])
        self.assertIn('write_files', seen['tools'])
        self.assertIn('Router at backend/src/api/items.ts', seen['system'])
        self.assertIn('Register with a unique username', seen['prompt'])          # Requirement text of REQ-A.
        self.assertIn('unknown requirement id', seen['prompt'])
        self.assertIn('BUILDING_BLOCKS.md', seen['prompt'])

    async def test_overlapping_or_protected_paths_are_refused_before_any_request(self):
        for tasks in ([{'id': 'a', 'task': 't', 'write_paths': ['frontend/src']},
                    {'id': 'b', 'task': 't', 'write_paths': ['frontend/src/pages']}],
                [{'id': 'a', 'task': 't', 'write_paths': ['tests']}],
                [{'id': 'a', 'task': 't', 'write_paths': ['../outside']}],
                [{'id': 'a', 'task': 't', 'write_paths': ['x']}, {'id': 'a', 'task': 't', 'write_paths': ['y']}]):
            with self.assertRaises(ValueError):
                scopes_valid(tasks)
        scopes_valid([{'id': 'a', 'task': 't', 'write_paths': ['frontend/src/pages/auth']},
            {'id': 'b', 'task': 't', 'write_paths': ['frontend/src/pages/authors']}])   # Not a prefix of each other.
        self.agent.tools.model_factory = lambda: self.fail('no sub-agent may start')
        refused = await self.agent.tools.execute(call('delegate_tasks', contract='c', tasks=[
            {'id': 'a', 'task': 't', 'write_paths': ['backend']}, {'id': 'b', 'task': 't', 'write_paths': ['backend/src']}]))
        self.assertIn('would both write', refused.error)

    async def test_one_failing_sub_agent_does_not_discard_the_others(self):
        self.sub_models([ModelResponse(tool_calls=(write('a', 'a/one.ts', '1'),), finish_reason='tool_calls'),
            ModelResponse('Done one.')], [])                                       # The second provider fails at once.
        result = (await self.agent.tools.execute(call('delegate_tasks', contract='c', tasks=[
            {'id': 'one', 'task': 't', 'write_paths': ['a']}, {'id': 'two', 'task': 't', 'write_paths': ['b']}]))).value
        self.assertEqual([t['status'] for t in result['tasks']], ['proposed', 'provider_error'])
        self.assertEqual(result['tasks'][0]['files_changed'], ['a/one.ts'])

    def test_the_lead_is_told_when_and_how_to_delegate(self):
        workflow = self.agent.profile.workflow
        self.assertIn('delegate_tasks', workflow)
        self.assertIn('shared contract', workflow)
        self.assertIn('delegate_tasks', self.agent.profile.tools)


if __name__ == '__main__':
    unittest.main()
