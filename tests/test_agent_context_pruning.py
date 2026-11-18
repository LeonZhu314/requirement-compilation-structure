"""A lighter conversation: obsolete observations, filtered logs, cache accounting."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.messages import Message, ModelResponse, ToolCall, ToolResult, Usage
from infrastructure.runtime.model import ScriptedModel
from infrastructure.verification.results import error_excerpt
from tests.verification_support import call, make_agent, tools


def noisy_log(errors=True):
    lines = [f'vite v9 transforming module {index} of 4000 ...' for index in range(4000)]
    if errors:
        lines[1500] = "src/pages/Login.tsx(12,7): error TS2322: Type 'string' is not assignable to type 'number'."
        lines[2500] = "src/api/client.ts(4,22): error TS2307: Cannot find module './missing'."
        lines.append('Found 2 errors in 2 files.')
    return '\n'.join(lines)


class LogFilterTests(unittest.TestCase):
    def test_a_long_log_is_reduced_to_its_errors_and_summary(self):
        excerpt = error_excerpt(noisy_log(), 2500)
        self.assertLess(len(excerpt), 2600)
        for expected in ('TS2322', 'TS2307', 'Found 2 errors'):
            self.assertIn(expected, excerpt)
        self.assertLess(excerpt.index('TS2322'), excerpt.index('TS2307'))    # First errors first.
        self.assertNotIn('module 10 of', excerpt)
        # Without any recognizable error the end of the log is the best evidence; a short log is untouched.
        self.assertTrue(error_excerpt(noisy_log(errors=False), 500).endswith('module 3999 of 4000 ...'))
        self.assertEqual(error_excerpt('error: one line', 500), 'error: one line')
        repeated = '\n'.join(['filler ' * 20] * 300 + ['npm error code E404'] * 200)
        self.assertEqual(error_excerpt(repeated, 2500).count('npm error code E404'), 1)


class ContextPruningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agent, _, self.log = make_agent(self.root, ScriptedModel([]), prune_min_bytes=3000, observation_window=0)
        self.count = 0

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    async def step(self, tool_name, **args):
        """Run one real tool call and record it in the conversation as the loop would."""
        self.count += 1
        request = ToolCall(f'c{self.count}', tool_name, json.dumps(args))
        result = await self.agent.tools.execute(request)
        self.agent.state.messages += [Message('assistant', tool_calls=(request,)), result.message()]
        return request.id

    def observation(self, identity):
        message = next(m for m in self.agent.state.messages if m.tool_call_id == identity)
        return json.loads(message.content)['result']

    async def test_only_obsolete_observations_are_replaced_and_stay_retrievable(self):
        body = ''.join(f'export const value{index} = "needle {index}";\n' for index in range(120))
        setup = await self.step('write_files', files=[{'path': 'a.ts', 'content': body}, {'path': 'b.ts', 'content': body}])
        first_a, first_b = await self.step('read_file', path='a.ts'), await self.step('read_file', path='b.ts')
        grouped = await self.step('read_files', files=[{'path': 'a.ts', 'start_line': 1, 'end_line': 60},
            {'path': 'b.ts', 'start_line': 61, 'end_line': 120}])
        await self.step('write_file', path='a.ts', content=body.replace('needle', 'changed'))
        second_a, again_b = await self.step('read_file', path='a.ts'), await self.step('read_file', path='b.ts')
        first_search = await self.step('search_text', query='needle')
        second_search = await self.step('search_text', query='needle')
        old_check = ToolCall('old-check', 'verify_application', '{"kind": "build"}')
        self.agent.state.messages += [Message('assistant', tool_calls=(old_check,)), ToolResult('old-check',
            'verify_application', {'kind': 'build', 'status': 'failed', 'output_tail': 'error TS1 ' * 300}).message()]
        new_check = await self.step('verify_application', kind='all')
        original = next(m.content for m in self.agent.state.messages if m.tool_call_id == first_a)
        answered = [m.tool_call_id for m in self.agent.state.messages if m.role == 'tool']

        event = self.agent.loop.context.prune()
        self.assertEqual(event['observations'], 4)
        self.assertGreater(event['saved_bytes'], 3000)
        # Rewritten later, read again later, repeated later, checked again later.
        self.assertIn('rewritten later', self.observation(first_a)['pruned'])
        self.assertIn('rewritten later', self.observation(grouped)['files'][0]['pruned'])
        self.assertIn('same call', self.observation(first_search)['pruned'])
        self.assertIn('run again later', self.observation('old-check')['pruned'])
        # Still current: the only text of b.ts (its later read answered "unchanged"), the other
        # half of the grouped read, the latest read, search and check, and every write.
        self.assertTrue(self.observation(again_b)['unchanged'])
        self.assertIn('content', self.observation(first_b))
        self.assertIn('value100', self.observation(grouped)['files'][1]['content'])
        self.assertIn('changed 1', self.observation(second_a)['content'])
        self.assertEqual(self.observation(second_search)['total'], 120)
        self.assertEqual(self.observation(new_check)['status'], 'passed')
        self.assertEqual(len(self.observation(setup)['files']), 2)
        # Nothing is lost, every call keeps its answer, and a second pass has nothing to do.
        stored = self.agent.tools.artifacts.read(self.observation(first_a)['artifact'], limit=12000)
        self.assertEqual(stored['content'], original[:12000])
        self.assertEqual([m.tool_call_id for m in self.agent.state.messages if m.role == 'tool'], answered)
        self.assertIsNone(self.agent.loop.context.prune())

    async def test_history_is_left_alone_until_a_whole_block_can_be_reclaimed(self):
        await self.step('write_file', path='a.ts', content='const needle = 1;\n' * 30)
        await self.step('search_text', query='needle', limit=20)
        await self.step('search_text', query='needle', limit=20)
        before = list(self.agent.state.messages)
        self.assertIsNone(self.agent.loop.context.prune())                # Below prune_min_bytes: prefix kept intact.
        self.assertEqual(self.agent.state.messages, before)
        self.agent.loop.context.profile = replace(self.agent.profile, prune_min_bytes=0)
        self.assertIsNone(self.agent.loop.context.prune())                # 0 disables.
        self.agent.loop.context.profile = replace(self.agent.profile, prune_min_bytes=300)
        self.assertEqual(self.agent.loop.context.prune()['observations'], 1)

    async def test_page_observations_keep_only_the_latest_ones(self):
        for index in range(4):
            request = ToolCall(f'b{index}', 'browser', '{"action": "snapshot"}')
            self.agent.state.messages += [Message('assistant', tool_calls=(request,)),
                ToolResult(request.id, 'browser', {'dom': f'<main>page {index}</main>' * 150}).message()]
        self.assertEqual(self.agent.loop.context.prune()['observations'], 2)
        self.assertEqual(['pruned' in self.observation(f'b{index}') for index in range(4)], [True, True, False, False])

    async def test_the_loop_prunes_between_requests_and_reports_it(self):
        line = 'const needle = "' + 'x' * 100 + '";\n'
        await self.agent.tools.execute(call('write_file', path='a.ts', content=line * 200))
        self.agent.loop.model = ScriptedModel([tools(call('search_text', 's1', query='needle')),
            tools(call('search_text', 's2', query='needle')), ModelResponse('Done.')])
        result = await self.agent.run('Search twice.')
        self.assertEqual(result.status, 'proposed')
        self.assertEqual([event.kind for event in result.events].count('pruned'), 1)
        report = self.agent.loop.budget.report()['context_pruning']
        self.assertEqual((report['passes'], report['observations']), (1, 1))
        sent = self.agent.loop.model.requests[-1][0]
        self.assertIn('pruned', next(m.content for m in sent if m.tool_call_id == 's1'))
        self.assertNotIn('pruned', next(m.content for m in sent if m.tool_call_id == 's2'))
        # The start of the conversation and the tool schemas are identical for every request.
        first, last = self.agent.loop.model.requests[0], self.agent.loop.model.requests[-1]
        self.assertEqual(first[0][:2], last[0][:2])
        self.assertEqual(first[1], last[1])

    async def test_a_read_after_compaction_returns_text_again(self):
        agent = self.agent
        await agent.tools.execute(call('write_file', path='app.ts', content='export const kept = true;\n'))
        self.assertIn('content', (await agent.tools.execute(call('read_file', path='app.ts'))).value)
        agent.loop.context.profile = replace(agent.profile, max_context_bytes=40000, prune_min_bytes=0)
        for index in range(12):
            request = ToolCall(f'c{index}', 'list_files', json.dumps({'offset': index}))
            agent.state.messages += [Message('assistant', tool_calls=(request,)),
                ToolResult(request.id, request.name, 'x' * 2200).message()]
        self.assertIsNotNone(agent.loop.context.compact())
        self.assertIn('content', (await agent.tools.execute(call('read_file', path='app.ts'))).value)

    async def test_build_and_package_manager_logs_are_filtered_and_other_output_is_not(self):
        registry, outputs = self.agent.tools, {}

        async def run(command, timeout=None, env=None):
            text, code = outputs[command[0]]
            return {'status': 'completed' if code == 0 else 'failed', 'returncode': code,
                'artifact': registry.artifacts.put(text), 'content': text[:12000], 'offset': 0,
                'next_offset': 12000 if len(text) > 12000 else None, 'accepted': False}
        registry.processes.run = run
        outputs['npm'] = (noisy_log(errors=False), 0)
        passed = (await registry.execute(call('run_command', command=['npm', 'run', 'build']))).value
        self.assertLessEqual(len(passed['content']), 1000)
        self.assertTrue(passed['content'].endswith('module 3999 of 4000 ...'))
        self.assertEqual(passed['total_chars'], len(noisy_log(errors=False)))
        self.assertEqual(registry.artifacts.read(passed['artifact'], limit=20)['content'], noisy_log(errors=False)[:20])
        outputs['sh'] = (noisy_log(), 2)
        failed = (await registry.execute(call('run_command', command=['sh', '-c', 'cd frontend && npx tsc -b']))).value
        self.assertIn('TS2307', failed['content'])
        self.assertLess(len(failed['content']), 4100)
        # A command whose output is the answer is not a log: it is returned as before.
        outputs['cat'] = (noisy_log(errors=False), 0)
        listed = (await registry.execute(call('run_command', command=['cat', 'big.txt']))).value
        self.assertIn('preview', listed)                                   # Bounded as any long observation.
        self.assertTrue(json.loads(listed['preview'][:200].split(', "content"')[0] + '}')['returncode'] == 0)

    def test_the_report_shows_how_much_input_came_from_the_provider_cache(self):
        budget = self.agent.loop.budget
        budget.record_usage(Usage(1000, 50, cached_input_tokens=800))
        budget.record_usage(Usage(1000, 50, cached_input_tokens=None))
        tokens = budget.report()['reported_tokens']
        self.assertEqual((tokens['input'], tokens['output'], tokens['cached_input'], tokens['cached_input_ratio'],
            tokens['total']), (2000, 100, 800, 0.4, 2100))


if __name__ == '__main__':
    unittest.main()
