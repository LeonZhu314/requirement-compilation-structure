import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infrastructure.runtime.artifacts import ArtifactStore
from infrastructure.runtime.dependencies import DependencyManager
from infrastructure.runtime.execution import (EnvironmentUnavailable, ExecutionMirror, ExecutionSettings,
    ProcessManager, Sandbox, clean_environment)


class ExecutionIsolationTests(unittest.TestCase):
    def test_shell_mirror_cannot_publish_protected_tests_secrets_or_links(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app'
            (app / 'tests').mkdir(parents=True)
            (app / 'tests/external.py').write_text('assert original')
            (app / '.env').write_text('OPENAI_API_KEY=private')
            (app / 'app.ts').write_text('original')
            mirror = ExecutionMirror(app, root / 'host-state')
            mirror.push()
            self.assertFalse((mirror.root / '.env').exists())
            (mirror.root / 'tests/external.py').write_text('assert weakened')
            (mirror.root / 'app.ts').write_text('fixed')
            (mirror.root / 'requirements.yaml').write_text('fabricated')
            (mirror.root / '.env').write_text('injected')
            os.link(app / 'tests/external.py', mirror.root / 'alias.py')
            mirror.pull()
            self.assertEqual((app / 'tests/external.py').read_text(), 'assert original')
            self.assertEqual((app / '.env').read_text(), 'OPENAI_API_KEY=private')
            self.assertFalse((app / 'requirements.yaml').exists())
            self.assertFalse((app / 'alias.py').exists())
            self.assertEqual((app / 'app.ts').read_text(), 'fixed')

    def test_concurrent_source_edits_are_not_silently_overwritten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app'
            app.mkdir()
            (app / 'file.ts').write_text('base')
            mirror = ExecutionMirror(app, root / 'state')
            mirror.push()
            (app / 'file.ts').write_text('user edit')
            (mirror.root / 'file.ts').write_text('shell edit')
            with self.assertRaisesRegex(ValueError, 'Concurrent'):
                mirror.pull()
            self.assertEqual((app / 'file.ts').read_text(), 'user edit')

    def test_docker_and_linux_launchers_mount_only_mirror_and_readonly_test_copies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app'
            app.mkdir()
            mirror = ExecutionMirror(app, root / 'state')
            mirror.push()
            sandbox = Sandbox(mirror, ExecutionSettings(backend='docker', network=False), root / 'state')
            with patch.object(sandbox, 'executable', return_value='docker'):
                argv = sandbox.argv(['node', '-e', 'process.exit(0)'], 'agentase-test')
                self.assertIn('--read-only', argv)
                self.assertIn('--cap-drop=ALL', argv)
                self.assertIn('none', argv)
                self.assertTrue(any('target=/workspace/tests,readonly' in a for a in argv))
                self.assertFalse(any(f'source={app},' in a for a in argv))
                self.assertFalse(any('OPENAI_API_KEY' in a for a in argv))
                with self.assertRaises(ValueError):
                    sandbox.argv(['node'], 'test', ports=[3000])
            sandbox.backend = 'bubblewrap'
            with patch.object(sandbox, 'executable', return_value='bwrap'):
                argv = sandbox.argv(['node', '--version'], 'unused')
                self.assertIn('--unshare-net', argv)
                self.assertIn('--clearenv', argv)
                self.assertIn('--disable-userns', argv)
                self.assertNotIn(str(app), argv)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret', 'NODE_OPTIONS': '--require secret.js'}):
                env = clean_environment()
                self.assertNotIn('OPENAI_API_KEY', env)
                self.assertNotIn('NODE_OPTIONS', env)


class TrustedFixtureSandbox:
    """Test-only injection for known Python fixtures; never selectable by a profile."""
    backend = 'test-fixture'
    async def check(self):
        return {'backend': self.backend, 'version': 1}
    def argv(self, command, name, ports=(), env=None):
        return command
    async def remove(self, name):
        pass


class ProcessLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        app = self.root / 'app'
        app.mkdir()
        state = self.root / 'state'
        self.manager = ProcessManager(app, state, ExecutionSettings(), ArtifactStore(state))
        self.manager.sandbox = TrustedFixtureSandbox()

    async def asyncTearDown(self):
        await self.manager.aclose()
        self.tmp.cleanup()

    async def test_real_process_output_sources_timeout_and_reuse(self):
        code = "from pathlib import Path; Path('module.ts').write_text('created'); print('observed')"
        result = await self.manager.run([sys.executable, '-c', code], timeout=5)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('observed', result['content'])
        self.assertEqual((self.manager.mirror.workspace / 'module.ts').read_text(), 'created')
        command = [sys.executable, '-c', 'import time; time.sleep(120)']
        await self.manager.start('service', command, ports=[3000])
        pid = self.manager.processes['service']['process'].pid
        await self.manager.start('service', command, ports=[3000])
        self.assertEqual(self.manager.processes['service']['process'].pid, pid)
        (self.manager.mirror.workspace / 'module.ts').write_text('changed')
        self.assertTrue(self.manager.status('service')['source_changed_since_start'])
        await self.manager.start('service', command, ports=[3000], restart=True)
        self.assertNotEqual(self.manager.processes['service']['process'].pid, pid)
        timeout = await self.manager.run(command, timeout=1)
        self.assertEqual(timeout['status'], 'timed_out')

    async def test_cancellation_kills_owned_command_and_does_not_leak_parent_credentials(self):
        result = await self.manager.run([sys.executable, '-c', "import os; print(os.getenv('OPENAI_API_KEY','missing'))"], timeout=5)
        self.assertEqual(result['content'].strip(), 'missing')
        task = asyncio.create_task(self.manager.run([sys.executable, '-c', 'import time; time.sleep(120)']))
        while len(self.manager.processes) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(entry['process'].poll() is not None for entry in self.manager.processes.values()))

    async def test_missing_sandbox_fails_before_any_command_runs(self):
        self.manager.sandbox = Sandbox(self.manager.mirror, ExecutionSettings(backend='docker'), self.root / 'state')
        with patch('infrastructure.runtime.execution.shutil.which', return_value=None):
            with self.assertRaises(EnvironmentUnavailable):
                await self.manager.run([sys.executable, '-c', "open('unconfined','w').write('bad')"])
        self.assertFalse((self.manager.mirror.workspace / 'unconfined').exists())


class DependencyCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_lockfile_install_reuse_manifest_and_missing_package_invalidation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app'
            app.mkdir()
            (app / 'package.json').write_text('{"name":"fixture"}')
            state = root / 'state'
            manager = ProcessManager(app, state, ExecutionSettings(), ArtifactStore(state))
            manager.sandbox = TrustedFixtureSandbox()
            calls = []
            async def run(command, **kwargs):
                calls.append(command)
                if command[0] == 'node' or command == ['npm', '--version']:
                    return {'status': 'completed', 'returncode': 0, 'content': 'fixture-version'}
                (manager.mirror.root / 'node_modules/pkg').mkdir(parents=True, exist_ok=True)
                (manager.mirror.root / 'node_modules/.package-lock.json').write_text('{"packages":{"node_modules/pkg":{}}}')
                (manager.mirror.root / 'package-lock.json').write_text('{"lockfileVersion":3}')
                manager.mirror.pull()
                return {'status': 'completed', 'returncode': 0, 'content': ''}
            manager.run = run
            manager.mirror.push()
            dependencies = DependencyManager(manager, state)
            self.assertEqual((await dependencies.install())['operation'], 'install')
            (app / 'source.ts').write_text('application change')
            self.assertEqual((await dependencies.install())['status'], 'reused')
            (app / 'package.json').write_text('{"name":"changed"}')
            self.assertEqual((await dependencies.install())['operation'], 'ci')
            (manager.mirror.root / 'node_modules/pkg').rmdir()
            self.assertEqual((await dependencies.install())['operation'], 'ci')
            self.assertEqual(sum(c[0:2] in [['npm', 'ci'], ['npm', 'install']] for c in calls), 3)
