"""Real OS isolation, opt-in because Docker/namespace support is host dependent."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.artifacts import ArtifactStore
from infrastructure.runtime.execution import ExecutionSettings, ProcessManager


@unittest.skipUnless(os.getenv('AGENTASE_TEST_SANDBOX'), 'Set AGENTASE_TEST_SANDBOX=docker or bubblewrap for real isolation tests')
class RealSandboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_cannot_modify_original_acceptance_or_read_host_secret(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app'
            (app / 'tests').mkdir(parents=True)
            (app / 'tests/acceptance.js').write_text('original acceptance')
            (app / '.env').write_text('PRIVATE_VALUE=do-not-copy')
            outside = root / 'outside-secret.txt'
            outside.write_text('host-only')
            settings = ExecutionSettings(backend=os.environ['AGENTASE_TEST_SANDBOX'], network=False,
                docker_image=os.getenv('AGENTASE_TEST_IMAGE', 'node:22-bookworm'))
            manager = ProcessManager(app, root / 'state', settings, ArtifactStore(root / 'state'))
            try:
                code = '''const fs=require('fs'); const denied=[];
                for(const path of ['tests/acceptance.js','/outside-secret.txt']) {
                  try { fs.writeFileSync(path,'bad'); } catch(e) { denied.push(path); }
                }
                if(denied.length!==2 || fs.existsSync('.env') || process.env.OPENAI_API_KEY) process.exit(9);
                fs.writeFileSync('implemented.js','console.log("ready")'); console.log('isolated');'''
                result = await manager.run(['node', '-e', code], timeout=30)
                self.assertEqual(result['returncode'], 0, result)
                self.assertIn('isolated', result['content'])
                self.assertEqual((app / 'tests/acceptance.js').read_text(), 'original acceptance')
                self.assertEqual(outside.read_text(), 'host-only')
                self.assertTrue((app / 'implemented.js').exists())
                task = asyncio.create_task(manager.run(['node', '-e', 'setInterval(()=>{},1000)'], timeout=30))
                while len(manager.processes) < 2:
                    await asyncio.sleep(0.05)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(all(e['process'].poll() is not None for e in manager.processes.values()))
            finally:
                await manager.aclose()
