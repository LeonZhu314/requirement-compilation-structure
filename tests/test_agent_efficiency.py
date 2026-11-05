"""Uncapped agents continue to real acceptance while retaining efficient batched reads."""

import tempfile
import unittest
from importlib import import_module
from inspect import signature
from pathlib import Path
from unittest.mock import Mock, patch

from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.feedback import compact_feedback
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tools import FileTools
from infrastructure.stages.frontend.ui.testing import require_green


class AgentEfficiency(unittest.TestCase):
    def test_pipeline_defaults_do_not_restore_attempt_or_round_caps(self):
        entries = (
            ('02_build_db_schema', 'build_db_schema', 'max_attempts'),
            ('03_infer_db_obligations', 'infer_db_obligations', 'max_attempts'),
            ('05_implement_db', 'implement_db', 'max_attempts'),
            ('05_implement_db', 'implement_db', 'max_turns'),
            ('06_design_backend_apis', 'design_backend_apis', 'max_attempts'),
            ('08_implement_backend_tdd', 'implement_backend_tdd', 'max_turns'),
            ('09_design_ui', 'design_frontend_ui', 'max_attempts'),
            ('10_implement_ui', 'implement_frontend_ui', 'max_turns'),
            ('11_design_frontend_triggers', 'design_frontend_triggers', 'max_attempts'),
            ('12_implement_frontend_tdd', 'implement_frontend_triggers', 'max_turns'),
            ('infrastructure.stages.database.implementation', 'implement_startup_data', 'max_turns'),
            ('infrastructure.stages.database.implementation', 'verify_database_runtime', 'max_turns'),
            ('infrastructure.stages.frontend.ui.synthesis', 'synthesize_ui', 'max_attempts'),
            ('infrastructure.stages.frontend.ui.implementation', 'implement_ui', 'max_turns'),
            ('infrastructure.stages.frontend.triggers.synthesis', 'synthesize_triggers', 'max_attempts'),
            ('infrastructure.stages.frontend.triggers.implementation', 'run_trigger_tdd', 'max_turns'),
            ('infrastructure.stages.frontend.triggers.acceptance', 'run_independent_acceptance', 'max_turns'),
        )
        for module, function, parameter in entries:
            with self.subTest(module=module, parameter=parameter):
                self.assertIsNone(signature(getattr(import_module(module), function)).parameters[parameter].default)

    def test_discovery_can_exceed_the_previous_call_cap_and_finish(self):
        records = {f'E{i}': {'fields': {}} for i in range(20)}
        responses = [{'context_request': {'kind': 'schema', 'ids': [key]}} for key in records] + [{'entities': {}}]
        model = Mock(generate_json=Mock(side_effect=responses))
        accept = Mock(return_value='accepted')
        result, _ = propose_json(model, '', {}, accept, Mock(), 'schema',
            context_index=ContextIndex({'schema': records}))
        self.assertEqual(result, 'accepted')
        self.assertEqual(model.generate_json.call_count, 21)
        accept.assert_called_once_with({'entities': {}})

    def test_file_reads_can_exceed_the_previous_cap_before_implementation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [f'file{i}.ts' for i in range(20)]
            for path in paths:
                (root / path).write_text('export const value = 1;')
            model = Mock(generate_json=Mock(side_effect=[{'tool_calls': [
                {'tool': 'read_file', 'path': path}]} for path in paths] + [
                    {'tool_calls': [{'tool': 'edit_file', 'path': 'fix.ts',
                        'operation': 'create', 'new_content': 'export const fixed = true;'}]}]))
            gate = Mock(return_value={'green': True})
            run_file_agent(model, '', {}, FileTools(root, ['fix.ts']), gate, None, Mock(), 'read')
            self.assertEqual(model.generate_json.call_count, 21)
            self.assertTrue((root / 'fix.ts').is_file())
            gate.assert_called_once()

    def test_batched_reads_still_support_a_real_edit_and_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ('a.ts', 'b.ts'):
                (root / path).write_text('const value = 1;\nexport { value };\n')
            model = Mock(generate_json=Mock(side_effect=[{'tool_calls': [
                {'tool': 'read_file', 'path': 'a.ts'}, {'tool': 'read_file', 'path': 'b.ts'}]},
                {'tool_calls': [{'tool': 'edit_file', 'path': 'a.ts', 'operation': 'replace',
                    'old_content': 'value = 1', 'new_content': 'value = 2'}]}]))
            gate = Mock(return_value={'green': True})
            result = run_file_agent(model, '', {}, FileTools(root, ['a.ts']), gate,
                None, Mock(), 'edit')
            self.assertEqual(result['checks'], {'green': True})
            self.assertIn('value = 2', (root / 'a.ts').read_text())
            gate.assert_called_once()

    def test_unchanged_repairs_continue_until_real_checks_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Mock(generate_json=Mock(return_value={'tool_calls': []}))
            gate = Mock(side_effect=[*[ValueError('Business result missing') for _ in range(12)], {'green': True}])
            result = run_file_agent(model, '', {}, FileTools(Path(directory)), gate, None, Mock(), 'repair')
            self.assertEqual(result['turns'], 13)
            self.assertEqual(model.generate_json.call_count, 13)
            self.assertEqual(gate.call_count, 13)

    def test_actual_repair_after_noop_is_checked_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = Mock(generate_json=Mock(side_effect=[{'tool_calls': []}, {'tool_calls': []},
                {'tool_calls': [{'tool': 'edit_file', 'path': 'fix.ts',
                    'operation': 'create', 'new_content': 'export const fixed = true;'}]}]))
            gate = Mock(side_effect=[ValueError('Missing result'), ValueError('Missing result'), {'green': True}])
            run_file_agent(model, '', {}, FileTools(root, ['fix.ts']), gate, 3, Mock(), 'repair')
            self.assertEqual(gate.call_count, 3)

    def test_removed_environment_cap_does_not_stop_work(self):
        with patch.dict('os.environ', {'ARC_MAX_MODEL_CALLS': '1'}):
            model = Mock(generate_json=Mock(side_effect=[{}, {}, {'value': 'accepted'}]))
            result, _ = propose_json(model, '', {}, lambda value: value['value'], Mock(), 'schema')
            self.assertEqual(result, 'accepted')
            self.assertEqual(model.generate_json.call_count, 3)

    def test_transport_failure_does_not_launch_another_repair_request(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Mock(generate_json=Mock(side_effect=RuntimeError('Model transport unavailable')))
            gate = Mock()
            with self.assertRaisesRegex(RuntimeError, 'transport unavailable'):
                run_file_agent(model, '', {}, FileTools(Path(directory)), gate, 10, Mock(), 'request')
            self.assertEqual(model.generate_json.call_count, 1)
            gate.assert_not_called()

    def test_skipped_or_flaky_results_are_neither_compacted_nor_green(self):
        for kind in ('skipped', 'flaky', 'errors'):
            report = {'returncode': 0, 'passed': 1, kind: 1}
            with self.subTest(kind=kind):
                self.assertEqual(compact_feedback(report)[kind], 1)
                with self.assertRaises(ValueError):
                    require_green(report)
