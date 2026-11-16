"""Delivery E: comparison protocol tooling (step 23) and ablation-ready variants (step 24)."""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.composer import compose
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ToolCall
from infrastructure.runtime.model import ScriptedModel
from scripts import evaluate

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = {'confirmed': True, 'min_evaluated_pairs': 2, 'min_repeats': 1, 'max_external_success_loss': 0.0,
    'min_external_success_gain': 0.1, 'min_token_gain': 0.2, 'min_time_gain': 0.2}


class FakeRun:
    """Stands for one main.py process: writes the files a real run leaves behind."""
    outcomes = {}
    launched = []

    def __init__(self, argv, cwd=None, stdout=None, stderr=None, env=None, **options):
        self.argv = argv
        self.output = Path(argv[argv.index('--output-dir') + 1])
        self.state = Path(argv[argv.index('--state-dir') + 1]) / 'session'
        profile = Path(argv[argv.index('--profile') + 1]).stem
        self.kind = self.outcomes.get(profile, 'accepted')
        FakeRun.launched.append((profile, self.output))

    def wait(self, timeout=None):
        if self.kind == 'hang':
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.state.mkdir(parents=True)
        (self.output / '.arc').mkdir(parents=True)
        usage = [{'input_tokens': 1000, 'output_tokens': 100, 'cached_input_tokens': 800, 'reasoning_tokens': 60, 'retries': 1},
            {'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None, 'reasoning_tokens': None, 'retries': 0}]
        verifications = [{'status': 'failed', 'clean_state': False, 'usable': True, 'finished_at': 130.0},
            {'status': 'passed', 'clean_state': True, 'usable': True, 'finished_at': 190.0}]
        (self.state / 'session.json').write_text(json.dumps({'usage': usage, 'verifications': verifications}))
        (self.state / 'events.jsonl').write_text(json.dumps({'time': 100.0, 'kind': 'usage', 'data': {}}) + '\n')
        (self.state / 'run-summary.json').write_text(json.dumps({'fingerprints': {'profile': 'profile-sha'}, 'reasoning': 'low'}))
        (self.output / '.arc/run.json').write_text(json.dumps({'status': self.kind, 'model': 'm', 'cause': None,
            'verification_rounds': 2, 'budget': {'requests': {'total': 2}}, 'profile': 'p',
            'state_directory': str(self.state)}))
        return 0 if self.kind == 'accepted' else 1

    def kill(self):
        pass


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('alpha', 'beta'):
            (self.root / 'cases' / name).mkdir(parents=True)
            (self.root / 'cases' / name / 'requirements.yaml').write_text(f'id: {name}\n')
        self.cases = evaluate.load_cases([self.root / 'cases/alpha', self.root / 'cases/beta'])
        self.variants = [{'id': 'base', 'profile': 'profiles/arcbench-app/config.yaml'},
            {'id': 'cand', 'profile': 'profiles/arcbench-app/variant-skills.yaml'}]
        FakeRun.outcomes, FakeRun.launched = {}, []

    def test_schedule_is_paired_alternated_and_inputs_are_fingerprinted(self):
        plan = evaluate.schedule(self.variants, self.cases, 2)
        self.assertEqual([(v['id'], c['id'], r) for v, c, r in plan], [
            ('base', 'alpha', 1), ('cand', 'alpha', 1), ('base', 'beta', 1), ('cand', 'beta', 1),
            ('cand', 'alpha', 2), ('base', 'alpha', 2), ('cand', 'beta', 2), ('base', 'beta', 2)])
        changed = evaluate.tree_sha256(self.root / 'cases/alpha')
        (self.root / 'cases/alpha/requirements.yaml').write_text('id: changed\n')
        self.assertNotEqual(evaluate.tree_sha256(self.root / 'cases/alpha'), changed)
        with self.assertRaisesRegex(ValueError, 'requirements.yaml missing'):
            evaluate.load_cases([self.root / 'no-case-here'])
        self.assertEqual(len(evaluate.load_cases([self.root / 'cases'])), 2)   # A directory of cases.
        self.assertEqual(len(evaluate.source_sha256(ROOT)), 64)
        shipped = evaluate.load_variants(ROOT / 'benchmarks/variants.json')
        self.assertEqual([v['id'] for v in shipped], ['baseline', 'agent', 'agent-skills', 'agent-symbols'])

    def test_every_run_is_recorded_fresh_including_failures_and_timeouts(self):
        FakeRun.outcomes = {'variant-skills': 'hang'}
        stopped = []
        records = self.root / 'runs.jsonl'
        sheets = evaluate.execute(evaluate.schedule(self.variants, self.cases[:1], 2), self.root / 'work', records,
            5, (2.0, 8.0), 3000, runner=FakeRun, stop=lambda process: stopped.append(process))
        self.assertEqual(len(stopped), 2)
        self.assertEqual([s['status'] for s in sheets], ['completed', 'timed_out', 'timed_out', 'completed'])
        self.assertEqual(len({output for _, output in FakeRun.launched}), 4)      # New workspace and state per run.
        saved = evaluate.read_records(records)
        self.assertEqual([s['run_id'] for s in saved], [s['run_id'] for s in sheets])
        done = sheets[0]
        # Cached and reasoning subtotals are reported, never added to the totals.
        self.assertEqual((done['input_tokens'], done['output_tokens'], done['cached_input_tokens'], done['reasoning_tokens']),
            (1000, 100, 800, 60))
        self.assertEqual((done['requests'], done['requests_without_usage'], done['known_retries']), (2, 1, 1))
        self.assertIsNone(done['cost'])                                   # One request has no usage: cost unknown.
        self.assertEqual((done['seconds_to_first_usable'], done['repair_seconds_after_first_failure']), (30.0, 60.0))
        self.assertEqual((done['profile_sha256'], done['reasoning']), ('profile-sha', 'low'))
        self.assertTrue(done['local_accepted'])
        self.assertIsNone(done['external_passed'])                        # Local acceptance is not an external result.
        self.assertEqual((sheets[1]['local_accepted'], sheets[1]['input_tokens']), (False, None))
        summary = evaluate.report(saved)['variants']
        self.assertEqual(summary['cand']['statuses']['timed_out'], 2)
        self.assertEqual((summary['base']['unevaluated'], summary['base']['external_successes']), (2, 0))
        self.assertEqual(summary['base']['runs_with_unknown_usage'], 2)

    def sheet(self, variant, case, repeat, **values):
        base = dict(run_id=f'{variant}-{case}-{repeat}', variant=variant, case_id=case, repeat=repeat, source_sha256='s',
            input_sha256='i', profile_sha256='p', model='m', reasoning='low', budget={}, environment={},
            status='completed', local_accepted=True, external_passed=None, external_score=None, wall_seconds=1000,
            input_tokens=900_000, output_tokens=100_000, requests_without_usage=0, known_retries=0,
            seconds_to_first_usable=None, repair_seconds_after_first_failure=None, cost=None, artifacts=[])
        return {**base, **values}

    def test_external_results_decide_and_criteria_are_fixed_beforehand(self):
        records = self.root / 'runs.jsonl'
        sheets = [self.sheet('base', case, 1) for case in ('a', 'b', 'c')] + [
            self.sheet('cand', 'a', 1, input_tokens=500_000, wall_seconds=700),
            self.sheet('cand', 'b', 1, input_tokens=1_400_000, wall_seconds=1500),      # Costlier: kept for analysis.
            self.sheet('cand', 'c', 1, status='failed', local_accepted=False, input_tokens=400_000, wall_seconds=600)]
        records.write_text(''.join(json.dumps(s) + '\n' for s in sheets))
        report = evaluate.report(evaluate.read_records(records), 'base', 'cand', CRITERIA)['comparison']
        self.assertEqual(report['decision']['verdict'], 'insufficient_evidence')       # Nothing evaluated externally.
        with self.assertRaisesRegex(ValueError, 'Only a completed run'):
            evaluate.attach_external(records, 'cand-c-1', True, 1.0)
        for run, passed in (('base-a-1', True), ('base-b-1', True), ('base-c-1', True),
                ('cand-a-1', True), ('cand-b-1', False), ('cand-c-1', False)):
            evaluate.attach_external(records, run, passed, 1.0 if passed else 0.2)
        result = evaluate.report(evaluate.read_records(records), 'base', 'cand', CRITERIA)
        comparison = result['comparison']
        self.assertEqual((comparison['evaluated_pairs'], comparison['external_success_delta']), (3, -0.667))
        self.assertEqual(comparison['decision']['verdict'], 'reject')                   # Cheaper but worse is rejected.
        self.assertEqual([p['case_id'] for p in comparison['candidate_costlier']], ['b'])
        self.assertEqual(result['variants']['cand']['false_local_successes'], 1)        # Accepted locally, failed externally.
        self.assertEqual(comparison['token_ratio'], 0.867)
        unconfirmed = evaluate.report(evaluate.read_records(records), 'base', 'cand', {**CRITERIA, 'confirmed': False})
        self.assertEqual(unconfirmed['comparison']['decision']['verdict'], 'insufficient_evidence')
        for run in ('cand-b-1', 'cand-c-1'):
            evaluate.attach_external(records, run, False, 0.2)
        equal = [self.sheet('base', c, 1, external_passed=True) for c in ('a', 'b')] + [
            self.sheet('cand', c, 1, external_passed=True, input_tokens=500_000) for c in ('a', 'b')]
        self.assertEqual(evaluate.report(equal, 'base', 'cand', CRITERIA)['comparison']['decision'],
            {'verdict': 'adopt', 'reasons': ['tokens'], 'limits': 'Paired local runs; a removed pipeline is not itself evidence of a gain.'})
        same = [self.sheet(v, c, 1, external_passed=True) for v in ('base', 'cand') for c in ('a', 'b')]
        self.assertEqual(evaluate.report(same, 'base', 'cand', CRITERIA)['comparison']['decision']['verdict'], 'no_useful_gain')

    def test_shipped_criteria_are_proposals_until_confirmed(self):
        criteria = json.loads((ROOT / 'benchmarks/criteria.json').read_text())
        self.assertIs(criteria['confirmed'], False)
        self.assertEqual(evaluate.main(['plan', '--variants', str(ROOT / 'benchmarks/variants.json'),
            '--cases', str(self.root / 'cases/alpha')]), 0)
        self.assertEqual(evaluate.main(['run', '--variants', str(ROOT / 'benchmarks/variants.json'), '--cases',
            str(self.root / 'cases/alpha'), '--records', str(self.root / 'r.jsonl'), '--work', str(self.root / 'w')]), 2)
        self.assertFalse((self.root / 'r.jsonl').exists())                # No paid run without --yes.


class VariantTests(unittest.IsolatedAsyncioTestCase):
    async def test_variants_add_one_mechanism_each_and_the_default_profile_is_unchanged(self):
        base = load_profile(environment={})
        skills = load_profile(ROOT / 'profiles/arcbench-app/variant-skills.yaml', environment={})
        symbols = load_profile(ROOT / 'profiles/arcbench-app/variant-symbols.yaml', environment={})
        self.assertEqual((base.skills, 'read_skill' in base.tools, 'find_symbol' in base.tools), ((), False, False))
        self.assertEqual(set(skills.tools) - set(base.tools), {'read_skill'})
        self.assertEqual(set(symbols.tools) - set(base.tools), {'find_symbol'})
        self.assertEqual((skills.budget, skills.acceptance, skills.role), (base.budget, base.acceptance, base.role))
        self.assertNotIn('read_skill', compose(base))
        self.assertIn('sql, http, react, playwright', compose(skills))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'base.yaml').write_text((ROOT / 'profiles/arcbench-app/config.yaml').read_text())
            for name in ('role.md', 'workflow.md'):
                (root / name).write_text('text')
            (root / 'bad.yaml').write_text('extends: base.yaml\nskills: [sql]\n')
            with self.assertRaisesRegex(ValueError, 'enabled together'):
                load_profile(root / 'bad.yaml', environment={})
            (root / 'escape.yaml').write_text('extends: ../base.yaml\n')
            with self.assertRaisesRegex(ValueError, 'same directory'):
                load_profile(root / 'escape.yaml', environment={})
            agent = ApplicationAgent(root / 'app', model=ScriptedModel([]), profile=skills)
            try:
                async def tool(tool_name, **arguments):
                    return await agent.tools.execute(ToolCall('c', tool_name, json.dumps(arguments)))
                guide = await tool('read_skill', name='sql')
                self.assertIn('seedFiles', guide.value['guide'])
                self.assertIn('available: sql', (await tool('read_skill', name='rust')).error)
                self.assertEqual((await tool('find_symbol', name='x')).error, 'TOOL_NOT_ALLOWED')
            finally:
                await agent.aclose()
            agent = ApplicationAgent(root / 'app2', model=ScriptedModel([]), profile=symbols)
            try:
                app = agent.state.workspace
                (app / 'backend').mkdir()
                (app / 'backend/account.sql').write_text('CREATE TABLE IF NOT EXISTS account (id INTEGER);\n')
                (app / 'backend/api.ts').write_text('export function findAccount(id: number) { return id; }\n'
                    'app.post("/api/login", handler);\nconst row = db.prepare("SELECT * FROM account").get();\n')
                (app / 'ui.tsx').write_text('import { findAccount } from "./backend/api";\nfindAccount(1);\n')
                result = await agent.tools.execute(ToolCall('c', 'find_symbol', '{"name": "findAccount"}'))
                self.assertEqual([d['path'] for d in result.value['definitions']], ['backend/api.ts'])
                self.assertEqual(result.value['total_uses'], 2)
                table = await agent.tools.execute(ToolCall('c', 'find_symbol', '{"name": "account"}'))
                self.assertEqual(table.value['definitions'][0]['path'], 'backend/account.sql')
                self.assertEqual(table.value['uses'][0]['path'], 'backend/api.ts')
                route = await agent.tools.execute(ToolCall('c', 'find_symbol', '{"name": "/api/login"}'))
                self.assertEqual(route.value['definitions'][0]['line'], 2)
            finally:
                await agent.aclose()


if __name__ == '__main__':
    unittest.main()
