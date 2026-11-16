"""Offline fixtures for host verification: a simulated application and test runner.

The simulated application is a text file listing the behaviors it implements. A
scripted agent "repairs" it with ordinary file tools, and the fake runner decides
each test from that file, so the driver, registry and budget are exercised with
real sessions and real file effects but without npm, Docker or a browser.
"""

from dataclasses import replace
import json
from pathlib import Path
import re

import yaml

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.messages import ModelResponse, ToolCall
from infrastructure.verification.results import FAILED, PASSED

REQUIREMENTS = {'id': 'ROOT', 'name': 'Accounts', 'description': 'Accounts keep their own data.',
    'children': [
        {'id': 'REQ-A', 'name': 'Register', 'description': 'Register with a unique username.',
            'scenarios': [
                {'id': 'SCN-A-1', 'steps': [{'id': 'ST-A-1', 'Given': 'A new username',
                    'When': 'Register', 'Then': 'Show the username and remain signed in after a page refresh'}]},
                {'id': 'SCN-A-2', 'steps': [{'id': 'ST-A-2', 'Given': 'The username taken already exists',
                    'When': 'Register with taken', 'Then': 'Reject the registration without creating a session'}]}]},
        {'id': 'REQ-B', 'name': 'Profile', 'description': 'Show the profile.',
            'scenarios': [{'id': 'SCN-B-1', 'steps': [{'id': 'ST-B-1', 'Given': 'Two distinct accounts',
                'When': 'Open the profile as the second account', 'Then': 'Show the second account only'}]}]}]}

EXTERNAL = '''// requirement: REQ-A
import { expect, test } from '@playwright/test';
test('SCN-A-1: register and stay signed in', async ({ page }) => { await page.goto('/'); });
test('SCN-A-2: reject an existing username', async ({ page }) => { await page.goto('/'); });
'''
GENERATED = '''```ts
import { test, expect } from '@playwright/test';
test('SCN-B-1: the second account sees only its profile', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('second')).toBeVisible();
});
```'''


def call(name, identity='c', **arguments):
    return ToolCall(identity, name, json.dumps(arguments))


def tools(*calls):
    return ModelResponse(tool_calls=tuple(calls), finish_reason='tool_calls')


def write_input(root, *, external=True, requirements=None):
    source = root / 'input'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'requirements.yaml').write_text(yaml.safe_dump(requirements or REQUIREMENTS, sort_keys=False), encoding='utf-8')
    if external:
        (source / 'tests').mkdir(exist_ok=True)
        (source / 'tests/REQ-A.spec.ts').write_text(EXTERNAL, encoding='utf-8')
    return source


class FakeTooling:
    """Stands for the host Playwright runner: a test passes when the simulated
    application lists the scenario id of its title in app/behaviors.txt."""

    def __init__(self, root, workspace):
        self.root, self.workspace = Path(root), Path(workspace)
        self.runs, self.compiles, self.ensured = [], [], 0
        self.environment_error = None
        self.compile_error = None

    async def ensure(self):
        from infrastructure.runtime.execution import EnvironmentUnavailable
        self.ensured += 1
        if self.environment_error:
            raise EnvironmentUnavailable(self.environment_error)

    def behaviors(self):
        path = self.workspace / 'behaviors.txt'
        return set(path.read_text(encoding='utf-8').split()) if path.is_file() else set()

    async def run(self, suite, files, base_url, timeout, test_timeout=30, list_only=False, workers=1):
        self.workers = workers
        if list_only:
            self.compiles.append(list(files))
            return {'status': FAILED if self.compile_error else PASSED, 'returncode': 1 if self.compile_error else 0,
                'tests': [], 'errors': [self.compile_error] if self.compile_error else [], 'passed': 0, 'failed': 0,
                'skipped': 0, 'flaky': 0}
        self.runs.append(sorted(files))
        implemented, results = self.behaviors(), []
        for relative in sorted(files):
            text = (Path(suite) / relative).read_text(encoding='utf-8')
            for title in re.findall(r"test\('([^']+)'", text):
                scenario = title.split(':')[0]
                ok = scenario in implemented
                results.append({'file': relative, 'title': title, 'status': PASSED if ok else FAILED, 'duration_ms': 5,
                    'errors': [] if ok else [f"expect(locator).toBeVisible() failed for {scenario}: element not found"]})
        failed = sum(test['status'] == FAILED for test in results)
        return {'status': FAILED if failed else PASSED, 'returncode': 1 if failed else 0, 'tests': results, 'errors': [],
            'passed': len(results) - failed, 'failed': failed, 'skipped': 0, 'flaky': 0, 'output_tail': ''}


def simulate_runtime(agent):
    """Replace sandboxed commands with deterministic stand-ins keyed on workspace files."""
    processes, mirror = agent.tools.processes, agent.tools.processes.mirror
    log = {'commands': [], 'starts': [], 'installs': 0, 'resets': 0}

    async def run(command, timeout=None, env=None):
        mirror.pull()
        mirror.push()
        log['commands'].append(command)
        broken = (mirror.root / 'BUILD_BROKEN').is_file() and command[:3] == ['npm', 'run', 'build']
        text = 'error TS2322: broken build' if broken else 'ok'
        if 'test:backend' in command or 'backend/scripts/test-api.mjs' in command:
            text = '\n'.join(('# tests 2', '# pass 2', '# fail 0', '# skipped 0', '# todo 0', ''))
        return {'status': 'failed' if broken else 'completed', 'returncode': 1 if broken else 0,
            'artifact': agent.tools.artifacts.put(text), 'content': text, 'accepted': False}

    async def start(name, command, ports=(), env=None, restart=False, ready_timeout=0, host=False):
        mirror.pull()
        mirror.push()
        log['starts'].append({'name': name, 'env': dict(env or {}), 'host': host, 'generation': mirror.generation})
        return {'name': name, 'running': True, 'ready': not (mirror.root / 'START_BROKEN').is_file()}

    def logs(name, offset=0, limit=12000):
        return {'artifact': agent.tools.artifacts.put('server log'), 'content': 'Error: listen failed'}

    async def install():
        log['installs'] += 1
        return {'status': 'reused'}

    async def fingerprint():
        return 'fixed-toolchain'

    reset = mirror.reset

    def counted_reset(keep=('node_modules', '.npm-cache')):
        log['resets'] += 1
        return reset(keep)

    processes.run, processes.start, processes.logs = run, start, logs
    mirror.reset = counted_reset
    agent.tools.dependencies.install, agent.tools.dependencies.fingerprint = install, fingerprint
    return log


def profile(**changes):
    base = load_profile(environment={})
    acceptance = {key: changes.pop(key) for key in list(changes) if key in vars(base.acceptance)}
    budget = {key: changes.pop(key) for key in list(changes) if key in vars(base.budget)}
    return replace(base, acceptance=replace(base.acceptance, **{'visual': 'off', **acceptance}),
        budget=replace(base.budget, **budget), **changes)


def make_agent(root, model, *, external=True, requirements=None, **changes):
    source = write_input(root, external=external, requirements=requirements)
    agent = ApplicationAgent(root / 'app', input_dir=source, model=model, profile=profile(**changes))
    tooling = FakeTooling(root / 'tooling', root / 'app')
    return agent, tooling, simulate_runtime(agent)
