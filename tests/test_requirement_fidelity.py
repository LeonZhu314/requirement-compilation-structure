"""Preserve original shared UI constraints and both supported scenario formats."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
import unittest

from infrastructure.stages.requirements.normalize import normalize_requirements
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.backend.context import requirement_context
from infrastructure.stages.frontend.ui.testing import existence_suite
from test_frontend_flow import frontend_fixture


class RequirementFidelity(unittest.TestCase):
    def test_keyword_steps_and_page_references_are_normalized_without_losing_text(self):
        raw = {'id': 'ROOT', 'description': 'Shared controls', 'children': [{
            'id': 'REQ', 'description': 'Local contract',
            'pages': [{'name': 'home', 'reference': './reference/home.png'}],
            'scenarios': [{'name': 'Success', 'steps': [
                {'keyword': 'GIVEN', 'content': 'An existing account'},
                {'keyword': 'WHEN', 'content': 'Submit'},
                {'keyword': 'THEN', 'content': 'Saved'},
                {'keyword': 'AND', 'content': 'Still saved after refresh'}]}]}]}
        before = deepcopy(raw)
        normalized = normalize_requirements(raw)
        self.assertEqual(raw, before)
        self.assertEqual(normalize_requirements(normalized), normalized)
        tree = RequirementTree(raw)
        step = tree.steps[tree.own_steps['REQ'][0]]
        self.assertEqual(step['Given'], 'An existing account')
        self.assertEqual(step['When'], 'Submit')
        self.assertEqual(step['Then'], 'Saved\nStill saved after refresh')
        self.assertEqual(import_module('01_explore_requirement').collect_images(normalized),
            ['./reference/home.png'])

    def test_leaf_context_inherits_only_ancestor_descriptions_and_no_sibling_workflow(self):
        root = {'id': 'ROOT', 'description': 'Shared role/name contract', 'children': [
            {'id': 'FOLDER', 'description': 'Shared regional constraint', 'children': [
                {'id': 'REQ', 'description': 'Current action'}]},
            {'id': 'OTHER', 'description': 'Unrelated secret workflow'}]}
        task = requirement_context(RequirementTree(root), 'REQ')
        self.assertEqual([parent['id'] for parent in task['ancestor_requirements']], ['ROOT', 'FOLDER'])
        self.assertNotIn('Unrelated secret workflow', str(task))
        self.assertEqual(task['steps'], [])

    def test_presence_checks_validate_only_explicit_original_roles_and_names(self):
        _, _, ui, _, _, _ = frontend_fixture()
        for node in ui['elements'].values():
            node['data'] = [{'var': name, **ui['bindings'][name]} for name in node['data']]
        ui['elements']['UI-TEXT']['prop']['label'] = '* Note:'
        suite = existence_suite(ui, 'editor', [{'description': 'Use "Note"(role=textbox).'}])
        self.assertIn('toHaveRole("textbox")', suite)
        self.assertIn('toHaveAccessibleName("Note")', suite)
        self.assertNotIn('toHaveAccessibleName("Save")', suite)
        self.assertNotIn('toHaveRole', existence_suite(ui, 'editor'))
        ui['elements']['UI-TEXT']['type'] = 'text'
        self.assertNotIn('toHaveRole', existence_suite(ui, 'editor',
            [{'description': 'Use "Note"(role=textbox).'}]))

    def test_supplied_submit_requirements_can_be_parsed_with_shared_navigation_and_images(self):
        path = Path(__file__).resolve().parents[1] / 'c636a90b00e8-template/template/requirements/requirements.yaml'
        if not path.is_file():
            self.skipTest('Optional submit evidence is not part of the repository')
        raw = import_module('01_explore_requirement').load_requirements(path)
        tree = RequirementTree(raw)
        self.assertEqual(tree.leaves, ['REQ-1', 'REQ-2'])
        self.assertEqual(len(import_module('01_explore_requirement').collect_images(raw)), 2)
        self.assertTrue(tree.steps[tree.own_steps['REQ-2'][0]]['Then'])
        self.assertIn('Cookie Statement', str(requirement_context(tree, 'REQ-2')['ancestor_requirements']))
