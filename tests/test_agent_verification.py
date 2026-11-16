"""Delivery C, steps 13-15 and 18: real-application checks, acceptance, coverage, cache."""

import asyncio
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.messages import ModelResponse
from infrastructure.runtime.requirements import RequirementCatalog
from infrastructure.verification import visual
from infrastructure.verification.acceptance import AcceptanceSuite
from infrastructure.verification.coverage import CoverageRegistry, DIVERGENT, SIMILAR
from infrastructure.verification.results import parse_playwright, parse_tap
from infrastructure.verification.verifier import HostVerifier
from tests.verification_support import GENERATED, call, make_agent, profile, write_input


class ResultStatusTests(unittest.TestCase):
    def test_tap_distinguishes_missing_empty_skipped_failed_and_passed(self):
        self.assertEqual(parse_tap('NO_API_TESTS: none', 3)['status'], 'missing')
        self.assertEqual(parse_tap('# tests 0\n# pass 0\n# fail 0\n', 0)['status'], 'no_tests_executed')
        self.assertEqual(parse_tap('# tests 2\n# pass 1\n# fail 0\n# skipped 1\n', 0)['status'], 'incomplete')
        failed = parse_tap('not ok 1 - rejects duplicate\n  ---\n  code: ERR_ASSERTION\n  ...\n# tests 1\n# pass 0\n# fail 1\n', 1)
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('rejects duplicate', failed['failures'][0])
        self.assertEqual(parse_tap('BACKEND_STARTUP_ERROR: Error: no table\n', 1)['status'], 'failed')
        self.assertEqual(parse_tap('# tests 3\n# pass 3\n# fail 0\n# skipped 0\n# todo 0\n', 0)['status'], 'passed')

    def test_playwright_report_needs_executed_passing_tests(self):
        def report(expected=0, unexpected=0, skipped=0, flaky=0, status='expected', errors=()):
            return json.dumps({'stats': {'expected': expected, 'unexpected': unexpected, 'skipped': skipped, 'flaky': flaky},
                'errors': [{'message': e} for e in errors], 'suites': [{'file': 'a.spec.ts', 'title': 'a.spec.ts', 'specs': [
                    {'title': 'SCN-1: works', 'file': 'a.spec.ts', 'tests': [{'status': status, 'results': [
                        {'duration': 3, 'errors': [{'message': '\x1b[31mexpect(received).toBe(expected)\x1b[39m'}]
                            if status == 'unexpected' else []}]}]}]}]})
        self.assertEqual(parse_playwright(report(expected=1), 0)['status'], 'passed')
        failed = parse_playwright(report(unexpected=1, status='unexpected'), 1)
        self.assertEqual((failed['status'], failed['tests'][0]['errors']), ('failed', ['expect(received).toBe(expected)']))
        self.assertEqual(parse_playwright(report(expected=1, skipped=1), 0)['status'], 'incomplete')
        self.assertEqual(parse_playwright(json.dumps({'stats': {}, 'suites': []}), 0)['status'], 'no_tests_executed')
        self.assertEqual(parse_playwright("Error: browserType.launch: Executable doesn't exist", 1)['status'], 'environment_error')
        self.assertEqual(parse_playwright('SyntaxError: bad config', 1)['status'], 'failed')


class TargetedChecksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agent, self.tooling, self.log = make_agent(self.root, ScriptedModel([]))

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    async def tool(self, name, **args):
        return await self.agent.tools.execute(call(name, **args))

    async def test_results_are_reused_only_while_every_source_is_unchanged(self):
        first = (await self.tool('verify_application', kind='build')).value
        again = (await self.tool('verify_application', kind='build')).value
        self.assertEqual((first['status'], first['cached'], again['cached']), ('passed', False, True))
        self.assertEqual(len(self.log['commands']), 1)
        # An indirect change (not a test file) invalidates the functional result.
        await self.tool('verify_application', kind='backend_tests')
        await self.tool('write_file', path='backend/src/api/register.ts', content='// changed route\n')
        await self.tool('verify_application', kind='backend_tests')
        self.assertEqual(sum(c == ['npm', 'run', 'test:backend'] for c in self.log['commands']), 2)
        # Unchanged again: reused; a clean reset is a new generation and never reuses.
        self.assertTrue((await self.tool('verify_application', kind='backend_tests')).value['cached'])
        self.agent.tools.processes.mirror.reset()
        self.assertFalse((await self.tool('verify_application', kind='build')).value['cached'])

    async def test_typecheck_covers_both_projects_and_failures_are_not_passing(self):
        result = (await self.tool('verify_application', kind='typecheck')).value
        self.assertEqual([p['project'] for p in result['summary']['projects']],
            ['backend/tsconfig.test.json', 'frontend/tsconfig.json'])
        await self.tool('write_file', path='BUILD_BROKEN', content='x')
        broken = (await self.tool('verify_application', kind='build')).value
        self.assertEqual(broken['status'], 'failed')
        self.assertIn('TS2322', broken['output_tail'])
        self.assertFalse(broken['accepted'])
        self.assertIsNotNone((await self.tool('verify_application', kind='build', files=['a.test.ts'])).error)

    async def test_http_request_reaches_only_owned_services_and_reads_real_responses(self):
        async def handle(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 409 Conflict\r\nContent-Type: application/json\r\nContent-Length: 17\r\n'
                b'Connection: close\r\n\r\n{"error":"taken"}')
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            refused = await self.tool('http_request', port=port, path='/api/register')
            self.assertIn('owned service', refused.error)
            self.agent.tools.processes.ports = lambda: {port}
            result = (await self.tool('http_request', port=port, path='/api/register', method='POST',
                body='{"username":"taken"}')).value
            self.assertEqual((result['status'], json.loads(result['body'])), (409, {'error': 'taken'}))
            self.assertIsNotNone((await self.tool('http_request', port=port, path='/x', headers={'Cookie': 'a=b'})).value)
        finally:
            server.close()
            await server.wait_closed()

    async def test_interfaces_are_observations_recorded_for_the_host(self):
        self.assertIsNotNone((await self.tool('interface_write', pages=[{'path': 'home'}])).error)
        self.assertIsNotNone((await self.tool('interface_write', pages=[{'path': '/', 'image': 'UNKNOWN'}])).error)
        self.assertIsNone((await self.tool('interface_write', pages=[{'path': '/register', 'description': 'form'}])).error)
        self.assertEqual(self.agent.state.interfaces['pages'][0]['path'], '/register')


class CoverageRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = RequirementCatalog(write_input(Path(self.tmp.name)))
        self.registry = CoverageRegistry(self.catalog)

    def test_scenario_ids_are_matched_exactly_and_required_aspects_are_listed(self):
        self.assertEqual(self.registry.covers('SCN-A-1: register', '', ''), ['SCN-A-1'])
        self.assertEqual(self.registry.covers('registers', '// requirement: REQ-A', 'REQ-A'), ['REQ-A'])
        self.assertEqual(self.registry.covers('unrelated', '', 'misc'), [])
        self.assertIn('refresh', self.registry.entries['SCN-A-1']['required_aspects'])
        self.assertIn('rejection', self.registry.entries['SCN-A-2']['required_aspects'])
        self.assertIn('distinct_data', self.registry.entries['SCN-B-1']['required_aspects'])

    def test_claims_stay_separate_omissions_show_and_changes_invalidate_proofs(self):
        todos = [{'id': 't1', 'task': 'all', 'status': 'done', 'requirements': ['REQ-A', 'REQ-B']}]
        view = self.registry.view(todos, 'rev1')
        self.assertEqual(view['requirements'][1]['agent_claims'][0]['declared_status'], 'done')
        self.assertEqual(view['requirements'][1]['host_verification'][0]['functional'], 'unverified')
        tests = [{'title': 'SCN-A-1: ok', 'status': 'passed', 'covers': ['SCN-A-1']},
            {'title': 'SCN-A-2: reject', 'status': 'failed', 'covers': ['SCN-A-2']}]
        self.registry.record_functional(tests, 'rev1', 'evidence-1', complete=True)
        summary = self.registry.summary()
        self.assertEqual(summary['functional'], {'passed': 1, 'failed': 1, 'missing': 1})
        self.assertEqual(summary['omissions'], ['SCN-A-2', 'SCN-B-1'])  # A declared-done item is still an omission.
        self.assertEqual(self.registry.entries['SCN-A-1']['evidence'], 'evidence-1')
        self.assertEqual(self.registry.invalidate('rev1'), [])
        self.assertEqual(sorted(self.registry.invalidate('rev2')), ['SCN-A-1', 'SCN-A-2'])
        self.assertEqual(self.registry.entries['SCN-A-1']['functional'], 'stale')
        self.assertEqual(self.registry.entries['SCN-A-1']['last_result'], {'status': 'passed', 'source_revision': 'rev1'})


