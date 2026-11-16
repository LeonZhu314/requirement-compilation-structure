"""One dependency installation per manifest/lock/toolchain combination."""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import sys

from .files import source_files


def present(path):
    """Entry exists, without following it: workspace links created inside a Linux
    container cannot be resolved (or even stat-ed) from a Windows host."""
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True  # Present but unreadable from this host.


class DependencyManager:
    def __init__(self, processes, directory):
        self.processes, self.directory = processes, directory
        self.stamp = directory / 'dependency-state.json'
        self.toolchain = None

    def manifests(self, root=None):
        root = root or self.processes.mirror.root
        return {p: sha256(f.read_bytes()).hexdigest() for p, f in source_files(root)
            if Path(p).name in {'package.json', 'package-lock.json', 'npm-shrinkwrap.json'}}

    async def fingerprint(self):
        identity = await self.processes.sandbox.check()
        if self.toolchain is None:
            result = await self.processes.run(['node', '-e',
                'console.log(JSON.stringify({node:process.version,abi:process.versions.modules,platform:process.platform,arch:process.arch}));'], timeout=30)
            if result['returncode'] or result['status'] != 'completed':
                raise RuntimeError('Node is unavailable in the configured sandbox: ' + result['content'])
            npm = await self.processes.run(['npm', '--version'], timeout=30)
            if npm['returncode'] or npm['status'] != 'completed':
                raise RuntimeError('npm is unavailable in the configured sandbox: ' + npm['content'])
            self.toolchain = {'node': result['content'].strip(), 'npm': npm['content'].strip()}
        return sha256(json.dumps({'manifests': self.manifests(), 'runtime': identity,
            'tools': self.toolchain, 'install': ['--include=dev', '--include=optional', '--no-audit', '--no-fund']},
            sort_keys=True).encode()).hexdigest()

    async def _out_of_sync(self, result):
        log = await _read_log(self.processes, result)
        return any(sign in log for sign in SYNC_ERRORS)

    def _declared(self):
        """package.json files as the agent wrote them (lockfiles are npm's own output)."""
        workspace = self.processes.mirror.workspace if hasattr(self.processes.mirror, 'workspace') else None
        return {path: digest for path, digest in self.manifests(workspace).items() if Path(path).name == 'package.json'}

    async def install(self):
        if not hasattr(self, '_lock'):
            self._lock = asyncio.Lock()
        async with self._lock:
            return await self._install()

    async def _install(self):
        await self.processes.sandbox.check()
        self.processes.mirror.pull()
        self.processes.mirror.push()
        root = self.processes.mirror.root
        if not (root / 'package.json').is_file():
            raise ValueError('Initialize an application package.json before installing dependencies')
        digest = await self.fingerprint()
        try:
            previous = json.loads(self.stamp.read_text())
        except (OSError, ValueError):
            previous = {}
        modules = root / 'node_modules'
        # A stamp alone is insufficient after deleting node_modules or its lock.
        internal_lock = modules / '.package-lock.json'
        lock_hash = sha256(internal_lock.read_bytes()).hexdigest() if internal_lock.is_file() else None
        installed = False
        if lock_hash:
            try:
                packages = json.loads(internal_lock.read_text())['packages']
                installed = bool(packages) and all(present(root / path) for path in packages)
            except (ValueError, KeyError):
                pass
        if previous.get('fingerprint') == digest and installed and previous.get('installed_lock') == lock_hash:
            return {'status': 'reused', 'fingerprint': digest, 'toolchain': self.toolchain}
        operation = 'ci' if (root / 'package-lock.json').is_file() or (root / 'npm-shrinkwrap.json').is_file() else 'install'
        flags = ['--include=dev', '--include=optional', '--no-audit', '--no-fund', '--prefer-offline']
        # The agent may edit a manifest while npm runs (the warm-up installs in parallel with
        # its work): such an installation must not be recorded as matching the new manifest.
        requested = self._declared()
        result = await self.processes.run(['npm', operation, *flags])
        if operation == 'ci' and result['status'] != 'completed' and await self._out_of_sync(result):
            # A dependency was added to package.json: npm install updates the shipped lockfile.
            operation = 'install'
            result = await self.processes.run(['npm', operation, *flags])
        if result['status'] != 'completed':
            return {'status': 'installation_failed', 'diagnostic': result, 'application_failure': False}
        if self._declared() != requested:
            return {'status': 'installed', 'operation': operation, 'stale': True,
                'notice': 'A manifest changed during the installation; the next installation runs again.'}
        digest = await self.fingerprint()  # npm install may have created a lockfile.
        data = {'fingerprint': digest, 'installed_lock': sha256(internal_lock.read_bytes()).hexdigest()
            if internal_lock.is_file() else None, 'toolchain': self.toolchain}
        self.stamp.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')
        return {'status': 'installed', 'operation': operation, **data}


SYNC_ERRORS = ('can only install packages when your package.json and package-lock.json', 'are in sync',
    'Missing: ', 'Invalid: lock file')


async def _read_log(processes, result):
    identity = result.get('artifact')
    try:
        return processes.artifacts.path(identity).read_text(encoding='utf-8') if identity else result.get('content', '')
    except (OSError, ValueError):
        return result.get('content', '')


def environment_report():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = Path(driver.chromium.executable_path)
    return {'host_python': sys.version.split()[0], 'platform': platform.platform(),
        'host_tools': {name: shutil.which(name) for name in ('node', 'npm', 'git', 'bwrap', 'docker', 'cc', 'make')},
        'chromium': {'installed': browser.is_file(), 'executable': str(browser)},
        'native_libraries': 'The actual Chromium launch and npm native module build are checked on demand.'}
