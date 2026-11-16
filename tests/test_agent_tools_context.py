from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.context import size
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall, ToolResult
from infrastructure.runtime.model import ScriptedModel


class ToolsAndContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.agent = ApplicationAgent(self.root / 'app', model=ScriptedModel([]), profile=load_profile(environment={}))

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.temp.cleanup()

    async def tool(self, name, **args):
        return await self.agent.tools.execute(ToolCall('call', name, json.dumps(args)))

    async def test_search_patch_across_layers_rewrite_and_invalid_batch_permissions(self):
        for path in ('backend/src/api/register.ts', 'backend/src/db/tables/note.sql', 'frontend/src/App.tsx'):
            self.assertIsNone((await self.tool('write_file', path=path, content='old behavior\n')).error)
        matches = (await self.tool('search_text', query='old behavior', limit=1)).value
        self.assertEqual(matches['total'], 3)
        self.assertEqual(matches['next_offset'], 1)
        changes = [{'path': path, 'old_content': 'old behavior', 'new_content': 'new behavior'}
            for path in ('backend/src/api/register.ts', 'frontend/src/App.tsx')]
        self.assertIsNone((await self.tool('apply_patch', changes=changes)).error)
        rejected = await self.tool('apply_patch', changes=[
            {'path': 'frontend/src/App.tsx', 'old_content': 'new behavior', 'new_content': 'bad'},
            {'path': 'tests/external.py', 'old_content': 'assert false', 'new_content': 'assert true'}])
        self.assertIsNotNone(rejected.error)
        self.assertEqual((self.agent.state.workspace / 'frontend/src/App.tsx').read_text(), 'new behavior\n')
        digest = sha256(b'new behavior\n').hexdigest()
        self.assertIsNone((await self.tool('write_file', path='frontend/src/App.tsx', content='rewritten\n', expected_sha256=digest)).error)
        self.assertIsNotNone((await self.tool('write_file', path='frontend/src/App.tsx', content='stale', expected_sha256=digest)).error)

    async def test_reads_are_paged_cached_and_invalidated_after_edits(self):
        await self.tool('write_file', path='source.ts', content=''.join(f'line {i}\n' for i in range(300)))
        first = (await self.tool('read_file', path='source.ts')).value
        second = (await self.tool('read_file', path='source.ts')).value
        self.assertEqual(first['end_line'], 200)
        self.assertTrue(second['unchanged'])
        self.assertNotIn('content', second)
        exact = (await self.tool('read_artifact', identity=second['artifact'])).value
        self.assertEqual(exact['content'], first['content'])
        await self.tool('edit_file', path='source.ts', operation='replace', old_content='line 0\n', new_content='updated\n')
        self.assertFalse((await self.tool('read_file', path='source.ts')).value['unchanged'])
        for args in ({'path': 'source.ts', 'start_line': True}, {'path': 'source.ts', 'start_line': 4, 'end_line': 2},
                {'path': 'source.ts', 'unknown': 3}):
            self.assertIsNotNone((await self.tool('read_file', **args)).error)

    async def test_large_observations_can_be_recovered_exactly(self):
        value = {'content': 'x' * 20000}
        bounded = self.agent.tools.artifacts.bound(value, 1000)
        first = self.agent.tools.artifacts.read(bounded['artifact'], limit=12000)
        second = self.agent.tools.artifacts.read(bounded['artifact'], offset=12000)
        self.assertEqual(json.loads(first['content'] + second['content']), value)

    async def test_compaction_preserves_user_order_pairs_notes_and_previous_archive_chain(self):
        agent = self.agent
        agent.loop.profile = replace(agent.profile, max_context_bytes=34000)
        agent.loop.context.profile = agent.loop.profile
        agent.state.todos = [{'id': 't', 'task': 'Fix ownership', 'status': 'in_progress', 'requirements': []}]
        agent.state.notes['contracts'] = ['GET /notes returns only the signed-in user notes']
        for index in range(12):
            if index in (0, 5):
                agent.state.messages.append(Message('user', f'User correction {index}'))
            call = ToolCall(f'c{index}', 'read_file', '{"path":"app.ts"}')
            agent.state.messages += [Message('assistant', tool_calls=(call,)), ToolResult(call.id, call.name, 'x' * 2200).message()]
        old_size = size(agent.state.messages)
        event = agent.loop.context.compact()
        self.assertIsNotNone(event)
        self.assertLess(size(agent.state.messages), old_size)
        self.assertEqual(event['summary_requests'], 0)
        self.assertEqual([m.content for m in agent.state.messages if m.role == 'user'], ['User correction 0', 'User correction 5'])
        self.assertIn('Fix ownership', agent.loop.context.memory.content)
        self.assertIn('signed-in user', agent.loop.context.memory.content)
        calls = [call.id for m in agent.state.messages for call in m.tool_calls]
        self.assertEqual(calls, [m.tool_call_id for m in agent.state.messages if m.role == 'tool'])
        self.assertIn('c11', calls)
        archive = agent.tools.artifacts.path(event['archive']).read_text()
        self.assertIn('c0', archive)
        self.assertIn('User correction 5', archive)

    async def test_native_images_are_appended_after_all_tool_results(self):
        from PIL import Image
        from io import BytesIO
        output = BytesIO()
        Image.new('RGB', (5, 5)).save(output, 'PNG')
        identity = self.agent.tools.artifacts.put(output.getvalue(), '.png')
        profile = replace(self.agent.profile, image_mode='native')
        self.agent.tools.profile = profile
        self.agent.loop.model = ScriptedModel([ModelResponse(tool_calls=(
            ToolCall('image', 'view_image', json.dumps({'identity': identity})),
            ToolCall('list', 'list_files', '{}')), finish_reason='tool_calls'), ModelResponse('Observed')])
        await self.agent.run('Inspect')
        messages = self.agent.loop.model.requests[-1][0]
        self.assertEqual([m.role for m in messages[-4:]], ['assistant', 'tool', 'tool', 'user'])
        self.assertTrue(messages[-1].images)
