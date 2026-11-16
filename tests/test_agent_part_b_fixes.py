"""Regression tests for delivery B: verification status and browser cleanup."""

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.browser import LoopbackProxy
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ToolCall
from infrastructure.runtime.model import ScriptedModel

TEMPLATES = Path(__file__).resolve().parents[1] / 'infrastructure/shared/project/templates'


class ProxyShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_does_not_wait_forever_for_relayed_connections(self):
        async def idle(reader, writer):
            await reader.read()
            writer.close()
        upstream = await asyncio.start_server(idle, '127.0.0.1', 0)
        port = upstream.sockets[0].getsockname()[1]
        proxy = LoopbackProxy(lambda: {port})
        address = await proxy.start()
        reader, writer = await asyncio.open_connection('127.0.0.1', int(address.rsplit(':', 1)[1]))
        try:
            writer.write(b'\x05\x01\x00')
            await writer.drain()
            await reader.readexactly(2)
            writer.write(b'\x05\x01\x00\x01\x7f\x00\x00\x01' + port.to_bytes(2, 'big'))
            await writer.drain()
            self.assertEqual((await reader.readexactly(10))[1], 0)
            # The client keeps its relayed connection open while the session closes.
            await asyncio.wait_for(proxy.aclose(), 10)
            self.assertFalse(proxy.clients)
        finally:
            writer.close()
            upstream.close()


@unittest.skipUnless(shutil.which('node'), 'Node is required for the template runner')
class BackendRunnerTests(unittest.TestCase):
    def test_runner_reports_missing_checks_distinctly(self):
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / 'backend/scripts/test-api.mjs'
            script.parent.mkdir(parents=True)
            shutil.copy(TEMPLATES / 'backend/scripts/test-api.mjs', script)
            result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)
            self.assertIn('NO_API_TESTS:', result.stderr)
            self.assertIn('backend/checks', result.stderr)

    def test_development_checks_are_typechecked_with_backend_tests(self):
        config = json.loads((TEMPLATES / 'backend/tsconfig.test.json').read_text())
        self.assertIn('checks/**/*.ts', config['include'])


class ServiceReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_waits_for_http_response_and_reports_dead_service(self):
        from infrastructure.runtime.artifacts import ArtifactStore
        from infrastructure.runtime.execution import ExecutionSettings, ProcessManager
        from tests.test_agent_execution import TrustedFixtureSandbox
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app').mkdir()
            state = root / 'state'
            listener = await asyncio.start_server(lambda r, w: None, '127.0.0.1', 0)
            port = listener.sockets[0].getsockname()[1]
            listener.close()
            await listener.wait_closed()
            manager = ProcessManager(root / 'app', state, ExecutionSettings(allowed_ports=(port,)), ArtifactStore(state))
            manager.sandbox = TrustedFixtureSandbox()
            try:
                server = [sys.executable, '-c', 'import time, http.server, socketserver; time.sleep(1); '
                    f'socketserver.TCPServer(("127.0.0.1", {port}), http.server.SimpleHTTPRequestHandler).serve_forever()']
                status = await manager.start('web', server, ports=[port], ready_timeout=30)
                self.assertTrue(status['ready'], status)
                await manager.stop('web')
                dead = await manager.start('dead', [sys.executable, '-c', 'raise SystemExit(4)'],
                    ports=[port], ready_timeout=10)
                self.assertFalse(dead['ready'])
                self.assertIn('process_logs', dead['notice'])
            finally:
                await manager.aclose()


class VerificationStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_absent_backend_checks_are_missing_not_failed_or_passing(self):
        with TemporaryDirectory() as tmp:
            agent = ApplicationAgent(Path(tmp) / 'app', model=ScriptedModel([]), profile=load_profile(environment={}))
            try:
                artifacts = agent.tools.artifacts
                async def run(command, **kwargs):
                    identity = artifacts.put('npm error\nNO_API_TESTS: none found\n')
                    return {'status': 'failed', 'returncode': 1, 'artifact': identity,
                        'content': 'npm error', 'accepted': False}
                agent.tools.processes.run = run
                async def fingerprint():
                    return 'fixed-toolchain'
                agent.tools.dependencies.fingerprint = fingerprint
                result = await agent.tools.execute(ToolCall('c1', 'verify_application',
                    json.dumps({'kind': 'backend_tests'})))
                self.assertIsNone(result.error)
                self.assertEqual(result.value['status'], 'missing')
                self.assertEqual(agent.state.checks[-1]['status'], 'missing')
                self.assertFalse(agent.state.checks[-1]['accepted'])
            finally:
                await agent.aclose()


class MirrorSynchronizationTests(unittest.TestCase):
    def test_snapshot_reuse_never_misses_rewrites_and_deleted_sources_leave_the_mirror(self):
        import os
        import time
        from infrastructure.runtime.execution import ExecutionMirror
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / 'app'
            app.mkdir()
            (app / 'a.ts').write_text('one')
            (app / 'obsolete.ts').write_text('old')
            mirror = ExecutionMirror(app, Path(tmp) / 'state')
            mirror.push()
            first = mirror.snapshot(app)
            (app / 'a.ts').write_text('two')                 # Same size, written immediately after.
            self.assertNotEqual(mirror.snapshot(app)['a.ts'], first['a.ts'])
            old = time.time() - 60                           # A settled tree is served from the cache...
            for path in app.iterdir():
                os.utime(path, (old, old))
            settled = mirror.snapshot(app)
            self.assertEqual(mirror.snapshot(app), settled)
            self.assertIn(str(app), mirror._snapshots)
            (app / 'a.ts').write_text('six')                 # ...and any later rewrite is still seen.
            self.assertNotEqual(mirror.snapshot(app)['a.ts'], settled['a.ts'])
            (app / 'obsolete.ts').unlink()
            mirror.pull()
            mirror.push()
            self.assertFalse((mirror.root / 'obsolete.ts').exists())
            self.assertEqual((mirror.root / 'a.ts').read_text(), 'six')
