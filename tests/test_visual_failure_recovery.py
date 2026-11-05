"""Reproduce the submit's vision proxy failure without blocking frontend generation."""

from contextlib import redirect_stdout, redirect_stderr, nullcontext
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

import main
from infrastructure.compiler import Compiler
from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.stages.requirements.visuals import analyze_references
from infrastructure.utils.presentation.console import DemoConsole


PROXY_FAILURE = RuntimeError('Visual model request failed: Error code: 400 - '
    'model_proxy_error: upstream read: connection reset by peer')


class VisualFailureRecovery(unittest.TestCase):
    def workspace(self, root):
        source = root / 'input'
        source.mkdir()
        (source / 'reference').mkdir()
        for name in ('home', 'register'):
            (source / f'reference/{name}.png').write_bytes(b'image input handled by fake provider')
        raw = {'id': 'ROOT', 'description': 'Shared navigation contract', 'children': [
            {'id': 'HOME', 'name': 'Home', 'description': 'Render "Register"(role=link) on /.',
                'pages': [{'name': 'home', 'reference': 'reference/home.png'}]},
            {'id': 'REGISTER', 'name': 'Registration', 'description': 'Render "Name"(role=textbox) on /register.',
                'pages': [{'name': 'register', 'reference': 'reference/register.png'}]}]}
        (source / 'requirements.yaml').write_text(yaml.safe_dump(raw), encoding='utf-8')
        return source, root / 'application/.arc'

    def test_proxy_reset_is_recorded_and_later_images_and_ui_design_still_run(self):
        stage = import_module('01_explore_requirement')
        with tempfile.TemporaryDirectory() as directory:
            source, arc = self.workspace(Path(directory))
            model = Mock()
            model.analyze.side_effect = [PROXY_FAILURE, {'layout': 'Registration form', 'elements': ['Name'], 'style': 'Light'}]
            with patch.object(stage, 'VisualModel', return_value=model), \
                    patch.object(stage, 'checkpoint'), patch('infrastructure.stages.requirements.visuals.checkpoint'), \
                    redirect_stdout(StringIO()):
                result = stage.explore_requirement(source, arc)
            self.assertEqual(result['status'], 'DEGRADED')
            self.assertEqual(model.analyze.call_count, 2)
            analysis = json.loads((arc / 'visual_analysis.json').read_text())
            self.assertEqual(analysis['reference/home.png']['status'], 'UNAVAILABLE')
            self.assertEqual(analysis['reference/home.png']['elements'], [])
            self.assertEqual(analysis['reference/register.png']['elements'], ['Name'])
            self.assertNotIn('status', json.loads((arc / 'requirements.json').read_text()))
            tree, images, contexts = load_ui_context(arc, source)
            self.assertEqual(contexts['HOME']['images']['IMG-HOME-01']['analysis']['status'], 'UNAVAILABLE')
            self.assertIn('Shared navigation contract', str(contexts['HOME']['ancestor_requirements']))
            calls = []

            def generate(_, request):
                rid = request['requirement']['id']
                calls.append(rid)
                page = 'home' if rid == 'HOME' else 'register'
                image = 'IMG-' + rid + '-01'
                root_id = 'UI-' + rid
                return {'pages': {page: {'name': page, 'route': '/' if page == 'home' else '/register',
                    'root': root_id, 'images': [image]}},
                    'elements': {root_id: {'type': 'page', 'parent': None, 'mode': [], 'data': [], 'prop': {}}},
                    'requirement_ui': [root_id], 'step_ui': {}}

            with patch('infrastructure.shared.agent.proposals.checkpoint'):
                design = synthesize_ui(arc, tree, images, contexts, Mock(generate_json=generate), Mock())
            self.assertEqual(calls, ['HOME', 'REGISTER'])
            self.assertEqual(set(design['pages']), {'home', 'register'})

    def test_provider_initialization_failure_publishes_all_unavailable_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('infrastructure.stages.requirements.visuals.checkpoint'), redirect_stdout(StringIO()):
                analysis, report = analyze_references(root, root / '.arc', ['one.png', 'two.png'],
                    Mock(side_effect=ValueError('Image provider is unavailable')), DemoConsole())
            self.assertEqual(report['status'], 'DEGRADED')
            self.assertEqual(set(report['failures']), {'one.png', 'two.png'})
            self.assertTrue(all(item['status'] == 'UNAVAILABLE' for item in analysis.values()))
            self.assertTrue((root / '.arc/visual_analysis.json').is_file())

    def test_interrupt_is_not_converted_to_degraded_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(KeyboardInterrupt):
                analyze_references(root, root / '.arc', ['image.png'],
                    Mock(return_value=Mock(analyze=Mock(side_effect=KeyboardInterrupt()))), Mock())
            self.assertEqual(json.loads((root / '.arc/visual_analysis_report.json').read_text())['status'], 'RUNNING')

    def test_frontend_can_resume_when_older_submit_has_no_visual_artifact(self):
        stage = import_module('01_explore_requirement')
        with tempfile.TemporaryDirectory() as directory:
            source, arc = self.workspace(Path(directory))
            arc.mkdir(parents=True)
            raw = stage.load_requirements(source / 'requirements.yaml')
            (arc / 'requirements.json').write_text(json.dumps(raw), encoding='utf-8')
            tree, images, contexts = load_ui_context(arc, source)
            self.assertEqual(tree.leaves, ['HOME', 'REGISTER'])
            self.assertEqual(len(images), 2)
            self.assertEqual(contexts['HOME']['images']['IMG-HOME-01']['analysis']['status'], 'UNAVAILABLE')
            (source / 'reference/home.png').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing input image'):
                load_ui_context(arc, source)

    def test_pipeline_keeps_degraded_status_after_other_passes_succeed(self):
        from test_compiler import PASSES
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = Compiler(root / 'input', root / 'output')
            calls = []

            def load(module):
                function = next(function for name, function in PASSES if name == module)

                def run(*args, **kwargs):
                    calls.append(module)
                    return {'status': 'DEGRADED' if module == '01_explore_requirement' else 'GREEN'}

                return SimpleNamespace(**{function: run})

            with patch('infrastructure.compiler.import_module', side_effect=load), \
                    patch('infrastructure.compiler.checkpoint'), \
                    patch('infrastructure.compiler.console_log', return_value=nullcontext()), redirect_stdout(StringIO()):
                compiler.compile()
            self.assertEqual(len(calls), 13)
            self.assertEqual(compiler.report['status'], 'DEGRADED')
            self.assertEqual(compiler.report['stages']['12_implement_frontend_tdd']['status'], 'GREEN')

    def test_cli_does_not_report_failed_acceptance_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('requirements.yaml').write_text('id: ROOT\n')
            for status in ('COMPLETED_WITH_FAILURES', 'FAILED'):
                compiler = Mock(report={'status': status}, arc_dir=root / '.arc')
                with self.subTest(status=status), patch.object(main, 'Compiler', return_value=compiler), \
                        redirect_stderr(StringIO()), self.assertRaises(SystemExit) as failure:
                    main.main([str(root), '-o', str(root.parent / (root.name + '-output'))])
                self.assertEqual(failure.exception.code, 1)
