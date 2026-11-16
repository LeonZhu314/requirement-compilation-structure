"""Interface contract: roles and names stated in requirements, used by the agent and the host tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from infrastructure.requirements.contract import extract, locator
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.requirements import RequirementCatalog
from infrastructure.verification.acceptance import AUTHOR, CONFIG
from tests.verification_support import make_agent

SPEC = {'id': 'ROOT', 'name': 'Library', 'description': 'Organize items.', 'children': [
    {'id': 'REQ-1', 'name': 'Browse', 'description': {'text': 'Clicking "Items"(role=link) displays '
        '"Item list"(role=region). Each item is a keyboard-accessible "{item name}"(role=button).'},
     'scenarios': [{'id': 'SCN-1', 'steps': [{'id': 'S1', 'Given': 'Items exist', 'When': 'Open Items',
         'Then': 'Exactly one entry per item in Item list.'}]}],
     'children': [{'id': 'REQ-1.1', 'name': 'Delete', 'description': {'text': 'Clicking "Delete"(role=button) '
         'opens confirmation; Confirm returns to the list and removes the entry from Entry list (region).'},
         'scenarios': [{'id': 'SCN-2', 'steps': [{'id': 'S2', 'Given': 'g', 'When': 'w', 'Then': 't'}]}]}]}]}


class ContractTests(unittest.TestCase):
    def test_roles_and_names_are_extracted_exactly_and_nothing_else(self):
        self.assertEqual(extract('Clicking "Books"(role=link) shows “Book list” (role = region) and Page list (region).'),
            [('link', 'Books'), ('region', 'Book list'), ('region', 'Page list')])
        self.assertEqual(extract('Display Register links (see REQ-2) and items (sorted).'), [])
        self.assertEqual(locator({'role': 'region', 'name': 'Book list'}),
            "getByRole('region', { name: 'Book list', exact: true })")
        self.assertIn("<the item's own name>", locator({'role': 'button', 'name': '{item name}', 'pattern': True}))

    def test_the_agent_and_the_test_generator_receive_the_contract_with_ancestor_constraints(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.yaml').write_text(yaml.safe_dump(SPEC, sort_keys=False), encoding='utf-8')
            catalog = RequirementCatalog(root)
            context = catalog.initial_context()['interface_contract']
            self.assertEqual(context['locators']['REQ-1'], ["getByRole('link', { name: 'Items', exact: true })",
                "getByRole('region', { name: 'Item list', exact: true })",
                "getByRole('button', { name: <the item's own name>, exact: true })"])
            self.assertIn("getByRole('region', { name: 'Entry list', exact: true })", context['locators']['REQ-1.1'])
            inherited = catalog.contract_for('REQ-1.1')
            self.assertEqual([entry['requirement'] for entry in inherited], ['REQ-1'] * 3 + ['REQ-1.1'] * 2)
            self.assertNotIn('interface_contract', RequirementCatalog.__new__(RequirementCatalog).__dict__)

    def test_generated_tests_use_the_locators_and_run_like_the_benchmark(self):
        self.assertIn('required_locators', AUTHOR)
        self.assertIn('shared database', AUTHOR)
        self.assertIn('ACCEPTANCE_WORKERS', CONFIG)


class ContractSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_host_runs_acceptance_with_the_profile_workers_and_the_task_lists_locators(self):
        with TemporaryDirectory() as tmp:
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), requirements=SPEC, workers=3, generate=False)
            async with agent:
                from infrastructure.verification.verifier import HostVerifier
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                verifier.suite.assemble()
                task = verifier.suite.task('REQ-1.1', ['SCN-2'], {})
                self.assertIn("getByRole('button', { name: 'Delete', exact: true })", task['required_locators'])
                self.assertIn("getByRole('region', { name: 'Item list', exact: true })", task['required_locators'])
                await verifier._run([])
                self.assertEqual(tooling.workers, 3)
        from infrastructure.runtime.config import load_profile
        self.assertEqual(load_profile(environment={}).acceptance.workers, 3)
        workflow = load_profile(environment={}).workflow
        for rule in ('interface_contract', 'Never paginate', 'whatever page', 'never add special cases'):
            self.assertIn(rule, workflow)


if __name__ == '__main__':
    unittest.main()
