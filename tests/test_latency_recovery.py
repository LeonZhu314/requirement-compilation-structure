"""Correct the logged test-ownership loop and avoid resending redundant UI context."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.tools.files import FileToolError
from infrastructure.stages.frontend.triggers import acceptance
from infrastructure.stages.frontend.triggers.scope import model_context
from test_frontend_flow import frontend_fixture


class LatencyRecovery(unittest.TestCase):
    def test_denied_test_write_is_reviewed_by_its_owner_and_checks_can_finish_without_another_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = acceptance.acceptance_path('REQ')
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text('// original business assertions\npartial selector\n')
            workspace = FileTools(root, references=[path])
            calls = []

            def review(selected, evidence):
                calls.append((selected, evidence))
                self.assertEqual(selected, path)
                self.assertFalse(workspace.can_write(selected))
                owner = acceptance.acceptance_workspace(root, 'REQ')
                owner.execute([{'tool': 'edit_file', 'path': path, 'operation': 'replace',
                    'old_content': 'partial selector', 'new_content': 'exact selector'}])
                return True

            model = Mock(generate_json=Mock(return_value={'tool_calls': [
                {'tool': 'edit_file', 'path': path, 'operation': 'replace',
                    'old_content': 'partial selector', 'new_content': 'exact selector'}]}))

            def gate():
                self.assertIn('exact selector', target.read_text())
                self.assertIn('original business assertions', target.read_text())
                return {'green': True}

            result = run_file_agent(model, '', {}, workspace, gate, None, Mock(), 'Implementation',
                feedback={'returncode': 1, 'failures': ['strict mode violation: Name matches Username']}, test_review=review)
            self.assertEqual(result['checks'], {'green': True})
            self.assertEqual(model.generate_json.call_count, 1)
            self.assertEqual(len(calls), 1)
            self.assertFalse(workspace.can_write(path))

    def test_review_that_retains_assertions_routes_next_edit_to_the_application(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = acceptance.acceptance_path('REQ')
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text('// required assertions\nkeep expected outcome\n')
            requests = []

            def generate(_, payload):
                requests.append(deepcopy(payload))
                if len(requests) == 1:
                    return {'tool_calls': [{'tool': 'edit_file', 'path': path, 'operation': 'replace',
                        'old_content': 'required assertions', 'new_content': 'weakened assertions'}]}
                self.assertIn('Repair the application', str(payload['feedback']))
                self.assertNotIn('previous_response', payload['feedback'][-1])
                return {'tool_calls': [{'tool': 'edit_file', 'path': 'frontend/src/fix.ts',
                    'operation': 'create', 'new_content': 'export const fixed = true;'}]}

            review = Mock(return_value=False)
            run_file_agent(Mock(generate_json=generate), '', {}, FileTools(root, ['frontend/src/fix.ts'], [path]),
                Mock(return_value={}), None, Mock(), 'Implementation', test_review=review)
            self.assertIn('required assertions', target.read_text())
            self.assertTrue((root / 'frontend/src/fix.ts').is_file())
            review.assert_called_once()

    def test_implementation_context_omits_unrelated_decorative_nodes_without_losing_trigger_contracts(self):
        _, _, ui, triggers, backend, _ = frontend_fixture()
        from infrastructure.stages.frontend.triggers.implementation import scenario_context
        context = scenario_context(ui, triggers, 'REQ-A')
        context.update(backend_apis=backend['apis'], target_trigger_ids=['TR-INPUT', 'TR-SAVE'],
            obligations={tid: {} for tid in context['triggers']})
        for i in range(100):
            context['page_subtrees']['editor']['elements'][f'decoration-{i}'] = {
                'type': 'text', 'parent': 'UI-EDITOR', 'prop': {'text': 'Decoration ' * 100},
                'data': [{'var': f'decoration.{i}', 'dtype': 'string', 'constraints': []}]}
        full = model_context(context)
        compact = model_context(context, implementation=True)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)) / 5)
        self.assertEqual(compact['triggers'], full['triggers'])
        self.assertEqual(compact['backend_apis'], full['backend_apis'])
        self.assertEqual(compact['page_subtrees']['summary']['route'], '/summary')
        self.assertNotIn('decoration-0', compact['page_subtrees']['editor']['elements'])

    def test_reading_a_pinned_file_does_not_duplicate_its_contents_in_the_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = 'frontend/src/current.ts'
            (root / path).parent.mkdir(parents=True)
            (root / path).write_text('export const value = 1;\n')
            seen = []

            def generate(_, payload):
                seen.append(deepcopy(payload))
                return {'tool_calls': [{'tool': 'read_file', 'path': path}]} if len(seen) == 1 else {'tool_calls': []}

            run_file_agent(Mock(generate_json=generate), '', {}, FileTools(root, [path]),
                Mock(return_value={}), None, Mock(), 'Read')
            self.assertEqual(seen[1]['files'][path]['content'], 'export const value = 1;\n')
            self.assertNotIn('read_files', seen[1])

    def test_repeated_identical_test_review_reuses_its_verdict_but_new_evidence_is_reviewed(self):
        _, tree, ui, design, backend, _ = frontend_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / acceptance.acceptance_path('REQ-A')
            path.parent.mkdir(parents=True)
            path.write_text('// original assertion\nkeep this\n')
            checks = Mock()
            checks.typecheck.return_value = {'returncode': 0}
            model = Mock(generate_json=Mock(return_value={'tool_calls': []}))
            reviewed = set()
            with patch.object(acceptance, 'E2EChecks', return_value=checks):
                for failure in ('strict mode violation: same failure', 'strict mode violation: same failure', 'Different test mismatch'):
                    changed = acceptance.review_acceptance_suite(tree, root, {'entities': {}}, backend,
                        ui, design, 'REQ-A', model, Mock(), None,
                        {'returncode': 1, 'failures': [failure]}, reviewed)
                    self.assertFalse(changed)
            self.assertEqual(model.generate_json.call_count, 2)
            self.assertIn('original assertion', path.read_text())


class ExactLocatorParser(unittest.TestCase):
    def test_logged_home_name_and_password_ambiguities_are_corrected_without_model_calls_or_assertion_changes(self):
        root = Path(__file__).resolve().parents[1]
        projects = (root / 'outputs/acceptance-permissions-integration', root / 'outputs/demo')
        project = next((path for path in projects if (path / 'node_modules/typescript/lib/typescript.js').is_file()), None)
        node = shutil.which('node')
        if project is None or node is None:
            self.skipTest('Node.js and installed generated-project TypeScript are required for parser integration')
        directory = project / 'frontend/tests/e2e/acceptance'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='locator-regression-', dir=directory) as temporary:
            path = Path(temporary) / 'case.spec.ts'
            source = '''// Original business expectation must stay unchanged.
page.getByRole('link', {name: 'HOME'});
page.getByRole('textbox', {name: 'Name',});
page.getByRole('radio', {name: 'Male', exact: false});
page.getByRole('link', {name: /HOME/});
page.getByRole('button');
page.getByLabel('Password');
page.getByLabel('Confirm Password', {exact: true});
expect(result).toEqual({created: true, username: 'required-user'});
'''
            path.write_bytes(source.encode())
            script = root / 'infrastructure/stages/frontend/triggers/exact_locators.mjs'
            contracts = {'roles': [['HOME', 'link'], ['Name', 'textbox'], ['Male', 'radio']],
                'labels': ['Password', 'Confirm Password']}
            command = [node, str(script), str(project), path.relative_to(project).as_posix(), json.dumps(contracts)]
            first = subprocess.run(command, text=True, capture_output=True, timeout=15, encoding='utf-8')
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)['edits'], 3)
            changed = path.read_text()
            self.assertIn("{name: 'HOME', exact: true}", changed)
            self.assertIn("{name: 'Name', exact: true,}", changed)
            self.assertIn("getByLabel('Password', { exact: true })", changed)
            self.assertIn("{name: 'Male', exact: false}", changed)
            self.assertIn("{name: /HOME/}", changed)
            self.assertIn("expect(result).toEqual({created: true, username: 'required-user'});", changed)
            second = subprocess.run(command, text=True, capture_output=True, timeout=15, encoding='utf-8')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)['changed'])
