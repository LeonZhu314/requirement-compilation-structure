"""Fewer model round trips: grouped file tools, concurrent read-only calls, fused checks."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.messages import ModelResponse, ToolCall
from infrastructure.runtime.model import ScriptedModel
from tests.verification_support import call, make_agent, tools


class BatchingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agent, _, self.log = make_agent(self.root, ScriptedModel([]))
        self.workspace = self.agent.state.workspace

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    async def tool(self, tool_name, **args):
        return await self.agent.tools.execute(ToolCall('c', tool_name, json.dumps(args)))

    async def test_grouped_writes_are_all_or_nothing_and_grouped_reads_keep_every_file(self):
        written = await self.tool('write_files', files=[{'path': 'backend/src/a.ts', 'content': 'export const a = 1;\n'},
            {'path': 'frontend/src/b.tsx', 'content': 'x' * 30000 + '\n'}, {'path': 'c.sql', 'content': 'CREATE TABLE c(id);\n'}])
        self.assertEqual([item['path'] for item in written.value['files']], ['backend/src/a.ts', 'frontend/src/b.tsx', 'c.sql'])
        self.assertEqual((self.workspace / 'c.sql').read_text(), 'CREATE TABLE c(id);\n')
        # One forbidden or duplicated path rejects the whole call before any effect.
        for files in ([{'path': 'd.ts', 'content': 'd'}, {'path': 'tests/external.spec.ts', 'content': 'changed'}],
                [{'path': 'd.ts', 'content': '1'}, {'path': 'D.ts', 'content': '2'}], []):
            self.assertIsNotNone((await self.tool('write_files', files=files)).error)
        self.assertFalse((self.workspace / 'd.ts').exists())

        read = (await self.tool('read_files', files=[{'path': 'frontend/src/b.tsx'}, {'path': 'missing.ts'},
            {'path': 'backend/src/a.ts', 'start_line': 1, 'end_line': 1}, {'path': 'c.sql', 'start_line': 3, 'end_line': 2}])).value
        long, missing, short, invalid = read['files']
        # The long file is truncated on its own; the others stay complete.
        self.assertIn('artifact', long)
        self.assertNotIn('content', long)
        self.assertIn('error', missing)
        self.assertEqual(short['content'], 'export const a = 1;\n')
        self.assertIn('end_line precedes', invalid['error'])
        again = (await self.tool('read_files', files=[{'path': 'backend/src/a.ts', 'start_line': 1, 'end_line': 1}])).value
        self.assertTrue(again['files'][0]['unchanged'])

    async def test_read_only_calls_of_a_response_overlap_and_effects_keep_their_order(self):
        registry, order, active, peak = self.agent.tools, [], 0, 0

        async def query(sql, database='backend/data/app.db', limit=50):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            order.append('start ' + sql)
            await asyncio.sleep(0.05)
            active -= 1
            order.append('end ' + sql)
            return {'rows': [sql], 'accepted': False}
        registry.checks.database_query = query
        self.agent.loop.model = ScriptedModel([tools(
            call('database_query', 'q1', sql='one'), call('database_query', 'q2', sql='two'),
            call('read_files', 'r', files=[{'path': 'README.md'}]),
            call('write_file', 'w', path='note.txt', content='written\n'),
            call('database_query', 'q3', sql='three')), ModelResponse('Done.')])
        result = await self.agent.run('Inspect, then write.')
        self.assertEqual(result.status, 'proposed')
        self.assertEqual(peak, 2)                                     # q1 and q2 overlapped; q3 waited for the write.
        self.assertEqual(order[:2], ['start one', 'start two'])
        self.assertTrue((self.workspace / 'note.txt').is_file())
        self.assertEqual(order[-2:], ['start three', 'end three'])
        # The transcript answers the calls in the order the model gave them.
        answered = [m.tool_call_id for m in self.agent.state.messages if m.role == 'tool']
        self.assertEqual(answered, ['q1', 'q2', 'r', 'w', 'q3'])
        self.assertEqual(self.agent.loop.budget.report()['tool_calls']['total'], 5)
        self.assertEqual(self.agent.state.requests, 2)

    async def test_only_calls_without_effect_are_concurrent(self):
        concurrent = self.agent.tools.concurrent
        self.assertTrue(concurrent(call('http_request', port=3000, path='/api/items')))
        self.assertFalse(concurrent(call('http_request', port=3000, path='/api/items', method='POST')))
        for name in ('write_files', 'apply_patch', 'run_command', 'process_start', 'browser', 'verify_application',
                'todo_write', 'find_symbol'):                        # find_symbol is not enabled in this profile.
            self.assertFalse(concurrent(ToolCall('c', name, '{}')), name)
        for name in ('read_file', 'search_text', 'read_requirement', 'process_logs'):
            self.assertTrue(concurrent(ToolCall('c', name, '{}')), name)

    async def test_one_call_installs_and_runs_every_check_until_the_first_failure(self):
        result = (await self.tool('verify_application', kind='all')).value
        self.assertEqual((result['status'], [c['kind'] for c in result['checks']], result['not_run']),
            ('passed', ['typecheck', 'build', 'backend_tests'], []))
        self.assertEqual((self.log['installs'], result['dependencies'], result['accepted']), (1, 'reused', False))
        await self.tool('write_file', path='BUILD_BROKEN', content='x')
        broken = (await self.tool('verify_application', kind='all')).value
        self.assertEqual((broken['status'], broken['not_run']), ('failed', ['backend_tests']))
        self.assertIn('TS2322', broken['checks'][-1]['output_tail'])

        async def failing_install():
            return {'status': 'installation_failed', 'diagnostic': {'content': 'npm ERR! ETARGET'}}
        self.agent.tools.dependencies.install = failing_install
        commands = len(self.log['commands'])
        unavailable = (await self.tool('verify_application', kind='build')).value
        self.assertEqual(unavailable['status'], 'environment_error')
        self.assertEqual(len(self.log['commands']), commands)         # Nothing was checked.

    async def test_a_service_start_returns_its_first_response(self):
        async def respond(port, path='/', method='GET', body=None, headers=None):
            return {'status': 200, 'headers': {}, 'body': 'x' * 9000, 'accepted': False, 'seen': [port, path]}
        self.agent.tools.checks.http_request = respond
        started = (await self.tool('process_start', name='api', command=['npm', 'start'], ports=[3000],
            probe_path='/api/health')).value
        self.assertEqual((started['ready'], started['probe']['status'], started['probe']['seen']), (True, 200, [3000, '/api/health']))
        self.assertEqual(len(started['probe']['body']), 4000)
        self.assertIsNotNone((await self.tool('process_start', name='job', command=['node', 'x.js'], probe_path='/')).error)
        await self.tool('write_file', path='START_BROKEN', content='x')
        silent = (await self.tool('process_start', name='api2', command=['npm', 'start'], ports=[5173], probe_path='/')).value
        self.assertNotIn('probe', silent)

    async def test_the_instructions_and_schemas_ask_for_grouped_work(self):
        system = self.agent.state.messages[0].content if self.agent.state.messages else ''
        names = [schema['function']['name'] for schema in self.agent.tools.schemas()]
        self.assertTrue({'read_files', 'write_files'} <= set(names))
        self.assertIn('all independent tool calls', system)


if __name__ == '__main__':
    unittest.main()
