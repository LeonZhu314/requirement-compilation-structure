"""A richer application skeleton: building blocks, a resolved lockfile, and the agent told about them."""

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.dependencies import DependencyManager
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.messages import ModelResponse
from infrastructure.shared.project.initialize import initialize_project
from tests.verification_support import make_agent

TEMPLATES = Path(__file__).resolve().parents[1] / 'infrastructure/shared/project/templates'
BLOCKS = ('backend/src/lib/http.ts', 'backend/src/lib/password.ts', 'backend/src/lib/session.ts',
    'frontend/src/lib/api.ts', 'frontend/src/lib/router.tsx', 'frontend/src/lib/form.tsx', 'frontend/src/lib/layout.tsx')


class TemplateTests(unittest.TestCase):
    def test_new_workspaces_get_the_blocks_lockfile_and_guide_without_overwriting_user_files(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / 'backend/src/lib').mkdir(parents=True)
            (workspace / 'backend/src/lib/session.ts').write_text('// my own sessions\n')
            created = initialize_project(workspace)
            for path in (*BLOCKS, 'package-lock.json', 'BUILDING_BLOCKS.md'):
                self.assertTrue((workspace / path).is_file(), path)
            self.assertNotIn('backend/src/lib/session.ts', created)
            self.assertEqual((workspace / 'backend/src/lib/session.ts').read_text(), '// my own sessions\n')
            self.assertIn('app.use(apiErrors)', (workspace / 'backend/src/app.ts').read_text())

    def test_the_lockfile_matches_every_manifest_and_has_linux_and_windows_binaries(self):
        lock = json.loads((TEMPLATES / 'package-lock.json').read_text(encoding='utf-8'))
        packages = lock['packages']
        self.assertEqual(lock['lockfileVersion'], 3)
        for manifest_path, key in (('package.json', ''), ('backend/package.json', 'backend'), ('frontend/package.json', 'frontend')):
            manifest = json.loads((TEMPLATES / manifest_path).read_text(encoding='utf-8'))
            locked = packages[key]
            for section in ('dependencies', 'devDependencies'):
                self.assertEqual(locked.get(section, {}), manifest.get(section, {}), f'{manifest_path} {section}')
        for name, version in (('express', '5.1.0'), ('better-sqlite3', '12.2.0'), ('react', '18.3.1'), ('vite', '7.1.4')):
            self.assertEqual(packages[f'node_modules/{name}']['version'], version)
        for binary in ('@esbuild/linux-x64', '@esbuild/win32-x64', '@rollup/rollup-linux-x64-gnu',
                '@rollup/rollup-win32-x64-msvc', 'lightningcss-linux-x64-gnu'):
            self.assertIn(f'node_modules/{binary}', packages)
        hosts = {re.match(r'https://([^/]+)/', entry['resolved']).group(1) for entry in packages.values() if entry.get('resolved') and not entry.get('link')}
        self.assertEqual(hosts, {'registry.npmjs.org'})

    def test_the_guide_names_only_exports_that_exist(self):
        guide = (TEMPLATES / 'BUILDING_BLOCKS.md').read_text(encoding='utf-8')
        sources = ''.join((TEMPLATES / path).read_text(encoding='utf-8') for path in BLOCKS)
        exported = set(re.findall(r'export (?:const|function|class|type|interface) (\w+)', sources))
        for name in ('HttpError', 'badRequest', 'unauthorized', 'conflict', 'apiErrors', 'text', 'hashPassword',
                'verifyPassword', 'createSessions', 'sessionTableSql', 'api', 'ApiError', 'useResource', 'errorMessage',
                'Routes', 'Link', 'navigate', 'TextField', 'SelectField', 'RadioGroup', 'Checkbox', 'FormError',
                'SubmitButton', 'Layout'):
            self.assertIn(name, exported)
            self.assertIn(name, guide)
        self.assertLess(len(guide), 8000)               # Sent whole in the first message.
        # The only alert of a form is FormError: field messages must not compete with it.
        form = (TEMPLATES / 'frontend/src/lib/form.tsx').read_text(encoding='utf-8')
        self.assertEqual(form.count('role="alert"'), 1)


class AgentGuideTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_first_message_carries_the_guide_and_the_instructions_point_to_it(self):
        with TemporaryDirectory() as tmp:
            model = ScriptedModel([ModelResponse('Done.')])
            agent, _, _ = make_agent(Path(tmp), model)
            async with agent:
                await agent.run()
                first = [m.content for m in model.requests[0][0] if m.role == 'user'][0]
                system = model.requests[0][0][0].content
            self.assertIn('Workspace building blocks (BUILDING_BLOCKS.md)', first)
            self.assertIn('createSessions(connection)', first)
            self.assertLess(first.index('building blocks'), first.index('Original task context'))
            self.assertIn('Workspace building blocks', system)


class DependencyFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_npm_ci_falls_back_to_install_only_when_the_lockfile_is_out_of_sync(self):
        with TemporaryDirectory() as tmp:
            agent, _, _ = make_agent(Path(tmp), ScriptedModel([]))
            manager, commands, outputs = agent.tools.dependencies, [], []
            manager.toolchain = {'node': 'v22', 'npm': '10'}

            async def run(command, timeout=None, env=None):
                commands.append(command[:2])
                text, code = outputs.pop(0)
                return {'status': 'completed' if code == 0 else 'failed', 'returncode': code,
                    'artifact': agent.tools.artifacts.put(text), 'content': text}

            async def check():
                return 'host'
            manager.processes.run, manager.processes.sandbox.check = run, check
            async with agent:
                outputs[:] = [('npm error `npm ci` can only install packages when your package.json and '
                    'package-lock.json are in sync.\nnpm error Missing: dayjs@1.11.0 from lock file', 1), ('added 1', 0)]
                self.assertEqual((await DependencyManager.install(manager))['operation'], 'install')
                self.assertEqual(commands, [['npm', 'ci'], ['npm', 'install']])
                # Any other failure is reported as it is, without a second attempt.
                commands.clear()
                (agent.state.workspace / 'package.json').write_text('{"name": "changed"}')
                outputs[:] = [('npm error code E404', 1)]
                self.assertEqual((await DependencyManager.install(manager))['status'], 'installation_failed')
                self.assertEqual(commands, [['npm', 'ci']])


if __name__ == '__main__':
    unittest.main()
