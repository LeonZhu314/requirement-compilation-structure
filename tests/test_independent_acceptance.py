"""Independent tests cannot be rewritten by the application repair task."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import yaml

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.stages.frontend.triggers.acceptance import run_independent_acceptance, acceptance_path
from test_frontend_flow import frontend_fixture
from contextlib import ExitStack


class IndependentAcceptance(unittest.TestCase):
    def checks(self, root, behavior):
        stack = self.enterContext(ExitStack())
        checks = Mock()
        checks.typecheck.return_value = {'returncode': 0}
        checks.build.return_value = {'returncode': 0}
        checks.tests.side_effect = behavior
        for name in ('E2EChecks', 'FrontendChecks', 'BackendChecks'):
            stack.enter_context(patch('infrastructure.stages.frontend.triggers.acceptance.' + name,
                return_value=checks))
        return checks

    def setup_workspace(self, root):
        raw, tree, ui, triggers, backend, _ = frontend_fixture()
        input_dir = root / 'input'
        input_dir.mkdir()
        (input_dir / 'requirements.yaml').write_text(yaml.safe_dump(raw))
        return input_dir, ui, triggers, backend

    def test_real_behavior_failure_survives_separate_review_and_later_requirements_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir, ui, triggers, backend = self.setup_workspace(root)
            requests = []
            def generate(prompt, payload):
                requests.append(payload)
                task = payload['task']
                if 'application_entrypoints' in task:
                    self.assertFalse(payload['files'][task['test_path']]['writable'])
                    return {'tool_calls': []}
                self.assertEqual([path for path, value in payload['files'].items() if value['writable']], [task['test_path']])
                self.assertNotIn('file', payload['context_kinds'])
                self.assertNotIn('triggers', task)
                if payload['feedback']:
                    return {'tool_calls': [], 'diagnosis': {'cause': 'implementation', 'reason': 'Required result is missing'}}
                return {'tool_calls': [{'tool': 'edit_file', 'path': task['test_path'], 'operation': 'create',
                    'new_content': 'original requirement assertions'}]}
            failure = {'returncode': 1, 'passed': 0, 'failed': 1, 'failures': ['wrong account']}
            green = {'returncode': 0, 'passed': 1, 'failed': 0}
            checks = self.checks(root, lambda files: failure if acceptance_path('REQ-A') in files else green)
            with patch('infrastructure.stages.frontend.triggers.acceptance.E2EChecks', return_value=checks):
                result = run_independent_acceptance(input_dir, root / '.arc', {'entities': {}}, backend, ui,
                    triggers, Mock(generate_json=generate), Mock(), max_turns=1,
                    process_report={'requirements': {}, 'verification': {}})
            self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
            self.assertEqual(result['requirements']['REQ-A']['status'], 'FAILED')
            self.assertEqual(result['requirements']['REQ-C']['status'], 'GREEN', result)
            self.assertEqual((root / acceptance_path('REQ-A')).read_text(), 'original requirement assertions')
            self.assertEqual(len(requests), 5)

    def test_wrong_test_can_be_corrected_only_by_review_task_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir, ui, triggers, backend = self.setup_workspace(root)
            failure = {'returncode': 1, 'passed': 0, 'failed': 1, 'failures': ['invalid selector']}
            green = {'returncode': 0, 'passed': 1, 'failed': 0}
            checks = self.checks(root, lambda files: failure if any('initial selector' in (root / path).read_text()
                for path in files) else green)
            def generate(prompt, payload):
                corrected = bool(payload['feedback'])
                path = payload['task']['test_path']
                if corrected:
                    return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'replace',
                        'old_content': 'initial selector', 'new_content': 'correct selector'}],
                        'diagnosis': {'cause': 'test_overconstraint', 'reason': 'Selector contradicts original label'}}
                return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'create',
                    'new_content': '// original assertions\ninitial selector'}]}
            with patch('infrastructure.stages.frontend.triggers.acceptance.E2EChecks', return_value=checks):
                report = run_independent_acceptance(input_dir, root / '.arc', {'entities': {}}, backend, ui,
                    triggers, Mock(generate_json=generate), Mock(),
                    process_report={'requirements': {}, 'verification': {}})
            self.assertEqual(report['status'], 'GREEN', report)
            path = acceptance_path('REQ-A')
            workspace = SourceFiles(root).workspace(references=[path])
            self.assertFalse(workspace.state()[path]['writable'])
            SourceFiles(root).include(workspace, [path])
            self.assertFalse(workspace.state()[path]['writable'])
            self.assertIn('test_overconstraint', (root / '.arc/test_repairs.jsonl').read_text())
            self.assertIn('initial selector', (root / '.arc/test_repairs.jsonl').read_text())
