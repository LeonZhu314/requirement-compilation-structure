"""v1.18, from the local Stack Overflow runs: generated tests see the requirements their steps
rely on and the page they failed on; a wrong test can be set aside or disputed; a repair loop
that adds no passing test stops; the agent's old reasoning no longer fills the context."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.context import ContextWindow, REASONING_WINDOW, size
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.requirements import RequirementCatalog
from infrastructure.verification.acceptance import alerts, failure_pages, weakened
from infrastructure.verification.coverage import DISPUTED, CoverageRegistry
from infrastructure.verification.driver import feedback, rounds_without_progress
from tests.verification_support import call, make_agent, write_input

LINKED = {'id': 'ROOT', 'name': 'Forum', 'description': 'A forum.', 'children': [
    {'id': 'REQ-1', 'name': 'Sign in', 'description': 'Clicking "Log in"(role=button) opens the form.'},
    {'id': 'REQ-2', 'name': 'Publish', 'description': 'Enter "Body"(role=textbox) with at least 220 characters.'},
    {'id': 'REQ-3', 'name': 'Comment', 'description': 'Comment on a question.', 'dependencies': ['REQ-1'],
        'scenarios': [{'id': 'SCN-3-1', 'steps': [{'id': 'ST-3-1', 'Given': 'A question exists',
            'When': 'Add a comment', 'Then': 'It is shown', 'references': ['\\ref[requirement](REQ-2)']}]}]}]}

ERROR_CONTEXT = '''# Instructions

- Following Playwright test failed.

# Test info

- Name: generated\\abc.spec.ts >> SCN-3-1: comment
- Location: generated\\abc.spec.ts:5:5

# Error details

```
Error: expect(locator).toBeVisible() failed
```

```yaml
- banner:
  - button "Log out"
- main:
  - textbox "Body": too short
  - alert:
    - paragraph: Body is required (minimum 220 characters)
  - button "Post"
```

# Test source

```ts
import { test } from '@playwright/test';
const SECRET = 'test source';
```
'''


class OracleTests(unittest.TestCase):
    def test_referenced_requirements_come_from_dependencies_and_step_references(self):
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False, requirements=LINKED))
            self.assertEqual(catalog.referenced('REQ-3', ['SCN-3-1']), ['REQ-1', 'REQ-2'])
            context = catalog.referenced_context('REQ-3', ['SCN-3-1'])
            self.assertIn('at least 220 characters', context[1]['description'])
            self.assertEqual(context[0]['required_locators'], ["getByRole('button', { name: 'Log in', exact: true })"])
            self.assertEqual(catalog.referenced('ROOT'), [])                # Its own chain is not "referenced".

    def test_parts_of_a_page_named_by_the_scenarios_are_listed_but_fields_are_not(self):
        requirements = {**LINKED, 'children': [*LINKED['children'], {'id': 'REQ-4', 'name': 'Feed',
            'description': 'Follow Questions in Main navigation. Click Ask Question in Question feed. '
                'Fill Page title with a name, then check the value in Page title.'}]}
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False, requirements=requirements))
            context = catalog.initial_context(max_chars=10 ** 6)
            self.assertEqual(context['named_areas']['names'], ['Main navigation', 'Question feed'])
            self.assertEqual(catalog.areas_for('REQ-4'), ["getByRole('navigation', { name: 'Main navigation', exact: true })",
                "getByRole('region', { name: 'Question feed', exact: true })"])

    def test_controls_the_scenarios_use_inside_an_area_are_listed_with_that_area(self):
        # Real run: "Ask Question" sat just above the "Question feed" section; hidden tests look
        # for it inside the section and every test that created a question failed.
        requirements = {**LINKED, 'children': [*LINKED['children'], {'id': 'REQ-4', 'name': 'Feed',
            'description': 'Follow Questions in Main navigation. Question feed exposes Ask Question and summaries.',
            'scenarios': [{'id': 'SCN-4-1', 'steps': [{'id': 'ST-4-1', 'Given': 'A visitor',
                'When': 'Click Ask Question in Question feed, fill Title.', 'Then': 'The editor opens.'}]}]}]}
        with TemporaryDirectory() as tmp:
            catalog = RequirementCatalog(write_input(Path(tmp), external=False, requirements=requirements))
            pairs = catalog.initial_context(max_chars=10 ** 6)['controls_inside_areas']['pairs']
            self.assertEqual(pairs, ["'Questions' inside 'Main navigation'", "'Ask Question' inside 'Question feed'"])
            self.assertIn("'Ask Question' inside getByRole('region', { name: 'Question feed', exact: true })",
                catalog.controls_inside_for('REQ-4', ['SCN-4-1']))

    def test_unannotated_controls_are_buttons_for_the_agent_and_the_generated_tests(self):
        # Hidden tests (real BookStack run): button(page, 'Edit').click() on an "Edit" the requirement
        # gives no role; the application made it a link because "a link opens a page".
        from infrastructure.verification.acceptance import AUTHOR, REVIEWER
        workflow = (Path(__file__).resolve().parents[1] / 'profiles/arcbench-app/workflow.md').read_text(encoding='utf-8')
        self.assertIn('is a <button>, also when it opens another page', workflow)
        self.assertNotIn('a link to open a page', workflow)
        self.assertIn('A control whose role the requirement does not state is a button', AUTHOR)
        self.assertIn('a test locating it as a button is right', REVIEWER)

    def test_the_page_at_failure_is_read_without_the_test_source(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'generated-abc-SCN-3-1'
            folder.mkdir()
            (folder / 'error-context.md').write_text(ERROR_CONTEXT, encoding='utf-8')
            pages = failure_pages(tmp)
            page = pages[('generated/abc.spec.ts', 'SCN-3-1: comment')]
            self.assertIn('textbox "Body"', page)
            self.assertNotIn('SECRET', page)
            self.assertEqual(alerts(page), ['alert: paragraph: Body is required (minimum 220 characters)'])

    def test_a_page_of_a_few_lines_is_given_whole_and_the_largest_snapshot_is_the_page(self):
        self.assertEqual(alerts('- text: "{\\"error\\":\\"Invalid request\\"}"\n'),
            ['whole page: text: "{\\"error\\":\\"Invalid request\\"}"'])
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'case'
            folder.mkdir()
            text = ERROR_CONTEXT.replace('```\nError: expect(locator).toBeVisible() failed\n```',
                '```\nError: toHaveAttribute failed\n```\n\n```yaml\n- textbox "Password": x\n```')
            (folder / 'error-context.md').write_text(text, encoding='utf-8')
            self.assertIn('- main:', failure_pages(tmp)[('generated/abc.spec.ts', 'SCN-3-1: comment')])

    def test_a_correction_that_drops_assertions_or_exact_names_is_refused(self):
        before = "await expect(page.getByRole('heading', { name: t, exact: true })).toBeVisible();\nexpect(x).toBe(1);"
        self.assertIn('assertions', weakened(before, "await expect(page.getByText(t)).toBeVisible();"))
        self.assertIn('exact names', weakened(before, "await expect(page.getByText(t)).toBeVisible();\nexpect(x).toBe(1);"))
        self.assertIsNone(weakened(before, before.replace("'heading'", "'link'")))

    def test_a_test_any_review_kept_or_refused_is_never_set_aside(self):
        from infrastructure.verification.acceptance import AcceptanceSuite, MAX_REVIEWS
        suite = AcceptanceSuite.__new__(AcceptanceSuite)
        suite.disputed, suite._manifest = set(), lambda: None
        suite.review_attempts = {'a.spec.ts': MAX_REVIEWS, 'b.spec.ts': MAX_REVIEWS, 'c.spec.ts': MAX_REVIEWS}
        suite.reviews = [{'file': 'a.spec.ts', 'decision': 'kept'}, {'file': 'a.spec.ts', 'decision': 'corrected'},
            {'file': 'b.spec.ts', 'decision': 'corrected'}, {'file': 'b.spec.ts', 'decision': 'rejected_correction'},
            {'file': 'c.spec.ts', 'decision': 'corrected'}, {'file': 'c.spec.ts', 'decision': 'corrected'}]
        self.assertEqual([suite.dispute(f) for f in ('a.spec.ts', 'b.spec.ts', 'c.spec.ts')], [False, False, True])

    def test_a_disputed_scenario_is_neither_passed_nor_an_omission(self):
        with TemporaryDirectory() as tmp:
            registry = CoverageRegistry(RequirementCatalog(write_input(Path(tmp), external=False, requirements=LINKED)))
            registry.record_functional([{'title': 'SCN-3-1: comment', 'status': DISPUTED, 'covers': ['SCN-3-1']}],
                'r1', 'e', complete=False)
            self.assertEqual(registry.entries['SCN-3-1']['functional'], DISPUTED)
            self.assertNotIn('SCN-3-1', registry.omissions())

    def test_feedback_shows_what_the_page_said_and_what_was_set_aside(self):
        report = {'round': 2, 'clean_state': False, 'stage': 'acceptance', 'status': 'failed', 'evidence': 'e.json',
            'stages': [], 'stopped_services': [], 'disputed': [{'covers': ['SCN-9'], 'title': 'SCN-9: x'}],
            'failures': [{'stage': 'acceptance', 'covers': ['SCN-3-1'], 'title': 'SCN-3-1: comment',
                'errors': ['element not found'], 'page_alerts': ['alert: Body is required (minimum 220 characters)']}]}
        text = feedback(report, repeated=False, remaining={})
        self.assertIn('The page showed: alert: Body is required', text)
        self.assertIn('Set aside, not counted against the application', text)
        self.assertIn('disputes', text)

    def test_set_aside_tests_are_shown_with_what_they_looked_for(self):
        from infrastructure.verification.driver import disputed_review
        text = disputed_review({'disputed': [{'covers': ['SCN-3-2'], 'title': 'SCN-3-2: author',
            'errors': ["Error: expect(locator).toBeVisible() failed\n\nLocator: getByRole('region', { name: 'Author' })"
                ".locator('img')"], 'page_alerts': []}]})
        self.assertIn('a review can be mistaken', text)
        self.assertIn("Locator: getByRole('region', { name: 'Author' }).locator('img')", text)


class RequestProgressTests(unittest.TestCase):
    def test_requests_since_the_last_new_best_are_counted(self):
        from infrastructure.verification.driver import requests_without_progress
        reports = [{'passed': 22, 'requests': 100}, {'passed': 36, 'requests': 180}, {'passed': 30, 'requests': 260}]
        self.assertEqual(requests_without_progress(reports, 340), 160)
        self.assertEqual(requests_without_progress([], 50), 0)


class ProgressTests(unittest.TestCase):
    def test_rounds_without_a_new_best_are_counted(self):
        # The real run: 5, 16, 16, 17, 16, 17, 17 passing.
        reports = [{'passed': n} for n in (5, 16, 16, 17, 16, 17, 17)]
        self.assertEqual(rounds_without_progress(reports), 3)
        self.assertEqual(rounds_without_progress(reports + [{'passed': 18}]), 0)
        self.assertEqual(rounds_without_progress([]), 0)


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_reasoning_is_shortened_and_recent_reasoning_kept(self):
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                messages = agent.state.messages
                messages[:] = [Message('system', 's'), Message('user', 'task')]
                for index in range(REASONING_WINDOW + 3):
                    messages += [Message('assistant', '', (ToolCall(f'c{index}', 'list_files', '{}'),),
                        reasoning_content='thinking ' * 2000),
                        Message('tool', json.dumps({'ok': True, 'result': {'files': []}, 'error': None}),
                            tool_call_id=f'c{index}')]
                window = agent.loop.context
                window.profile = replace(agent.profile, prune_min_bytes=1000, observation_window=0)
                self.assertIsNotNone(window.prune())
                reasoning = [m.reasoning_content for m in messages if m.role == 'assistant']
                self.assertTrue(all('shortened by the host' in text for text in reasoning[:3]))
                self.assertTrue(all(len(text) > 10000 for text in reasoning[-REASONING_WINDOW:]))

    async def test_compaction_keeps_more_recent_work_by_shortening_older_reasoning(self):
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                messages = agent.state.messages
                messages[:] = [Message('system', 's'), Message('user', 'task')]
                for index in range(6):
                    messages += [Message('assistant', '', (ToolCall(f'c{index}', 'list_files', '{}'),),
                        reasoning_content='r' * 9000),
                        Message('tool', json.dumps({'ok': True, 'result': 'x' * 1000, 'error': None}),
                            tool_call_id=f'c{index}')]
                window = agent.loop.context
                window.profile = replace(agent.profile, max_context_bytes=80000 + size(messages[:2]),
                    prune_min_bytes=0, context_ceiling_bytes=0)
                self.assertIsNotNone(window.compact())
                kept = [m for m in messages if m.role == 'assistant' and m.tool_calls]
                self.assertGreater(len(kept), 2)                              # 9 KB each: more than two fit.
                self.assertEqual(len(kept[-1].reasoning_content), 9000)        # The latest keeps it all.
                self.assertTrue(all('shortened by the host' in m.reasoning_content for m in kept[:-1]))
                ids = {m.tool_calls[0].id for m in kept}
                results = {m.tool_call_id for m in messages if m.role == 'tool'}
                self.assertEqual(ids, results)                                 # Pairs stay complete.

    async def test_compaction_memory_holds_a_host_journal_and_only_the_latest_feedback(self):
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                (agent.state.workspace / 'backend' / 'notes.ts').write_text(
                    "export function listNotes() {}\nrouter.get('/api/notes', listNotes);\n", encoding='utf-8')
                agent.state.verifications.append({'round': 1, 'status': 'failed', 'passed': 3, 'failing': ['SCN-A-1'],
                    'first_errors': {'SCN-A-1': 'alert: too short'}})
                messages = agent.state.messages
                messages[:] = [Message('system', 's'), Message('user', 'task'),
                    Message('user', 'Host verification round 1 did not accept the application.'),
                    Message('user', 'Host verification round 2 did not accept the application.')]
                for index in range(6):
                    messages += [Message('assistant', '', (ToolCall(f'c{index}', 'list_files', '{}'),)),
                        Message('tool', json.dumps({'ok': True, 'result': 'x' * 4000, 'error': None}),
                            tool_call_id=f'c{index}')]
                window = agent.loop.context
                window.profile = replace(agent.profile, max_context_bytes=36000 + size(messages[:2]),
                    prune_min_bytes=0, context_ceiling_bytes=0)
                self.assertIsNotNone(window.compact())
                memory = json.loads(next(m for m in messages if m.content.startswith('Working memory')).content
                    .split('\n', 1)[1])
                journal = memory['host_journal']
                self.assertIn('exports: listNotes', journal['code_map']['backend/notes.ts'])
                self.assertIn('GET /api/notes', journal['code_map']['backend/notes.ts'])
                self.assertEqual(journal['verification_history'][-1]['first_errors'], {'SCN-A-1': 'alert: too short'})
                feedback_left = [m.content for m in messages if m.content.startswith('Host verification round')]
                self.assertEqual(feedback_left, ['Host verification round 2 did not accept the application.'])


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_provider_error_is_continued_once_and_an_empty_application_is_not_verified(self):
        from infrastructure.runtime.model import ProviderError
        from infrastructure.verification.driver import FinalizationDriver
        from infrastructure.verification.verifier import HostVerifier

        class Failing(ScriptedModel):
            async def respond(self, messages, tools):
                self.requests.append(len(messages))
                raise ProviderError('APITimeoutError (status=None)')
        with TemporaryDirectory() as tmp:
            model = Failing([])
            agent, tooling, _ = make_agent(Path(tmp), model, generate=True)
            async with agent:
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, model,
                    agent.input_dir, tooling=tooling)
                outcome = await FinalizationDriver(agent, verifier).run()
                self.assertEqual(len(model.requests), 2)                     # The task, then one continuation.
                self.assertEqual(outcome.status, 'provider_error')
                self.assertIn('verification skipped', outcome.cause)
                self.assertEqual(verifier.rounds, 0)
                self.assertTrue(any('smaller steps' in m.content for m in agent.state.messages if m.role == 'user'))


class DisputeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_test_judged_wrong_twice_is_set_aside_and_the_agent_can_dispute_one(self):
        with TemporaryDirectory() as tmp:
            reviews = []

            def reviewer(messages, schemas):
                payload = json.loads(messages[1].content)
                reviews.append(payload)
                source = payload['test_file'].replace("getByText('second')", "getByText('second account')")
                return ModelResponse('The page shows the test is wrong.\n```ts\n' + source + '```')
            model = ScriptedModel([reviewer] * 6)
            agent, tooling, _ = make_agent(Path(tmp), model, generate=False, external=False)
            async with agent:
                from infrastructure.verification.acceptance import AUTHOR
                from infrastructure.verification.verifier import HostVerifier
                from tests.verification_support import GENERATED
                verifier = agent.verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget,
                    model, agent.input_dir, tooling=tooling)
                agent.tools.acceptance_runner = agent.acceptance_now
                suite = verifier.suite
                suite.assemble()
                relative = suite.generated_path('REQ-B')
                suite._write(relative, GENERATED.split('```ts\n')[1].split('```')[0].encode(), 'generated',
                    requirement='REQ-B')
                verifier.generated = True
                self.assertTrue(AUTHOR)
                first = await verifier.verify(clean_state=False)
                self.assertEqual(first['status'], 'failed')                   # Nothing passes: no review yet.
                self.assertEqual(reviews, [])
                await verifier.verify(clean_state=False)                     # One review per round.
                second = await verifier.verify(clean_state=False)            # Reviewed twice, still failing.
                self.assertEqual(len(reviews), 2)
                self.assertIn('referenced_requirements', reviews[0])
                self.assertIn('page_at_failure', reviews[0]['failures'][0])
                self.assertEqual([item['covers'] for item in second['disputed']], [['SCN-B-1']])
                self.assertNotEqual(second['status'], 'failed')               # Set aside, not counted.
                # The agent disputes a scenario: one more review with its reason.
                suite.disputed.clear()
                verifier.last_report = {**second, 'status': 'failed', 'failures': [{'key': relative + ' › SCN-B-1: x',
                    'title': 'SCN-B-1: x', 'errors': ['boom'], 'covers': ['SCN-B-1']}]}
                answer = (await agent.tools.execute(call('run_acceptance_tests',
                    disputes=[{'scenario': 'SCN-B-1', 'reason': 'REQ-B never names this text'}]))).value
                self.assertEqual(reviews[-1]['agent_claim'], 'REQ-B never names this text')
                self.assertEqual(answer['disputes'][0]['scenario'], 'SCN-B-1')


if __name__ == '__main__':
    unittest.main()
