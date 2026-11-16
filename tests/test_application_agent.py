"""Behavioral integration of our loop with real confined file effects."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall, ToolResult
from infrastructure.runtime.model import ProviderError, ScriptedModel


def call(name, arguments, identity='call-1'):
    return ToolCall(identity, name, json.dumps(arguments))


def response(*calls):
    return ModelResponse(tool_calls=calls, finish_reason='tool_calls')


class ApplicationAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / 'app'
        self.workspace.mkdir()
        self.profile = load_profile(environment={})

    def agent(self, model, **limits):
        return ApplicationAgent(self.workspace, profile=replace(self.profile, **limits), model=model)

    async def test_read_edit_verify_and_followup_use_one_session(self):
        path = self.workspace / 'app.ts'
        path.write_text('const value = 1;\nexport { value };\n')
        def verify_observation(messages, tools):
            observation = json.loads(messages[-1].content)
            self.assertIn('value = 2', observation['result']['content'])
            return ModelResponse('File change verified by reading; runtime remains unverified.')
        model = ScriptedModel([
            response(call('read_file', {'path': 'app.ts'})),
            response(call('edit_file', {'path': 'app.ts', 'operation': 'replace',
                'old_content': 'value = 1', 'new_content': 'value = 2'}, 'edit')),
            response(call('read_file', {'path': 'app.ts'}, 'verify')), verify_observation,
            ModelResponse('Previous change retained; awaiting executable checks.')])
        async with self.agent(model) as agent:
            first = await agent.run('Set value to 2 and inspect the saved file.')
            identity = agent.state.id
            second = await agent.run('Do not claim runtime acceptance.')
            self.assertEqual((first.status, second.status), ('proposed', 'proposed'))
            self.assertEqual(agent.state.id, identity)
            self.assertEqual(agent.state.requests, 5)
            self.assertEqual(len([m for m in model.requests[-1][0] if m.role == 'user']), 2)
            self.assertFalse(first.events[-1].data['accepted'])
            self.assertEqual(len([e for e in first.events if e.kind == 'tool_finished']), 3)
            self.assertFalse(model.closed)
        self.assertTrue(model.closed)

    async def test_bad_arguments_and_unknown_tool_are_observations(self):
        model = ScriptedModel([response(ToolCall('bad', 'read_file', '{'),
            call('shell', {}, 'unknown'), call('read_file', {'path': 'x', 'extra': 1}, 'schema')),
            ModelResponse('Correcting my tool calls.')])
        async with self.agent(model) as agent:
            result = await agent.run('Inspect')
            self.assertEqual(result.status, 'proposed')
            errors = [json.loads(m.content) for m in agent.state.messages if m.role == 'tool']
            self.assertEqual(len(errors), 3)
            self.assertTrue(all(not e['ok'] for e in errors))

    async def test_protected_files_and_escape_cannot_be_written(self):
        model = ScriptedModel([response(*(call('edit_file', {'path': p, 'operation': 'create',
            'new_content': 'changed'}, str(i)) for i, p in enumerate([
                '../escape.ts', 'requirements.yaml', 'frontend/tests/acceptance.spec.ts', '.env']))),
            ModelResponse('Writes denied.')])
        async with self.agent(model) as agent:
            await agent.run('Attempt writes')
            self.assertTrue(all(json.loads(m.content)['error'] for m in agent.state.messages if m.role == 'tool'))
        self.assertEqual(list(self.workspace.iterdir()), [])

    async def test_request_budget_survives_followup(self):
        model = ScriptedModel([ModelResponse('First')])
        async with self.agent(model, max_requests=1) as agent:
            await agent.run('First')
            result = await agent.run('Second')
            self.assertEqual(result.status, 'budget_exceeded')
            self.assertEqual(len(model.requests), 1)

    async def test_context_limit_prevents_request(self):
        model = ScriptedModel([])
        async with self.agent(model, max_context_bytes=1) as agent:
            self.assertEqual((await agent.run('Task')).status, 'context_limit')
            self.assertFalse(model.requests)

    async def test_truncation_does_not_execute_even_complete_looking_calls(self):
        model = ScriptedModel([ModelResponse(tool_calls=(call('edit_file',
            {'path': 'bad.ts', 'operation': 'create', 'new_content': 'bad'}),), finish_reason='length')])
        async with self.agent(model) as agent:
            self.assertEqual((await agent.run('Task')).status, 'incomplete')
            self.assertFalse((self.workspace / 'bad.ts').exists())

    async def test_excessive_batch_has_no_partial_effect(self):
        model = ScriptedModel([response(call('edit_file', {'path': 'a.ts', 'operation': 'create',
            'new_content': 'a'}, 'a'), call('read_file', {'path': 'a.ts'}, 'b'))])
        async with self.agent(model, max_tools_per_response=1) as agent:
            self.assertEqual((await agent.run('Task')).status, 'budget_exceeded')
            self.assertFalse((self.workspace / 'a.ts').exists())

    async def test_duplicate_call_ids_rejected_before_edits(self):
        c = call('edit_file', {'path': 'bad.ts', 'operation': 'create', 'new_content': 'bad'})
        async with self.agent(ScriptedModel([response(c, c)])) as agent:
            self.assertEqual((await agent.run('Task')).status, 'provider_error')
            self.assertFalse((self.workspace / 'bad.ts').exists())

    async def test_cancel_pending_batch_balances_transcript_and_preserves_completed_write(self):
        model = ScriptedModel([response(call('edit_file', {'path': 'done.ts', 'operation': 'create',
            'new_content': 'done'}, 'done'), call('edit_file', {'path': 'later.ts',
                'operation': 'create', 'new_content': 'later'}, 'later')), ModelResponse('Resumed')])
        async with self.agent(model) as agent:
            original = agent.tools.execute
            async def execute(c):
                result = await original(c)
                agent.cancel()
                return result
            agent.tools.execute = execute
            task = asyncio.create_task(agent.run('Work'))
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue((self.workspace / 'done.ts').exists())
            self.assertFalse((self.workspace / 'later.ts').exists())
            self.assertEqual([m.tool_call_id for m in agent.state.messages if m.role == 'tool'], ['done', 'later'])
            self.assertEqual((await agent.run('Inspect before resuming')).status, 'proposed')

    async def test_close_cancels_model_and_concurrent_turn_is_rejected(self):
        entered = asyncio.Event()
        class SlowModel(ScriptedModel):
            async def respond(self, messages, tools):
                entered.set()
                await asyncio.Event().wait()
        model = SlowModel([])
        agent = self.agent(model)
        task = asyncio.create_task(agent.run('Wait'))
        await entered.wait()
        with self.assertRaises(RuntimeError):
            await agent.run('Concurrent')
        await agent.aclose()
        self.assertTrue(task.cancelled())
        self.assertTrue(model.closed)
        with self.assertRaises(RuntimeError):
            await agent.run('Closed')

    async def test_two_sessions_have_separate_history_workspace_and_budget(self):
        first = self.agent(ScriptedModel([ModelResponse('One')]))
        other = ApplicationAgent(self.workspace.parent / 'other', profile=self.profile,
            model=ScriptedModel([ModelResponse('Two')]))
        async with first, other:
            await first.run('Private first task')
            await other.run('Second task')
            self.assertNotEqual(first.state.id, other.state.id)
            self.assertNotEqual(first.state.state_directory, other.state.state_directory)
            self.assertNotIn('Private', str(other.state.messages))
            self.assertEqual(other.state.requests, 1)

    def test_message_serialization_preserves_native_call_and_reasoning(self):
        message = Message('assistant', '', (ToolCall('1', 'read_file', '{bad'),), reasoning_content='state')
        self.assertEqual(Message.from_dict(json.loads(json.dumps(message.to_dict()))), message)
        self.assertEqual(message.to_wire()['tool_calls'][0]['function']['arguments'], '{bad')
        result = ToolResult('1', 'read_file', error='invalid JSON')
        self.assertEqual(result.message().to_wire()['tool_call_id'], '1')
