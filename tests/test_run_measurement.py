"""Measurement before optimization: where a run spent its requests, tokens and time."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.budget import Budget, BudgetSettings
from infrastructure.runtime.messages import ModelResponse, Usage
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.persistence import restore_session, session_payload
from infrastructure.verification.driver import FinalizationDriver
from scripts import analyze_run, evaluate
from tests.verification_support import call, make_agent, tools

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_phases_and_tools_are_accounted_separately_and_survive_a_resume(self):
        clock = Clock()
        state = type('State', (), {'requests': 0, 'auxiliary_requests': 0, 'compactions': [], 'id': 's', 'status': 'x',
            'messages': [], 'todos': [], 'notes': {}, 'interfaces': {}, 'checks': [], 'verifications': [], 'usage': []})()
        budget = Budget(state, 10, BudgetSettings(), clock)
        budget.start()
        with budget.timed('model.main'):
            clock.now += 30
        with budget.timed('tools'):
            clock.now += 8                                   # Two overlapping calls of 8 s and 5 s.
        budget.add_tool_time('read_files', 8)
        budget.add_tool_time('database_query', 5)
        budget.add_time('verification', 50)
        budget.add_time('verification.build', 20)
        budget.add_time('verification.acceptance', 28)
        clock.now += 50 + 12                                 # Verification, then 12 s nothing accounts for.
        timing = budget.report()['timing']
        self.assertEqual((timing['model_seconds'], timing['tools_seconds'], timing['verification_seconds'],
            timing['other_seconds']), (30.0, 8.0, 50.0, 12.0))
        self.assertEqual(timing['verification'], {'acceptance': 28.0, 'build': 20.0})
        self.assertEqual(list(timing['tools'].items())[0], ('read_files', {'calls': 1, 'seconds': 8.0}))
        # The same measurements continue after a resume; an older state without them still loads.
        payload = json.loads(json.dumps(session_payload(state, budget, {}, {})))
        resumed = Budget(state, 10, BudgetSettings(), clock)
        restore_session(payload, state, resumed)
        self.assertEqual(resumed.report()['timing'], budget.report()['timing'])
        for key in ('seconds', 'tool_seconds', 'pruned', 'input_tokens', 'output_tokens', 'cached_tokens'):
            payload['budget'].pop(key)
        older = Budget(state, 10, BudgetSettings(), clock)
        restore_session(payload, state, older)
        self.assertEqual(older.report()['timing']['model_seconds'], 0.0)

    async def test_a_real_session_reports_model_tool_and_verification_time_with_its_rounds(self):
        model = ScriptedModel([tools(call('read_files', 'r', files=[{'path': 'README.md'}]),
                call('write_file', 'w', path='behaviors.txt', content='SCN-A-1\n')),
            ModelResponse('Done.', usage=Usage(900, 40, cached_input_tokens=600)),
            tools(call('write_file', 'w2', path='behaviors.txt', content='SCN-A-1 SCN-A-2\n')), ModelResponse('Fixed.')])
        agent, tooling, _ = make_agent(self.root, model, generate=False)
        async with agent:
            outcome = await agent.generate(tooling=tooling)
            report = {**outcome.to_dict(), 'model': 'scripted', 'verifications': agent.state.verifications,
                'state_directory': str(agent.state.state_directory)}
        self.assertEqual(outcome.status, 'accepted')
        timing = report['budget']['timing']
        self.assertEqual(sorted(timing['tools']), ['read_files', 'write_file'])
        self.assertEqual(timing['tools']['write_file']['calls'], 2)
        for stage in ('integrity', 'dependencies', 'build', 'startup', 'acceptance'):
            self.assertIn(stage, timing['verification'])
        self.assertGreaterEqual(timing['verification_seconds'], sum(timing['verification'].values()) - 0.5)
        self.assertEqual([r['status'] for r in report['verifications']], ['failed', 'candidate', 'passed'])
        self.assertIn('acceptance', report['verifications'][0]['stage_seconds'])

        facts = analyze_run.decompose(report)
        self.assertEqual((facts['requests'], facts['tool_calls'], facts['verification_rounds'],
            facts['failed_verification_rounds']), (4, 3, 3, 1))
        self.assertEqual((facts['input_tokens'], facts['cached_input_tokens'], facts['cached_input_ratio']), (900, 600, 0.667))
        self.assertEqual(facts['tool_calls_per_request'], 0.75)
        line = analyze_run.one_line(facts)
        for expected in ('requests 4', '(67% cached)', 'verification rounds 3, failed 1'):
            self.assertIn(expected, line)
        # The command prints one report per run and a comparison when several are given.
        path = self.root / 'app/.arc/run.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding='utf-8')
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(analyze_run.main([str(self.root / 'app'), str(path)]), 0)
        self.assertIn('round 1 incremental failed', out.getvalue())
        self.assertIn('== comparison', out.getvalue())

    def test_an_older_report_is_decomposed_from_its_events_and_unknowns_stay_unknown(self):
        state = self.root / 'state'
        state.mkdir()
        events = [(0.0, 'resumed', {}), (12.0, 'usage', {'input_tokens': 10}),
            (12.5, 'tool_started', {'call_id': 'a', 'name': 'run_command'}),
            (40.5, 'tool_finished', {'call_id': 'a'}), (50.5, 'usage', {'input_tokens': 10}),
            (51.0, 'usage', {'source': 'auxiliary'})]
        (state / 'events.jsonl').write_text(''.join(json.dumps({'time': t, 'kind': k, 'data': d}) + '\n'
            for t, k, d in events) + '{"time": 60, "kin', encoding='utf-8')          # Truncated last line.
        old = {'status': 'accepted', 'model': 'm', 'verification_rounds': 3, 'state_directory': str(state),
            'budget': {'elapsed_seconds': 2763.0, 'requests': {'main': 60, 'total': 62, 'limit': 250},
                'tool_calls': {'total': 150, 'limit': 2500}, 'reported_tokens': {'total': 2_000_000}}}
        facts = analyze_run.decompose(old)
        self.assertEqual((facts['model_seconds'], facts['tools'], facts['timing_source']),
            (22.0, {'run_command': {'calls': 1, 'seconds': 28.0}}, 'events.jsonl'))
        self.assertIsNone(facts['verification_seconds'])
        self.assertIsNone(facts['input_tokens'])
        self.assertIn('unknown', analyze_run.one_line(facts))
        old['state_directory'] = str(self.root / 'gone')
        self.assertIsNone(analyze_run.decompose(old)['model_seconds'])
        self.assertIn('unknown', analyze_run.render('old', analyze_run.decompose(old)))


class CaseSetAndRepeatTests(unittest.TestCase):
    def test_the_shipped_case_set_loads_and_is_large_enough_for_the_criteria(self):
        cases = evaluate.load_cases([ROOT / 'benchmarks/cases', ROOT / 'input'])
        self.assertEqual(sorted(case['id'] for case in cases),
            ['accounts', 'booking', 'input', 'inventory', 'library', 'orders', 'presentation'])
        criteria = json.loads((ROOT / 'benchmarks/criteria.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases), criteria['min_cases'])
        self.assertEqual(criteria['min_repeats'], 2)
        self.assertEqual(len(evaluate.load_cases([ROOT / 'benchmarks/cases/validation'])), 2)
        with self.assertRaises(ValueError):
            evaluate.load_cases([ROOT / 'profiles'])

    def test_a_single_repeat_or_a_single_case_is_insufficient_evidence(self):
        criteria = {'confirmed': True, 'min_evaluated_pairs': 2, 'min_cases': 2, 'min_repeats': 2,
            'max_external_success_loss': 0.0, 'min_external_success_gain': 0.1, 'min_token_gain': 0.2, 'min_time_gain': 0.2}
        comparison = {'evaluated_pairs': 4, 'paired_cases': 2, 'min_repeats_per_case': 2, 'external_success_delta': 0.0,
            'token_ratio': 0.6, 'wall_ratio': 0.9}
        self.assertEqual(evaluate.decide(comparison, criteria)['verdict'], 'adopt')
        once = evaluate.decide({**comparison, 'min_repeats_per_case': 1}, criteria)
        self.assertEqual(once['verdict'], 'insufficient_evidence')
        self.assertIn('repeat', once['reasons'][0])
        single = evaluate.decide({**comparison, 'paired_cases': 1}, criteria)
        self.assertIn('case', single['reasons'][0])


if __name__ == '__main__':
    unittest.main()
