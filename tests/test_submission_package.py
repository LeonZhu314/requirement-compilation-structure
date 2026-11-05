"""Submit the actual working tree with a complete pip manifest and no local secrets."""

from io import StringIO
from pathlib import Path
import tempfile
import tomllib
import unittest
import zipfile

from dotenv import dotenv_values
from scripts.package import package_arcbench


class SubmissionPackage(unittest.TestCase):
    def fixture(self, root):
        dependencies = ['PyYAML', 'playwright>=1.64.1']
        root.joinpath('pyproject.toml').write_text('[project]\ndependencies = ["PyYAML", "playwright>=1.64.1"]\n')
        root.joinpath('requirements.txt').write_text('\n'.join(dependencies) + '\n')
        for relative in ('main.py', '01_explore_requirement.py', '12_implement_frontend_tdd.py',
                'infrastructure/stages/requirements/visuals.py',
                'infrastructure/stages/frontend/triggers/exact_locators.mjs',
                'infrastructure/shared/project/templates/frontend/src/App.tsx', 'uv.lock'):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('' if path.suffix == '.py' else 'fixture')
        root.joinpath('.env.example').write_text('MODEL=example\nOPENAI_API_KEY=\n')
        root.joinpath('.env').write_text('MODEL=current-model\nVISUAL_MODEL=current-vision\n'
            'OPENAI_API_KEY=private-main-key\nVISUAL_API_KEY=private-visual-key\n')

    def test_arcbench_pip_dependencies_match_the_project(self):
        root = Path(__file__).resolve().parents[1]
        declared = set(tomllib.loads((root / 'pyproject.toml').read_text())['project']['dependencies'])
        installed = {line.strip() for line in (root / 'requirements.txt').read_text().splitlines()
            if line.strip() and not line.startswith('#')}
        self.assertEqual(declared, installed)
        self.assertIn('playwright>=1.64.1', installed)

    def test_archive_keeps_untracked_source_changes_but_not_keys_or_generated_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            root.joinpath('infrastructure/current.py').write_text('CURRENT_VERSION = True\n')
            root.joinpath('outputs').mkdir()
            root.joinpath('outputs/private.log').write_text('private runtime logs')
            archive_path = root / 'outputs/submission.zip'
            count = package_arcbench(root, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(count, len(archive.namelist()))
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('infrastructure/current.py'), root.joinpath('infrastructure/current.py').read_bytes())
                self.assertFalse(any(name.startswith('outputs/') for name in archive.namelist()))
                settings = dotenv_values(stream=StringIO(archive.read('.env').decode()))
                self.assertEqual(settings['MODEL'], 'current-model')
                self.assertEqual(settings['VISUAL_MODEL'], 'current-vision')
                self.assertEqual(settings['OPENAI_API_KEY'], '')
                content = b''.join(archive.read(name) for name in archive.namelist())
                self.assertNotIn(b'private-main-key', content)
                self.assertNotIn(b'private-visual-key', content)

    def test_incomplete_pip_manifest_fails_before_creating_an_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            root.joinpath('requirements.txt').write_text('PyYAML\n')
            archive = root / 'submission.zip'
            with self.assertRaisesRegex(ValueError, 'missing from pip manifest'):
                package_arcbench(root, archive)
            self.assertFalse(archive.exists())
