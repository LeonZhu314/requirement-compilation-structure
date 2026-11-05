"""One independent test oracle drives implementation and is reused in final acceptance."""

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from infrastructure.shared.agent.tools.files import FileToolError
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.frontend.triggers import implementation
from infrastructure.stages.frontend.triggers import acceptance
from test_frontend_flow import frontend_fixture


GREEN = {'returncode': 0, 'passed': 1, 'failed': 0, 'output': 'passed'}


class AcceptanceTDD(unittest.TestCase):
    def test_generation_has_no_application_access_and_is_reused(self):
        _, tree, ui, triggers, backend, _ = frontend_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0}
            seen = []

            def generate(_, payload):
                seen.append(deepcopy(payload))
                task = payload['task']
                self.assertIn('original_requirement', task)
                self.assertNotIn('triggers', task)
                self.assertNotIn('file', payload['context_kinds'])
                self.assertEqual([path for path, value in payload['files'].items() if value['writable']],
                    [task['test_path']])
                return {'tool_calls': [{'tool': 'edit_file', 'operation': 'create',
                    'path': task['test_path'], 'new_content': '// independent original assertions'}]}

            model = Mock(generate_json=generate)
            with patch.object(acceptance, 'E2EChecks', return_value=checks):
                first = acceptance.prepare_acceptance_suite(tree, root, {'entities': {}}, backend,
                    ui, triggers, 'REQ-A', model, Mock(), 2)
                second = acceptance.prepare_acceptance_suite(tree, root, {'entities': {}}, backend,
                    ui, triggers, 'REQ-A', model, Mock(), 2)
            self.assertEqual(first, second)
            self.assertEqual(len(seen), 1)
            checks.tests.assert_not_called()
            with self.assertRaises(FileToolError):
                acceptance.acceptance_workspace(root, 'REQ-A').execute([
                    {'tool': 'read_file', 'path': 'frontend/src/App.tsx'}])

    def test_implementation_uses_independent_suites_without_second_test_generator(self):
        self.check_implementation()

    def test_failed_implementation_preserves_the_original_oracle_and_later_tasks_run(self):
        self.check_implementation(failing_first=True)

    def test_ambiguous_test_is_reviewed_during_implementation_without_another_application_round(self):
        self.check_implementation(ambiguous_test=True)

    def check_implementation(self, failing_first=False, ambiguous_test=False):
        _, tree, ui, triggers, backend, _ = frontend_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_project(root)
            for aid, api in backend['apis'].items():
                api['signature'] = {'name': aid, 'method': 'GET', 'path': '/api/' + aid}
            prepared, requests, reviewed = {}, [], []

            def prepare(rid):
                path = acceptance.acceptance_path(rid)
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('// original requirement: ' + rid
                    + ('\npartial selector' if ambiguous_test and rid == 'REQ-A' else ''))
                prepared[path] = rid
                return path

            def tests(files):
                source = root / 'frontend/src/workflows.ts'
                content = source.read_text() if source.is_file() else ''
                missing = [path for path in files if prepared.get(path, '') not in content
                    or (failing_first and prepared.get(path) == 'REQ-A')]
                if missing:
                    return {**GREEN, 'returncode': 1, 'passed': 0, 'failed': 1,
                        'failures': [missing[0] + ': original business outcome missing']}
                if ambiguous_test:
                    invalid = [path for path in files if 'partial selector' in (root / path).read_text()]
                    if invalid:
                        return {**GREEN, 'returncode': 1, 'passed': 0, 'failed': 1,
                            'failures': [invalid[0] + ': strict mode violation: Name also matches Username']}
                return dict(GREEN)

            def review(path, evidence):
                reviewed.append(path)
                acceptance.acceptance_workspace(root, 'REQ-A').execute([
                    {'tool': 'edit_file', 'path': path, 'operation': 'replace',
                        'old_content': 'partial selector', 'new_content': 'exact selector'}])
                return True

            def generate(_, payload):
                requests.append(deepcopy(payload))
                self.assertNotIn('file_target', payload['task'])
                rid = payload['task']['requirement']['id']
                path = acceptance.acceptance_path(rid)
                self.assertFalse(payload['files'][path]['writable'])
                target = root / 'frontend/src/workflows.ts'
                return {'tool_calls': [{'tool': 'edit_file', 'path': 'frontend/src/workflows.ts',
                    'operation': 'append' if target.is_file() else 'create', 'new_content': '\n// ' + rid}]}

            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0, 'output': 'compiled'}
            checks.tests.side_effect = tests
            checks.build.return_value = {'returncode': 0, 'output': 'built'}
            backend_checks = Mock()
            backend_checks.typecheck.return_value = {'returncode': 0}
            backend_checks.tests.return_value = {'returncode': 0}
            with patch.object(implementation, 'install_dependencies'), \
                    patch.object(implementation, 'E2EChecks', return_value=checks), \
                    patch.object(implementation, 'FrontendChecks', return_value=checks), \
                    patch.object(implementation, 'BackendChecks', return_value=backend_checks):
                report = implementation.run_trigger_tdd(root / '.arc', tree, {'entities': {}}, backend,
                    ui, triggers, {}, {rid: {'id': rid} for rid in tree.leaves},
                    Mock(generate_json=generate), Mock(), {'requirements': {}}, 2,
                    acceptance_prepare=prepare, acceptance_review=review if ambiguous_test else None)
            self.assertEqual(report['status'], 'COMPLETED_WITH_FAILURES' if failing_first else 'GREEN')
            self.assertEqual(len(requests), 4 if failing_first else 3)
            if ambiguous_test:
                self.assertEqual(reviewed, [acceptance.acceptance_path('REQ-A')])
            self.assertEqual(report['requirements']['REQ-B']['status'], 'GREEN')
            self.assertEqual(report['requirements']['REQ-C']['status'], 'GREEN')
            self.assertIn('TR-COUNT', requests[0]['task']['triggers'])
            self.assertEqual(requests[0]['task']['target_trigger_ids'], ['TR-INPUT', 'TR-SAVE'])
            self.assertEqual(checks.tests.call_args.args[0], [acceptance.acceptance_path(rid) for rid in tree.leaves])
            for rid in tree.leaves:
                self.assertEqual(report['requirements'][rid]['test_path'], acceptance.acceptance_path(rid))
                self.assertEqual((root / acceptance.acceptance_path(rid)).read_text(), '// original requirement: ' + rid
                    + ('\nexact selector' if ambiguous_test and rid == 'REQ-A' else ''))
