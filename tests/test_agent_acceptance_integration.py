"""Real acceptance path: host Playwright runner, real browser, real HTTP server.

Opt-in (AGENTASE_TEST_ACCEPTANCE=1): the first run installs @playwright/test from npm.
The application is a dependency-free Node server; a deliberately wrong business rule
(duplicate usernames accepted) must be detected by the supplied external test.
"""

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.execution import ProcessManager
from infrastructure.runtime.model import ScriptedModel
from infrastructure.verification.acceptance import PlaywrightTooling
from infrastructure.verification.verifier import HostVerifier
from tests.verification_support import make_agent

SERVER = '''const http = require("http");
const users = new Set(["taken"]);
const ACCEPT_DUPLICATES = __MUTATION__;
const page = `<!doctype html><html><body><h1>Accounts</h1>
<label>Username<input aria-label="Username"></label><button>Register</button><p role="status"></p>
<script>
const status = document.querySelector("[role=status]");
const saved = sessionStorage.getItem("user"); if (saved) status.textContent = "Signed in as " + saved;
document.querySelector("button").onclick = async () => {
  const username = document.querySelector("input").value;
  const response = await fetch("/api/register", { method: "POST", body: JSON.stringify({ username }) });
  if (response.ok) { sessionStorage.setItem("user", username); status.textContent = "Signed in as " + username; }
  else { const alert = document.createElement("p"); alert.setAttribute("role", "alert"); alert.textContent = "Username already exists"; document.body.append(alert); }
};
</script></body></html>`;
http.createServer((request, response) => {
  if (request.method === "POST" && request.url === "/api/register") {
    let body = ""; request.on("data", chunk => body += chunk); request.on("end", () => {
      const { username } = JSON.parse(body);
      if (users.has(username) && !ACCEPT_DUPLICATES) { response.writeHead(409); return response.end("{}"); }
      users.add(username); response.writeHead(201); response.end("{}");
    });
  } else { response.writeHead(200, { "Content-Type": "text/html" }); response.end(page); }
}).listen(Number(process.env.PORT), "127.0.0.1");
'''
SPEC = '''// requirement: REQ-A
import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
test('SCN-A-1: register and stay signed in after refresh', async ({ page }) => {
  const name = 'user-' + randomUUID().slice(0, 8);
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Username', exact: true }).fill(name);
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Signed in as ' + name);
  await page.reload();
  await expect(page.getByRole('status')).toHaveText('Signed in as ' + name);
});
test('SCN-A-2: reject an existing username without a session', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Username', exact: true }).fill('taken');
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('status')).toHaveText('');
});
'''
WRAPPER = ('import json, os, subprocess, sys\n'
    'os.environ.update(json.loads(sys.argv[1]))\n'
    'sys.exit(subprocess.call(sys.argv[2:]))\n')


class HostProcessSandbox:
    """Test-only: run the fixture server as a host process with its configured variables."""
    backend = 'test-fixture'

    async def check(self):
        return {'backend': self.backend}

    def argv(self, command, name, ports=(), env=None):
        return [sys.executable, '-c', WRAPPER, json.dumps(env or {}), shutil.which(command[0]) or command[0], *command[1:]]

    async def remove(self, name):
        pass


@unittest.skipUnless(os.getenv('AGENTASE_TEST_ACCEPTANCE') and shutil.which('node'),
    'Set AGENTASE_TEST_ACCEPTANCE=1 (needs Node, npm registry access and Chromium)')
class RealAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_test_detects_a_wrong_business_rule_in_the_real_application(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent, _, _ = make_agent(root, ScriptedModel([]), generate=False)
            agent.profile = replace(agent.profile, execution=replace(agent.profile.execution, verification_port=port))
            processes = agent.tools.processes
            processes.settings = agent.profile.execution
            processes.sandbox = HostProcessSandbox()
            # Build and dependency stages are stand-ins; server start, HTTP readiness,
            # test execution and the browser are real.
            processes.start = ProcessManager.start.__get__(processes)
            processes.logs = ProcessManager.logs.__get__(processes)
            (root / 'input/tests/REQ-A.spec.ts').write_text(SPEC, encoding='utf-8')
            cache = Path(os.getenv('AGENTASE_ACCEPTANCE_TOOLING') or root / 'tooling')
            verifier = HostVerifier(agent.tools, agent.profile, agent.state, agent.loop.budget, agent.loop.model,
                agent.input_dir, tooling=PlaywrightTooling(cache))
            verifier.start_command = ['node', 'server.cjs']
            workspace = agent.state.workspace
            try:
                (workspace / 'server.cjs').write_text(SERVER.replace('__MUTATION__', 'true'))
                report = await verifier.verify(clean_state=True)
                self.assertEqual((report['status'], report['stage']), ('failed', 'acceptance'), report)
                self.assertEqual([f['covers'] for f in report['failures']], [['SCN-A-2']])
                self.assertIn('alert', ' '.join(report['failures'][0]['errors']))
                self.assertNotIn("fill('taken')", json.dumps(report))        # No test source in the evidence.
                self.assertEqual(agent.tools.coverage.entries['SCN-A-1']['functional'], 'passed')
                (workspace / 'server.cjs').write_text(SERVER.replace('__MUTATION__', 'false'))
                report = await verifier.verify(clean_state=True)
                self.assertTrue(report['accepted'], report)
                self.assertEqual(agent.tools.coverage.entries['SCN-A-2']['functional'], 'passed')
                self.assertFalse(list(workspace.rglob('*.spec.ts')))          # Tests never enter the workspace.
            finally:
                await agent.aclose()


if __name__ == '__main__':
    unittest.main()
