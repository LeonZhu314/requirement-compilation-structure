from hashlib import sha256
import json
from pathlib import Path
import unittest
import zipfile
import importlib.util


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / 'benchmarks/baseline/manifest.json').exists(), 'Reference artifacts live in the source checkout')
class BaselineTests(unittest.TestCase):
    def test_frozen_archive_reports_and_cases_match_the_manifest(self):
        base = ROOT / 'benchmarks/baseline'
        manifest = json.loads((base / 'manifest.json').read_text())
        archive = base / manifest['source_archive']['path']
        self.assertEqual(sha256(archive.read_bytes()).hexdigest(), manifest['source_archive']['sha256'])
        with zipfile.ZipFile(archive) as z:
            for name, digest in manifest['source_files'].items():
                self.assertEqual(sha256(z.read(name)).hexdigest(), digest)
            self.assertNotIn('.env', z.namelist())
        for report in manifest['historical_reports']:
            self.assertEqual(sha256((base / report['path']).read_bytes()).hexdigest(), report['sha256'])
        cases = json.loads((ROOT / 'benchmarks/cases/manifest.json').read_text())
        self.assertEqual({c['split'] for c in cases}, {'development', 'validation'})
        for case in cases:
            self.assertEqual(sha256((ROOT / 'benchmarks' / case['requirements']).read_bytes()).hexdigest(), case['sha256'])

    def test_failures_and_unknown_costs_are_retained(self):
        spec = importlib.util.spec_from_file_location('benchmark_summary', ROOT / 'benchmarks/summarize.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        base = dict(variant='candidate', case_id='inventory', repeat=1, source_sha256='s', input_sha256='i',
            profile_sha256='p', model='m', reasoning='low', budget={}, environment={},
            external_score=None, wall_seconds=10, input_tokens=10, output_tokens=10, artifacts=[])
        records = [{**base, 'run_id': 'one', 'status': 'completed', 'external_passed': True, 'cost': 2},
            {**base, 'run_id': 'two', 'status': 'timed_out', 'external_passed': False, 'cost': 3}]
        result = module.summarize(records)['candidate']
        self.assertEqual(result['cost_per_success'], 5)
        self.assertEqual(result['success_fraction_all_runs'], 0.5)
        records[1]['cost'] = None
        self.assertIsNone(module.summarize(records)['candidate']['cost_per_success'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            module.summarize([records[0], records[0]])