def picture(layout):
    image = Image.new('RGB', (800, 600), 'white')
    draw = ImageDraw.Draw(image)
    if layout == 'reference':
        draw.rectangle((0, 0, 800, 90), fill=(20, 60, 160))
        draw.rectangle((40, 140, 520, 420), fill=(230, 230, 235), outline=(90, 90, 90))
        for row in range(5):
            draw.rectangle((70, 170 + row * 45, 420, 195 + row * 45), outline=(60, 60, 60))
        draw.rectangle((560, 140, 760, 420), fill=(250, 210, 120))
    elif layout == 'close':
        draw.rectangle((0, 0, 800, 94), fill=(24, 64, 150))
        draw.rectangle((44, 146, 524, 424), fill=(232, 232, 236), outline=(90, 90, 90))
        for row in range(5):
            draw.rectangle((74, 176 + row * 45, 424, 200 + row * 45), outline=(60, 60, 60))
        draw.rectangle((564, 146, 764, 424), fill=(248, 212, 124))
    else:  # The required buttons exist, but the page looks nothing like the reference.
        draw.rectangle((10, 10, 110, 40), outline=(0, 0, 0))
        draw.rectangle((120, 10, 220, 40), outline=(0, 0, 0))
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


class VisualFidelityTests(unittest.IsolatedAsyncioTestCase):
    def test_structure_decides_not_the_mere_presence_of_controls(self):
        close = visual.compare(picture('reference'), picture('close'))
        bare = visual.compare(picture('reference'), picture('bare'))
        self.assertEqual(visual.verdict(close, 0.6), SIMILAR)
        self.assertEqual(visual.verdict(bare, 0.6), DIVERGENT)
        self.assertGreater(close['score'] - bare['score'], 0.25)
        self.assertEqual(visual.verdict(close, 0.6, ['404 /logo.png']), DIVERGENT)

    async def test_functional_pass_does_not_make_a_wrong_screen_conforming(self):
        requirements = {'id': 'ROOT', 'name': 'Home', 'description': {'text': 'Home page',
            'image': [{'id': 'IMG-HOME', 'reference': 'home.png'}]},
            'scenarios': [{'id': 'SCN-H-1', 'steps': [{'id': 'ST-H', 'Given': 'A visitor', 'When': 'Open /', 'Then': 'Show Login'}]}]}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            (root / 'input/home.png').write_bytes(picture('reference'))
            (root / 'input/tests').mkdir()
            (root / 'input/tests/home.spec.ts').write_text("test('SCN-H-1: shows login', async () => {});")
            agent, tooling, log = make_agent(root, ScriptedModel([]), external=False, requirements=requirements,
                visual='require', generate=False, image_mode='disabled')
            try:
                (agent.state.workspace / 'behaviors.txt').write_text('SCN-H-1')
                agent.state.interfaces = {'pages': [{'path': '/', 'image': 'IMG-HOME'}]}
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                captures = {'value': picture('bare')}

                async def compare(browser, image, path, revision):
                    metrics = visual.compare(agent.catalog.resource_data[image], captures['value'])
                    status = visual.verdict(metrics, agent.profile.acceptance.visual_threshold)
                    verifier.registry.record_visual(image, status, revision, 'capture', metrics=metrics)
                    return {'status': status, 'metrics': metrics}
                verifier._compare = compare
                report = await verifier.verify(clean_state=True)
                registry = agent.tools.coverage
                self.assertEqual(registry.entries['SCN-H-1']['functional'], 'passed')
                self.assertEqual(registry.visual['IMG-HOME']['status'], DIVERGENT)
                self.assertEqual((report['status'], report['accepted']), ('failed', False))
                self.assertEqual(report['failures'][0]['key'], 'visual:IMG-HOME')
                captures['value'] = picture('close')
                report = await verifier.verify(clean_state=True)
                self.assertEqual((report['status'], report['accepted']), ('passed', True))
                # Without a declared page the proof is explicitly missing, not assumed.
                agent.state.interfaces = {'pages': []}
                report = await verifier.verify(clean_state=True)
                self.assertEqual(registry.visual['IMG-HOME']['status'], 'missing_interface')
                self.assertEqual(report['status'], 'missing')
            finally:
                await agent.aclose()


class AcceptanceSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def suite(self, **settings):
        source = write_input(self.root)
        catalog = RequirementCatalog(source)
        registry = CoverageRegistry(catalog)
        suite = AcceptanceSuite(self.root / 'suite', catalog, registry, profile(**settings).acceptance, source)
        suite.assemble()
        return suite

    async def no_compile_error(self, relative):
        return None

    async def test_external_tests_are_isolated_versioned_and_only_gaps_are_generated(self):
        suite = self.suite()
        self.assertEqual(suite.specs(), ['external/REQ-A.spec.ts'])
        self.assertEqual(suite.uncovered(), ['SCN-B-1'])
        self.assertFalse(suite.integrity())
        version = suite.version()
        agent, _, _ = make_agent(self.root / 'session', ScriptedModel([
            ModelResponse("```ts\nimport { test } from '@playwright/test';\ntest.skip('SCN-B-1: x', async () => {});\n```"),
            ModelResponse(GENERATED)]))
        try:
            budget, model = agent.loop.budget, agent.loop.model
            created = await suite.generate(model, budget, {'declared_pages': []}, self.no_compile_error)
            self.assertEqual(len(created), 1)                      # First reply rejected (skip), second kept.
            self.assertEqual(len(model.requests), 2)
            self.assertEqual(budget.requests['acceptance_generation'], 2)
            task = json.loads(model.requests[0][0][1].content)
            self.assertEqual(task['scenarios_to_cover'], ['SCN-B-1'])       # Covered scenarios are not regenerated.
            self.assertEqual(task['original_requirement']['id'], 'REQ-B')
            self.assertIn('distinct_data', task['required_aspects']['SCN-B-1'])
            self.assertIn('not expected behavior', task['observed_interfaces']['notice'])
            self.assertNotEqual(suite.version(), version)
            self.assertEqual(suite.uncovered(), [])
            self.assertEqual(await suite.generate(model, budget, {}, self.no_compile_error), [])
            self.assertEqual(len(model.requests), 2)
            self.assertEqual(agent.catalog.consulted, set())        # Host reads are not agent consultations.
            manifest = json.loads((suite.directory / 'manifest.json').read_text())
            self.assertEqual(manifest['files'][created[0]]['origin'], 'generated')
            # Tampering with a host-owned test or with the original is detected.
            (suite.directory / 'external/REQ-A.spec.ts').write_text('test("SCN-A-1: always", () => {});')
            self.assertIn('acceptance file altered: external/REQ-A.spec.ts', suite.integrity())
        finally:
            await agent.aclose()

    async def test_review_changes_a_test_only_with_grounds_and_never_external_ones(self):
        suite = self.suite()
        corrected = GENERATED.replace("getByText('second')", "getByText('second', { exact: true })")
        agent, _, _ = make_agent(self.root / 'session', ScriptedModel([ModelResponse(GENERATED),
            ModelResponse('KEEP The application shows the first account; the requirement demands the second.'),
            ModelResponse('The requirement only says "Show the second account".\n' + corrected),
            ModelResponse('Loosen it.\n```ts\nimport { test } from "@playwright/test";\n```')]))
        try:
            budget, model = agent.loop.budget, agent.loop.model
            relative = (await suite.generate(model, budget, {}, self.no_compile_error))[0]
            failure = [{'title': 'SCN-B-1: the second account sees only its profile', 'errors': ['expected second, got first']}]
            before = suite.files[relative]['sha256']
            self.assertFalse(await suite.review(model, budget, 'external/REQ-A.spec.ts', failure, self.no_compile_error))
            self.assertFalse(await suite.review(model, budget, relative, failure, self.no_compile_error))   # KEEP
            self.assertEqual(suite.files[relative]['sha256'], before)
            self.assertFalse(await suite.review(model, budget, relative, failure, self.no_compile_error))   # Same evidence: no new request.
            self.assertEqual(budget.requests['test_review'], 1)
            other = [{'title': failure[0]['title'], 'errors': ['strict mode violation: 2 elements']}]
            self.assertTrue(await suite.review(model, budget, relative, other, self.no_compile_error))
            self.assertNotEqual(suite.files[relative]['sha256'], before)
            kept = suite.files[relative]['sha256']
            third = [{'title': failure[0]['title'], 'errors': ['another failure']}]
            self.assertFalse(await suite.review(model, budget, relative, third, self.no_compile_error))  # Drops the test: rejected.
            self.assertEqual(suite.files[relative]['sha256'], kept)
            self.assertEqual([r['decision'] for r in suite.reviews], ['kept', 'corrected', 'rejected_correction'])
        finally:
            await agent.aclose()


class HostVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agent, self.tooling, self.log = make_agent(self.root, ScriptedModel([]), generate=False)
        self.verifier = HostVerifier(self.agent.tools, self.agent.profile, self.agent.state, self.agent.loop.budget,
            self.agent.loop.model, self.agent.input_dir, tooling=self.tooling)
        self.workspace = self.agent.state.workspace

    async def asyncTearDown(self):
        await self.agent.aclose()
        self.tmp.cleanup()

    async def test_runs_without_any_pipeline_artifact_and_detects_wrong_business_behavior(self):
        for name in ('db_schema.json', 'backend_apis.json', 'ui_design.json', 'frontend_triggers.json'):
            self.assertFalse(list(self.workspace.rglob(name)))
        # Mutation: duplicate usernames are accepted (SCN-A-2 behavior absent).
        (self.workspace / 'behaviors.txt').write_text('SCN-A-1')
        report = await self.verifier.verify(clean_state=True)
        self.assertEqual((report['status'], report['stage']), ('failed', 'acceptance'))
        self.assertEqual([f['covers'] for f in report['failures']], [['SCN-A-2']])
        self.assertEqual(self.agent.tools.coverage.entries['SCN-A-2']['functional'], 'failed')
        self.assertEqual(self.agent.tools.coverage.entries['SCN-B-1']['functional'], 'missing')   # Visible omission.
        (self.workspace / 'behaviors.txt').write_text('SCN-A-1 SCN-A-2')
        report = await self.verifier.verify(clean_state=True)
        self.assertTrue(report['accepted'])
        self.assertEqual(report['coverage']['omissions'], ['SCN-B-1'])

    async def test_fast_stages_stop_first_and_incremental_rounds_replay_failures_before_a_clean_delivery(self):
        (self.workspace / 'BUILD_BROKEN').write_text('x')
        (self.workspace / 'behaviors.txt').write_text('SCN-A-1')
        report = await self.verifier.verify(clean_state=False)
        self.assertEqual((report['status'], report['stage']), ('failed', 'build'))
        self.assertEqual((self.tooling.runs, self.log['starts']), ([], []))       # Nothing slower ran.
        (self.workspace / 'BUILD_BROKEN').unlink()
        report = await self.verifier.verify(clean_state=False)
        self.assertEqual(report['stage'], 'acceptance')
        self.assertEqual(self.log['resets'], 0)
        self.assertIn('DATABASE_URL', self.log['starts'][-1]['env'])               # New database, not a reset.
        self.assertTrue(self.log['starts'][-1]['host'])
        builds = sum(c == ['npm', 'run', 'build'] for c in self.log['commands'])
        report = await self.verifier.verify(clean_state=False)                      # Unchanged sources: build reused.
        self.assertEqual(sum(c == ['npm', 'run', 'build'] for c in self.log['commands']), builds)
        (self.workspace / 'behaviors.txt').write_text('SCN-A-1 SCN-A-2')
        report = await self.verifier.verify(clean_state=False)
        self.assertEqual((report['status'], report['accepted']), ('candidate', False))
        self.assertEqual(self.tooling.runs[-1], ['external/REQ-A.spec.ts'])        # Previously failing file first.
        report = await self.verifier.verify(clean_state=True)
        self.assertTrue(report['accepted'])
        self.assertEqual(self.log['resets'], 1)
        self.assertNotIn('DATABASE_URL', self.log['starts'][-1]['env'])            # Started as it will be deployed.
        self.assertEqual(sum(c == ['npm', 'run', 'build'] for c in self.log['commands']), builds + 2)
        self.assertEqual(self.verifier.validated_revision, report['source_revision'])

    async def test_startup_environment_missing_tests_and_integrity_are_distinct(self):
        (self.workspace / 'START_BROKEN').write_text('x')
        report = await self.verifier.verify(clean_state=True)
        self.assertEqual((report['status'], report['stage']), ('failed', 'startup'))
        (self.workspace / 'START_BROKEN').unlink()
        self.tooling.environment_error = 'Node.js is required on the host'
        report = await self.verifier.verify(clean_state=True)
        self.assertEqual(report['status'], 'environment_error')
        self.tooling.environment_error = None
        (self.agent.input_dir / 'requirements.yaml').write_text('id: ROOT\nname: rewritten\n')
        report = await self.verifier.verify(clean_state=True)
        self.assertEqual(report['status'], 'integrity_violation')
        self.assertIn('requirements.yaml changed', report['failures'][0]['problems'][0])

    async def test_no_independent_test_is_reported_as_missing_verification(self):
        with TemporaryDirectory() as tmp:
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), external=False, generate=False)
            try:
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                report = await verifier.verify(clean_state=True)
                self.assertEqual((report['status'], report['stage'], report['accepted']), ('missing', 'acceptance', False))
                self.assertEqual([s['status'] for s in report['stages'][:4]], ['passed'] * 4)
            finally:
                await agent.aclose()


if __name__ == '__main__':
    unittest.main()
