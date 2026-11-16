from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
import yaml

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ModelResponse, ToolCall
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.requirements import RequirementCatalog


class RequirementCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = {'id': 'ROOT', 'name': 'Library', 'description': 'Keep ownership and persistence.',
            'scenarios': [{'id': 'PARENT', 'steps': [{'id': 'PARENT-STEP', 'Given': 'Two users',
                'When': 'Switch accounts', 'Then': 'Keep records separate'}]}],
            'children': [{'id': 'BOOKS', 'name': 'Books', 'description': {'text': 'Manage books',
                'image': [{'id': 'IMAGE', 'reference': 'reference.png'}]},
                'scenarios': [{'id': 'CREATE', 'steps': [
                    {'id': 'GIVEN', 'keyword': 'Given', 'content': 'No books'},
                    {'id': 'WHEN', 'keyword': 'When', 'content': 'Save a title'},
                    {'id': 'THEN', 'keyword': 'Then', 'content': 'Persist the title',
                        'references': [r'\ref[image](IMAGE)', r'\ref[requirement](ROOT)']}]}]}]}
        Image.new('RGB', (30, 20), 'red').save(self.root / 'reference.png')

    def save(self, spec=None):
        text = yaml.safe_dump(self.spec if spec is None else spec, allow_unicode=True, sort_keys=False)
        (self.root / 'requirements.yaml').write_text(text, encoding='utf-8')
        return text

    def test_exact_text_parent_scenarios_keyword_ids_and_all_nodes_survive(self):
        text = self.save()
        catalog = RequirementCatalog(self.root)
        self.assertEqual(catalog.initial_context()['original_yaml'], text)
        result = catalog.read('WHEN')
        self.assertEqual(result['ancestor_requirements'][0]['scenarios'][0]['steps'][0]['id'], 'PARENT-STEP')
        self.assertEqual(result['requirement']['scenarios'][0]['steps'][1],
            self.spec['children'][0]['scenarios'][0]['steps'][1])
        self.assertEqual(catalog.catalog(limit=1)['next_offset'], 1)
        self.assertEqual(catalog.catalog(offset=1)['items'][0]['parent'], 'ROOT')
        self.assertIn('catalog', catalog.initial_context(max_chars=1))
        before = catalog.resource_data['IMAGE']
        (self.root / 'reference.png').write_bytes(b'changed')
        self.assertEqual(catalog.resource_data['IMAGE'], before)

    def test_one_image_shared_by_several_requirements_is_accepted(self):
        # Real inputs attach the same reference image, under the same id, to several requirements.
        spec = deepcopy(self.spec)
        spec['description'] = {'text': 'Keep ownership.', 'image': [{'id': 'IMAGE', 'reference': 'reference.png'}]}
        self.save(spec)
        catalog = RequirementCatalog(self.root)
        self.assertEqual(list(catalog.images), ['IMAGE'])
        self.assertEqual([row['resources'] for row in catalog.catalog()['items']], [['IMAGE'], ['IMAGE']])
        self.assertNotIn('input_notices', catalog.initial_context())
        # The same id on another file keeps both images reachable and tells the agent.
        Image.new('RGB', (30, 20), 'blue').save(self.root / 'other.png')
        spec['description']['image'][0]['reference'] = 'other.png'
        self.save(spec)
        catalog = RequirementCatalog(self.root)
        self.assertEqual(sorted(catalog.images), ['IMAGE', 'IMAGE@BOOKS'])
        self.assertNotEqual(catalog.resource_data['IMAGE'], catalog.resource_data['IMAGE@BOOKS'])
        self.assertIn('IMAGE@BOOKS', catalog.initial_context()['input_notices'][0])
        spec['children'][0]['description']['image'][0].pop('id')
        self.save(spec)
        with self.assertRaisesRegex(ValueError, 'Missing image id'):
            RequirementCatalog(self.root)

    def test_duplicate_ids_shapes_and_invalid_references_fail_before_model(self):
        mutations = [lambda s: s['children'][0].update(id='ROOT'),
            lambda s: s['children'][0]['scenarios'][0]['steps'][1].update(id='GIVEN'),
            lambda s: s['children'][0]['scenarios'][0]['steps'][2].update(references=[r'\ref[image](MISSING)']),
            lambda s: s['children'][0]['scenarios'][0]['steps'][2].update(references=[r'\ref[image]']),
            lambda s: s.update(children={}), lambda s: s.update(description=5),
            lambda s: s['children'][0]['description']['image'][0].update(reference='../secret.png'),
            lambda s: s['children'][0]['description']['image'][0].update(reference='missing.png')]
        for change in mutations:
            spec = deepcopy(self.spec)
            change(spec)
            self.save(spec)
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                RequirementCatalog(self.root)
        (self.root / 'requirements.yaml').write_text('id: A\nid: B\n')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            RequirementCatalog(self.root)


class RequirementSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_preserves_existing_files_and_context_only_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / 'input', root / 'app'
            source.mkdir()
            (source / 'requirements.yaml').write_text('id: ROOT\nname: Notes\ndescription: Persist notes\n')
            (output / 'frontend/src').mkdir(parents=True)
            (output / 'frontend/src/App.tsx').write_text('existing custom page')
            model = ScriptedModel([ModelResponse('First'), ModelResponse('Followup')])
            async with ApplicationAgent(output, input_dir=source, model=model, profile=load_profile(environment={})) as agent:
                self.assertFalse(model.requests)
                await agent.run()
                await agent.run('Keep the original navigation')
                self.assertEqual(sum('Original task context:' in m.content for m in agent.state.messages), 1)
                self.assertEqual((output / 'frontend/src/App.tsx').read_text(), 'existing custom page')
                self.assertTrue((output / 'deploy.sh').is_file())
                self.assertNotIn('Step 05', (output / 'backend/src/db/initialize.ts').read_text())
                self.assertIn('foreign_keys = ON', (output / 'backend/src/db/initialize.ts').read_text())
            with self.assertRaisesRegex(ValueError, 'disjoint'):
                ApplicationAgent(source / 'app', input_dir=source, model=ScriptedModel([]))

    async def test_images_are_only_requested_on_demand_and_fallback_usage_counts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input'
            source.mkdir()
            (source / 'requirements.yaml').write_text('id: R\ndescription:\n  image:\n    - id: I\n      reference: ref.png\n')
            Image.new('RGB', (10, 10), 'blue').save(source / 'ref.png')
            profile = replace(load_profile(environment={}), image_mode='fallback')
            model = ScriptedModel([ModelResponse('No image needed')])
            vision = ScriptedModel([ModelResponse('A blue rectangle')])
            async with ApplicationAgent(root / 'app', input_dir=source, model=model, profile=profile) as agent:
                agent.tools.vision_factory = lambda settings: vision
                await agent.run()
                self.assertEqual(len(vision.requests), 0)
                result = await agent.tools.execute(ToolCall('view', 'view_image', '{"identity":"I"}'))
                self.assertIsNone(result.error)
                self.assertEqual(result.value['description'], 'A blue rectangle')
                self.assertEqual(agent.state.requests, 2)
                self.assertEqual(agent.state.auxiliary_requests, 1)
                self.assertTrue(vision.closed)
                self.assertEqual(agent.catalog.viewed, {'I'})
                self.assertTrue(vision.requests[0][0][1].to_wire()['content'][1]['image_url']['url'].startswith('data:image/jpeg'))
