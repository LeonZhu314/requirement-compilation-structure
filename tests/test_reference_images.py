"""Reference images given to the agent, visual differences fed back once, real pages captured."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ModelResponse
from infrastructure.runtime.model import ProviderError, ScriptedModel
from infrastructure.verification.verifier import HostVerifier
from tests.verification_support import call, make_agent


def source_with_image(root):
    source = root / 'input'
    source.mkdir()
    (source / 'requirements.yaml').write_text('id: R\ndescription:\n  image:\n    - id: HOME\n      reference: home.png\n'
        '      page: home\n')
    Image.new('RGB', (1600, 900), 'blue').save(source / 'home.png')
    return source


class AttachedReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_images_follow_the_task_in_their_own_message_and_are_reduced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_profile(environment={}).reference_images, 'describe')   # Off since v1.17.
            profile = replace(load_profile(environment={}), image_mode='fallback', reference_images='attach')
            model = ScriptedModel([ModelResponse('Done.')])
            async with ApplicationAgent(root / 'app', input_dir=source_with_image(root), model=model, profile=profile) as agent:
                agent.tools.vision_factory = lambda settings: ScriptedModel([ModelResponse('A blue page')])
                await agent.run()
                sent = model.requests[0][0]
            task, images = sent[1], sent[2]
            self.assertFalse(task.images)                                   # The task survives compaction.
            self.assertIn('Original task context', task.content)
            self.assertIn('HOME (page home)', images.content)
            self.assertEqual(len(images.images), 1)
            with Image.open(images.images[0].path) as picture:
                self.assertLessEqual(max(picture.size), 1280)
            self.assertTrue(images.to_wire()['content'][1]['image_url']['url'].startswith('data:image/jpeg'))

    async def test_a_provider_that_refuses_images_gets_the_task_without_them(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = replace(load_profile(environment={}), image_mode='fallback', reference_images='attach')

            def refuse(messages, schemas):
                if any(m.images for m in messages):
                    raise ProviderError('image input is not supported')
                return ModelResponse('Done.')

            class Picky(ScriptedModel):
                async def respond(self, messages, schemas):
                    self.requests.append((messages, schemas))
                    return refuse(messages, schemas)
            model = Picky([])
            async with ApplicationAgent(root / 'app', input_dir=source_with_image(root), model=model, profile=profile) as agent:
                agent.tools.vision_factory = lambda settings: ScriptedModel([ModelResponse('A blue page')])
                result = await agent.run()
                self.assertEqual(result.status, 'proposed')
                self.assertFalse(any(m.images for m in agent.state.messages))
                self.assertIn('HOME', [m.content for m in agent.state.messages if m.role == 'user'][0])   # Descriptions stay.


class VisualFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_differences_are_returned_once_before_the_turn_can_end(self):
        with TemporaryDirectory() as tmp:
            only_a = None
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False, finish_on_pass=True,
                visual_feedback=True)
            async with agent:
                agent.verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                agent.tools.acceptance_runner = agent.acceptance_now
                asked = []

                async def verify(*, clean_state, visual=False):
                    asked.append(visual)
                    return {'status': 'candidate', 'stage': 'visual' if visual else 'acceptance', 'fingerprint': 'f',
                        'coverage': {'functional': {'passed': 3}, 'omissions': []},
                        **({'visual': {'IMG-HOME': {'status': 'divergent', 'path': '/',
                            'differences': ['Left sidebar with Shelves is missing', 'Search bar is not centered']},
                            'IMG-DELETE': {'status': 'missing_interface'}}} if visual else {})}
                agent.verifier.verify = verify
                first = (await agent.tools.execute(call('run_acceptance_tests'))).value
                self.assertIn('Left sidebar with Shelves is missing', first['report'])
                self.assertIn('IMG-DELETE: no page declared', first['report'])
                self.assertFalse(agent.tools.finish_requested)              # The agent gets the chance to fix them.
                second = (await agent.tools.execute(call('run_acceptance_tests'))).value
                self.assertEqual(asked, [True, False])                     # Visual review only once.
                self.assertTrue(agent.tools.finish_requested)
                self.assertIn('host now ends your work turn', second['report'])
                self.assertIsNone(only_a)


class ParametrizedPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_route_pattern_is_captured_on_a_real_linked_page(self):
        with TemporaryDirectory() as tmp:
            agent, tooling, _ = make_agent(Path(tmp), ScriptedModel([]), generate=False)
            async with agent:
                verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                    agent.input_dir, tooling=tooling)
                pages = {'/': ['/books', '/about'], '/books': ['/books/create', '/books/7', '/books/7/edit', 'http://x/books/8']}

                class Page:
                    current = '/'

                    async def eval_on_selector_all(self, selector, script):
                        return pages.get(self.current, [])

                class Browser:
                    page = Page()

                    async def action(self, action, url):
                        self.page.current = url[len(verifier.base_url):]
                browser = Browser()
                self.assertEqual(await verifier._resolve(browser, '/books', []), '/books')
                self.assertEqual(await verifier._resolve(browser, '/books/:id', ['/books', '/books/:id']), '/books/7')
                self.assertEqual(await verifier._resolve(browser, '/books/:id/edit', ['/books']), '/books/7/edit')
                self.assertIsNone(await verifier._resolve(browser, '/pages/:id', ['/books']))


if __name__ == '__main__':
    unittest.main()
