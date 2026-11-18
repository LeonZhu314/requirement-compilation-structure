"""Large requirement files: kept in the task while they fit, read by section otherwise,
and an agent that only reads is told to write."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.context import ContextWindow, size
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.requirements import RequirementCatalog
from tests.verification_support import call, make_agent, tools, write_input


class RequirementReadingTests(unittest.TestCase):
    def test_an_ancestor_already_held_is_named_not_repeated(self):
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False))
            shown = set()
            first = catalog.read('REQ-A', shown=shown)
            self.assertIn('description', first['ancestor_requirements'][0])
            second = catalog.read('REQ-B', shown=shown)
            self.assertEqual(second['ancestor_requirements'], [{'id': 'ROOT', 'name': 'Accounts', 'already_shown': True}])
            self.assertIn('description', second['requirement'])
            shown.clear()  # What compaction does: the text left the conversation.
            self.assertIn('description', catalog.read('REQ-B', shown=shown)['ancestor_requirements'][0])
            # A host read keeps the full chain.
            self.assertIn('description', catalog.read('REQ-B', record=False)['ancestor_requirements'][0])

    def test_a_section_is_read_in_one_call(self):
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False))
            shown = set()
            section = catalog.read('ROOT', shown=shown, descendants=True)
            self.assertEqual([node['id'] for node in section['descendant_requirements']], ['REQ-A', 'REQ-B'])
            self.assertEqual(shown, {'ROOT', 'REQ-A', 'REQ-B'})
            self.assertTrue({'REQ-A', 'REQ-B'} <= catalog.consulted)

    def test_the_whole_file_stays_in_the_task_while_it_fits(self):
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False))
            whole = catalog.initial_context(max_chars=len(catalog.source))
            self.assertTrue(catalog.inline)
            self.assertIn('original_yaml', whole)
            self.assertIn('do not fetch them again', whole['notice'])
            listed = catalog.initial_context(max_chars=len(catalog.source) - 1)
            self.assertFalse(catalog.inline)
            self.assertIn('catalog', listed)
            self.assertIn('one top-level section at a time', listed['notice'])


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_requirements_are_not_sent_again_and_the_window_sits_on_top_of_the_task(self):
        with TemporaryDirectory() as tmp:
            model = ScriptedModel([tools(ToolCall('c', 'read_requirement', json.dumps({'identity': 'REQ-A'}))), ModelResponse('Done.')])
            agent, _, _ = make_agent(Path(tmp), model, generate=False)
            async with agent:
                await agent.run()
                self.assertTrue(agent.tools.requirements_inline)
                answer = json.loads(next(m for m in agent.state.messages if m.role == 'tool').content)['result']
                self.assertEqual(answer['ancestor_requirements'][0]['already_shown'], True)
                self.assertIn('already in your first message', answer['notice'])
                task = next(m for m in agent.state.messages if m.role == 'user')
                window = ContextWindow(agent.state, agent.tools, replace(agent.profile, max_context_bytes=100000,
                    context_ceiling_bytes=100000 + size([task]) + 5000))
                self.assertEqual(window.limit(), 100000 + size([task]))
                window.profile = replace(window.profile, context_ceiling_bytes=100500)
                self.assertEqual(window.limit(), 100500)                    # Never above what the model accepts.
                window.profile = replace(window.profile, context_ceiling_bytes=0)
                self.assertEqual(window.limit(), 100000)

    async def test_compaction_forgets_which_requirements_were_shown(self):
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                agent.tools.requirements_shown.update({'ROOT', 'REQ-A'})
                agent.state.messages[:] = [Message('system', 's'), Message('user', 'task')]
                for index in range(6):
                    request = tools(call('list_files', identity=f'c{index}', path=f'd{index}')).message()
                    agent.state.messages += [request, Message('tool', json.dumps({'ok': True, 'result': 'x' * 4000,
                        'error': None}), tool_call_id=f'c{index}')]
                agent.loop.context.profile = replace(agent.profile, max_context_bytes=34000, prune_min_bytes=0,
                    context_ceiling_bytes=0)
                self.assertIsNotNone(agent.loop.context.compact())
                self.assertEqual(agent.tools.requirements_shown, set())
                memory = next(m for m in agent.state.messages if m.content.startswith('Working memory'))
                self.assertIn('Do not read them all again', memory.content)

    async def test_twelve_steps_without_writing_earn_one_notice(self):
        with TemporaryDirectory() as tmp:
            steps = [tools(call('requirement_catalog', identity=f'c{index}', offset=index, limit=1)) for index in range(13)]
            model = ScriptedModel([*steps[:12], tools(call('write_file', identity='w', path='notes.txt', content='x')),
                steps[12], ModelResponse('Done.')])
            agent, _, _ = make_agent(Path(tmp), model, generate=False)
            async with agent:
                await agent.run()
                answers = [json.loads(m.content) for m in agent.state.messages if m.role == 'tool']
                noticed = [index for index, answer in enumerate(answers)
                    if isinstance(answer['result'], dict) and 'host_notice' in answer['result']]
                self.assertEqual(noticed, [11])                             # Once, on the twelfth step.
                self.assertTrue(answers[11]['ok'])
                self.assertIn('12 steps in a row without writing', answers[11]['result']['host_notice'])
                self.assertEqual(agent.loop.looking, 1)                     # The write reset the count.


class EndlessRoundTests(unittest.IsolatedAsyncioTestCase):
    def test_a_title_built_at_run_time_is_refused(self):
        from infrastructure.verification.acceptance import changing_title
        constant = "test('SCN-A-1: creates a book', async ({ page }) => { await page.goto('/'); });"
        self.assertIsNone(changing_title(constant))
        self.assertIn('constant string literal', changing_title(
            "test(`SCN-A-1: creates book ${Date.now()}`, async ({ page }) => { await page.goto('/'); });"))
        self.assertIn('constant string literal', changing_title(
            "test('SCN-A-1: creates ' + name, async ({ page }) => { await page.goto('/'); });"))

    async def test_the_same_failure_five_times_in_a_row_ends_the_work_turn(self):
        with TemporaryDirectory() as tmp:
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                from infrastructure.verification.verifier import HostVerifier
                agent.verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                agent.tools.acceptance_runner = agent.acceptance_now

                async def verify(*, clean_state, visual=False):
                    return {'status': 'failed', 'stage': 'acceptance', 'fingerprint': 'same', 'round': 1, 'coverage': {},
                        'clean_state': False, 'evidence': 'e.json', 'stages': [], 'stopped_services': [],
                        'failures': [{'stage': 'acceptance', 'key': 'a.spec.ts \u203a SCN-A-1: x', 'title': 'SCN-A-1: x',
                            'covers': ['SCN-A-1'], 'origin': 'generated', 'status': 'failed', 'errors': ['boom']}]}
                agent.verifier.verify = verify
                for expected in (False, False, False, False, True):
                    outcome = await agent.tools.execute(call('run_acceptance_tests'))
                    self.assertIsNone(outcome.error)
                    answer = outcome.value
                    self.assertEqual(agent.tools.finish_requested, expected)
                self.assertIn('delivers the application as it is', answer['report'])
                self.assertIn('5 times in a row', agent.tools.finish_note)

    async def test_an_unchanged_source_is_not_verified_again_and_the_first_round_is_clean(self):
        with TemporaryDirectory() as tmp:
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                from infrastructure.verification.verifier import HostVerifier
                verifier = agent.verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget,
                    agent.loop.model, agent.input_dir, tooling=tooling)
                agent.tools.acceptance_runner = agent.acceptance_now
                calls = []

                async def verify(*, clean_state, visual=None):
                    calls.append((clean_state, visual))
                    report = {'status': 'failed', 'stage': 'acceptance', 'fingerprint': 'same', 'round': len(calls),
                        'coverage': {}, 'clean_state': clean_state, 'evidence': 'e.json', 'stages': [],
                        'stopped_services': [], 'source_revision': agent.tools.processes.mirror.revision(),
                        'failures': [{'stage': 'acceptance', 'key': 'a.spec.ts › SCN-A-1: x', 'title': 'SCN-A-1: x',
                            'covers': ['SCN-A-1'], 'origin': 'generated', 'status': 'failed', 'errors': ['boom']}]}
                    verifier.reports.append(report)
                    verifier.last_report = report
                    return report
                verifier.verify = verify
                first = (await agent.tools.execute(call('run_acceptance_tests'))).value
                second = (await agent.tools.execute(call('run_acceptance_tests'))).value
                self.assertEqual(calls, [(True, False)])            # Deployed like the benchmark, no visual review.
                self.assertNotIn('did not run the tests again', first['report'])
                self.assertIn('did not run the tests again', second['report'])
                (agent.state.workspace / 'backend' / 'changed.ts').write_text('export {};')
                await agent.tools.execute(call('run_acceptance_tests'))
                self.assertEqual(calls, [(True, False), (False, False)])

    async def test_the_driver_gives_the_last_report_again_instead_of_verifying_unchanged_sources(self):
        with TemporaryDirectory() as tmp:
            from infrastructure.verification.driver import FinalizationDriver
            from infrastructure.verification.verifier import HostVerifier
            model = ScriptedModel([ModelResponse('Done.'), ModelResponse('Still done.')])
            agent, tooling, _ = make_agent(Path(tmp), model, generate=False)
            async with agent:
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                verified = []

                async def verify(*, clean_state, visual=None):
                    verified.append(clean_state)
                    raise AssertionError('an unchanged failing revision must not be verified again')
                verifier.verify = verify
                verifier.last_report = {'status': 'failed', 'stage': 'acceptance', 'fingerprint': 'f', 'round': 1,
                    'clean_state': False, 'evidence': 'e.json', 'stages': [], 'stopped_services': [],
                    'source_revision': agent.tools.processes.mirror.revision(), 'accepted': False,
                    'failures': [{'stage': 'acceptance', 'title': 'SCN-A-1: x', 'covers': ['SCN-A-1'], 'errors': ['boom']}]}
                verifier.reports.append(verifier.last_report)
                outcome = await FinalizationDriver(agent, verifier).run()
                self.assertEqual(verified, [])
                self.assertEqual(outcome.cause, 'stagnation: no source change after feedback')
                # The agent got the failures once more as feedback before the stop.
                self.assertTrue(any('Host verification round 1' in m.content for m in agent.state.messages if m.role == 'user'))


if __name__ == '__main__':
    unittest.main()
