"""Noninteractive isolated execution. Only an application mirror is mounted writable.

Original requirements, acceptance tests, credentials and session artifacts are never
mounted. There is deliberately no unsandboxed fallback.
"""

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic, time_ns
from uuid import uuid4

from infrastructure.utils.processes import process_options, stop_process
from .files import PROTECTED, atomic_write, protected, safe_path, source_files, visible


class EnvironmentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionSettings:
    backend: str = 'auto'
    network: bool = True
    docker_image: str = 'node:22-bookworm'
    docker_user: str = '1000:1000'
    timeout_seconds: int = 600
    memory_mb: int = 2048
    cpus: int = 2
    pids: int = 256
    tmp_mb: int = 512
    max_output_bytes: int = 4_000_000
    allowed_ports: tuple[int, ...] = (3000, 5173)
    verification_port: int = 3100  # Host-owned; never available to agent commands.


class ExecutionMirror:
    """Copy regular source files only; refuse conflicts when synchronizing changes.

    Dependencies, build output and runtime databases stay in the mirror. Original
    tests can be copied for local checks but their originals can never be changed
    by a command, including through links, renames or a modified package script.
    """
    def __init__(self, workspace, directory):
        self.workspace, self.root = workspace, directory / 'execution'
        self.baseline = {}
        self.initialized = False
        self.generation = 0  # Incremented by every clean reset; part of check cache keys.
        self._snapshots = {}

    def _signature(self, root):
        """Cheap directory listing (name, mtime, size). None when a file is so recent
        that an equal-size rewrite within the timestamp granularity could be missed."""
        entries, stack, recent = [], [(Path(root), '')], time_ns() - 2_000_000_000
        while stack:
            directory, prefix = stack.pop()
            try:
                with os.scandir(directory) as listing:
                    for entry in listing:
                        relative = prefix + entry.name
                        if not visible(relative) or relative.startswith('backend/data'):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, relative + '/'))
                            entries.append((relative, 'd'))
                        else:
                            status = entry.stat(follow_symlinks=False)
                            if status.st_mtime_ns >= recent:
                                return None
                            entries.append((relative, status.st_mtime_ns, status.st_size, entry.is_symlink()))
            except OSError:
                return None
        return hash(tuple(sorted(entries)))

    def snapshot(self, root):
        # Several snapshots are taken per tool call; an unchanged, settled tree is
        # not hashed again. Any doubt (recent write, listing error) recomputes.
        signature = self._signature(root)
        cached = self._snapshots.get(str(root))
        if signature is not None and cached and cached[0] == signature:
            return dict(cached[1])
        result = {p: sha256(f.read_bytes()).hexdigest() for p, f in source_files(root)
            if not p.startswith('backend/data/') and f.stat().st_size <= 20_000_000}
        if signature is not None and signature == self._signature(root):
            self._snapshots[str(root)] = (signature, dict(result))
        return result

    def push(self):
        self.root.mkdir(parents=True, exist_ok=True)
        current = self.snapshot(self.workspace)
        for relative, digest in current.items():
            target = safe_path(self.root, relative)
            if not target.exists() or sha256(target.read_bytes()).hexdigest() != digest:
                atomic_write(target, safe_path(self.workspace, relative).read_bytes())
        for relative in self.baseline.keys() - current.keys():
            target = safe_path(self.root, relative)
            target.unlink(missing_ok=True)
        self.baseline = current
        self.initialized = True
        # Mount points exist before launch, including for currently absent tests.
        for relative in PROTECTED:
            if '.' not in Path(relative).name:
                (self.root / relative).mkdir(parents=True, exist_ok=True)

    def pull(self):
        if not self.initialized:
            return []
        current = self.snapshot(self.root)
        original = self.snapshot(self.workspace)
        changed = []
        for relative in sorted(current.keys() | self.baseline.keys()):
            if protected(relative) or current.get(relative) == self.baseline.get(relative):
                # Unchanged by commands; a source deleted from the workspace must not
                # survive in the mirror once the baseline is refreshed below.
                if relative in current and relative not in original and not protected(relative):
                    safe_path(self.root, relative).unlink(missing_ok=True)
                continue
            if original.get(relative) != self.baseline.get(relative):
                raise ValueError(f'Concurrent source changes: {relative}; inspect before retrying')
            target = safe_path(self.workspace, relative)
            if relative in current:
                atomic_write(target, safe_path(self.root, relative).read_bytes())
            else:
                target.unlink(missing_ok=True)
            changed.append(relative)
        # Do not accept modified protected copies as a new source of truth.
        self.baseline = self.snapshot(self.workspace)
        return changed

    def revision(self):
        return sha256(json.dumps(self.snapshot(self.workspace), sort_keys=True).encode()).hexdigest()

    def reset(self, keep=('node_modules', '.npm-cache')):
        """Clean delivery state: only workspace sources plus reusable dependencies remain.

        Build output, development databases and files a command left outside the
        synchronized sources are removed, so validation cannot depend on them.
        """
        if self.initialized:
            self.pull()

        def clean(directory):
            for entry in list(directory.iterdir()):
                if entry.name in keep:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    clean(entry)
                    try:
                        entry.rmdir()
                    except OSError:
                        pass  # Still holds retained dependencies.
                else:
                    entry.unlink(missing_ok=True)
        if self.root.is_dir():
            clean(self.root)
        self.baseline, self.initialized = {}, False
        self.generation += 1
        self.push()


def clean_environment():
    # No inherited API keys, npm config, preload variables or private HOME.
    names = ('PATH', 'SystemRoot', 'WINDIR', 'PATHEXT', 'COMSPEC')
    return {**{k: os.environ[k] for k in names if k in os.environ},
        'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'CI': '1', 'NO_COLOR': '1'}


class Sandbox:
    def __init__(self, mirror, settings, directory):
        self.mirror, self.settings, self.directory = mirror, settings, directory
        self.backend = ('docker' if os.name == 'nt' else 'bubblewrap') if settings.backend == 'auto' else settings.backend
        self.checked = False
        self.identity = None

    def process_env(self, overrides=None):
        """Variables of an unisolated host command: a private home, cache and temp
        directory under the session state, and no inherited credentials."""
        root = self.mirror.root.resolve()
        home, temporary = self.directory / 'host-home', self.directory / 'host-tmp'
        for path in (home, temporary):
            path.mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in self.guest_env(overrides).items() if key not in {'PATH', 'LANG'}}
        env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
            TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary), npm_config_cache=str(root / '.npm-cache'))
        if 'DATABASE_URL' in env:
            env['DATABASE_URL'] = str(root / env['DATABASE_URL'].removeprefix('/workspace/'))
        return env

    def executable(self):
        if self.backend == 'host':
            return None
        name = 'docker' if self.backend == 'docker' else 'bwrap'
        if self.backend == 'bubblewrap' and sys.platform != 'linux':
            raise EnvironmentUnavailable('Bubblewrap requires Linux; select the Windows Docker profile')
        found = shutil.which(name)
        if not found:
            raise EnvironmentUnavailable(f'{name} is unavailable; install the configured sandbox. No host fallback.')
        return found

    def guest_env(self, overrides=None):
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': '/tmp', 'TMPDIR': '/tmp', 'CI': '1', 'NO_COLOR': '1', 'LANG': 'C.UTF-8',
            'npm_config_cache': '/workspace/.npm-cache', 'npm_config_update_notifier': 'false',
            'npm_config_audit': 'false', 'npm_config_fund': 'false', 'GIT_TERMINAL_PROMPT': '0'}
        for key, value in (overrides or {}).items():
            if key not in {'PORT', 'HOST', 'NODE_ENV', 'DATABASE_URL'} or not isinstance(value, str) or '\x00' in value:
                raise ValueError('Only PORT, HOST, NODE_ENV and DATABASE_URL may be configured for commands')
            if key == 'DATABASE_URL' and (not value.startswith('/workspace/') or '..' in Path(value).parts):
                raise ValueError('DATABASE_URL must be inside /workspace')
            env[key] = value
        return env

    def argv(self, command, name, ports=(), env=None):
        if not isinstance(command, list) or not command or any(not isinstance(p, str) or '\x00' in p for p in command):
            raise ValueError('command must be a nonempty argv list')
        permitted = {*self.settings.allowed_ports, self.settings.verification_port}
        if any(type(p) is not int or p not in permitted for p in ports) or len(set(ports)) != len(ports):
            raise ValueError('Port is not allowed by the execution profile')
        if ports and not self.settings.network:
            raise ValueError('Published browser ports require network=true in this backend')
        if self.backend == 'host':
            # Explicit opt-in for a disposable, already isolated machine: no isolation here.
            found = shutil.which(command[0])
            if not found:
                raise EnvironmentUnavailable(f'{command[0]} is not installed on the host')
            return [found, *command[1:]]
        binary = self.executable()
        root, cfg = self.mirror.root.resolve(), self.settings
        protected_dirs = [root / p for p in PROTECTED if (root / p).exists()]
        guest = self.guest_env(env)
        if self.backend == 'docker':
            if ',' in str(root):
                raise ValueError('Docker workspace paths cannot contain commas')
            argv = [binary, 'run', '--rm', '--init', '--name', name, '--label', 'agentase.session=true',
                '--pull=never', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--user', cfg.docker_user, '--cpus', str(cfg.cpus), '--memory', f'{cfg.memory_mb}m',
                '--pids-limit', str(cfg.pids), '--tmpfs', f'/tmp:rw,nosuid,nodev,size={cfg.tmp_mb}m',
                '--mount', f'type=bind,source={root},target=/workspace', '--workdir', '/workspace']
            for path in protected_dirs:
                argv += ['--mount', f'type=bind,source={path},target=/workspace/{path.relative_to(root).as_posix()},readonly']
            if not cfg.network:
                argv += ['--network', 'none']
            for port in ports:
                argv += ['--publish', f'127.0.0.1:{port}:{port}']
            for key, value in sorted(guest.items()):
                argv += ['--env', f'{key}={value}']
            return argv + [cfg.docker_image, *command]
        argv = [binary, '--die-with-parent', '--new-session', '--unshare-user', '--unshare-pid',
            '--unshare-ipc', '--unshare-uts', '--unshare-cgroup-try', '--disable-userns',
            '--cap-drop', 'ALL', '--clearenv', '--ro-bind', '/usr', '/usr']
        if not cfg.network:
            argv += ['--unshare-net']
        for text in ('/bin', '/sbin', '/lib', '/lib64'):
            path = Path(text)
            if path.is_symlink():
                argv += ['--symlink', os.readlink(path), text]
            elif path.exists():
                argv += ['--ro-bind', text, text]
        for path in ('/etc/passwd', '/etc/group', '/etc/nsswitch.conf', '/etc/hosts', '/etc/resolv.conf', '/etc/ssl'):
            argv += ['--ro-bind-try', path, path]
        argv += ['--proc', '/proc', '--dev', '/dev', '--size', str(cfg.tmp_mb * 1024 * 1024),
            '--tmpfs', '/tmp', '--bind', str(root), '/workspace']
        for path in protected_dirs:
            argv += ['--ro-bind', str(path), '/workspace/' + path.relative_to(root).as_posix()]
        for key, value in sorted(guest.items()):
            argv += ['--setenv', key, value]
        return argv + ['--chdir', '/workspace', '--', *command]

    async def _control(self, argv, timeout=15):
        env = clean_environment()
        if self.backend == 'docker':
            configuration = self.directory / 'docker-client'
            configuration.mkdir(parents=True, exist_ok=True)
            env['DOCKER_CONFIG'] = str(configuration)
        options = process_options()
        if os.name == 'nt':
            options['creationflags'] |= subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(argv, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **options)
        try:
            out, err = await asyncio.to_thread(process.communicate, timeout=timeout)
        except BaseException:
            await asyncio.to_thread(stop_process, process)
            raise
        if process.returncode:
            raise EnvironmentUnavailable((err or out).decode('utf-8', 'replace')[-2000:])
        return out.decode('utf-8', 'replace')

    async def check(self):
        if self.checked:
            return self.identity
        self.mirror.push()
        if self.backend == 'host':
            self.identity, self.checked = {'backend': 'host', 'isolation': 'none'}, True
            return self.identity
        binary = self.executable()
        if self.backend == 'docker':
            await self._control([binary, 'info', '--format', '{{.OSType}}'])
            raw = await self._control([binary, 'image', 'inspect', self.settings.docker_image])
            info = json.loads(raw)[0]
            if info.get('Os') != 'linux' or info.get('Config', {}).get('Volumes'):
                raise EnvironmentUnavailable('Use a Linux Node image without declared VOLUME paths')
            self.identity = {'backend': 'docker', 'image_id': info['Id']}
        else:
            version = await self._control([binary, '--version'])
            name = 'agentase-check-' + uuid4().hex
            await self._control(self.argv(['/bin/true'], name))
            self.identity = {'backend': 'bubblewrap', 'version': version.strip()}
        self.checked = True
        return self.identity

    async def remove(self, name):
        if self.backend == 'docker':
            try:
                await self._control([self.executable(), 'rm', '--force', '--volumes', name])
            except EnvironmentUnavailable as error:
                if 'No such container' not in str(error):
                    raise


class ProcessManager:
    def __init__(self, workspace, directory, settings, artifacts):
        self.directory, self.settings, self.artifacts = directory, settings, artifacts
        self.mirror = ExecutionMirror(workspace, directory)
        self.sandbox = Sandbox(self.mirror, settings, directory)
        self.processes = {}
        self._closed = False
        self.monitors = set()

    def ports(self):
        return {port for entry in self.processes.values() if entry['process'].poll() is None for port in entry['ports']}

    async def _responds(self, port):
        # Docker's port publisher accepts TCP before the service listens, so
        # readiness requires actual HTTP response bytes.
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port), 2)
            writer.write(b'GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
            await writer.drain()
            return bool(await asyncio.wait_for(reader.read(1), 2))
        except (OSError, asyncio.TimeoutError):
            return False
        finally:
            if writer:
                writer.close()

    async def wait_ready(self, name, timeout):
        entry = self.processes[name]
        deadline = monotonic() + timeout
        while monotonic() < deadline and entry['process'].poll() is None:
            if entry['ports'] and all([await self._responds(port) for port in entry['ports']]):
                return True
            await asyncio.sleep(0.25)
        return False

    async def start(self, name, command, ports=(), env=None, restart=False, ready_timeout=0, host=False):
        # The verification port belongs to host-owned acceptance launches only.
        if not host and self.settings.verification_port in ports:
            raise ValueError('Port is not allowed by the execution profile')
        status = await self._start(name, command, ports, env, restart)
        if ready_timeout and ports:
            ready = await self.wait_ready(name, ready_timeout)
            status = {**self.status(name), 'ready': ready}
            if not ready:
                status['notice'] = ('No HTTP response on the declared ports before ready_timeout; '
                    'inspect process_logs before retrying.')
        return status

    async def _start(self, name, command, ports=(), env=None, restart=False):
        if self._closed:
            raise RuntimeError('Process manager is closed')
        existing = self.processes.get(name)
        if existing and existing['process'].poll() is None:
            if not restart:
                if existing['command'] != command or tuple(ports) != existing['ports'] or (env or {}) != existing['env']:
                    raise ValueError('Process name already has another command; request restart explicitly')
                return self.status(name)
            await self.stop(name)
        if set(ports) & self.ports():
            raise ValueError('A requested port is already owned by this session')
        await self.sandbox.check()
        self.mirror.pull()
        self.mirror.push()
        container = 'agentase-' + uuid4().hex
        argv = self.sandbox.argv(command, container, ports, env)
        logs = self.directory / 'process-logs'
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / (container + '.log')
        with log.open('wb') as output:
            options = process_options()
            if os.name == 'nt':
                options['creationflags'] |= subprocess.CREATE_NO_WINDOW
            host_env = clean_environment()
            if self.sandbox.backend == 'docker':
                host_env['DOCKER_CONFIG'] = str(self.directory / 'docker-client')
            elif self.sandbox.backend == 'host':
                host_env.update(self.sandbox.process_env(env))
            process = subprocess.Popen(argv, cwd=self.mirror.root, env=host_env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, **options)
        entry = {'process': process, 'container': container, 'command': command, 'ports': tuple(ports),
            'env': env or {}, 'log': log, 'started': monotonic(), 'revision': self.mirror.revision(),
            'stop_lock': asyncio.Lock(), 'stopped': False}
        self.processes[name] = entry
        monitor = asyncio.create_task(self._monitor(name, entry))
        self.monitors.add(monitor)
        monitor.add_done_callback(self.monitors.discard)
        await asyncio.sleep(0)
        return self.status(name)

    def status(self, name):
        entry = self.processes[name]
        code = entry['process'].poll()
        return {'name': name, 'running': code is None, 'returncode': code, 'ports': entry['ports'],
            'source_changed_since_start': entry['revision'] != self.mirror.revision(),
            'elapsed_seconds': round(monotonic() - entry['started'], 3), 'backend': self.sandbox.backend,
            'notice': 'Restart a non-watching server after source changes; a running process is not proof of readiness.'}

    def logs(self, name, offset=0, limit=12000):
        entry = self.processes[name]
        data = entry['log'].read_bytes()[:self.settings.max_output_bytes]
        identity = self.artifacts.put(data.decode('utf-8', 'replace'))
        return {**self.status(name), **self.artifacts.read(identity, offset, limit)}

    async def stop(self, name):
        entry = self.processes[name]
        async with entry['stop_lock']:
            if not entry['stopped']:
                try:
                    await asyncio.to_thread(stop_process, entry['process'])
                finally:
                    await self.sandbox.remove(entry['container'])
                entry['stopped'] = True
        self.mirror.pull()
        return self.status(name)

    async def _monitor(self, name, entry):
        try:
            while entry['process'].poll() is None and not self._closed:
                if entry['log'].stat().st_size > self.settings.max_output_bytes:
                    entry['output_limit'] = True
                    break
                await asyncio.sleep(0.1)
            if not self._closed and self.processes.get(name) is entry:
                await self.stop(name)
        except Exception as error:
            entry['cleanup_error'] = str(error)

    async def run(self, command, timeout=None, env=None):
        timeout = timeout or self.settings.timeout_seconds
        if not 1 <= timeout <= self.settings.timeout_seconds:
            raise ValueError('Command timeout exceeds configured execution limit')
        name = 'command-' + uuid4().hex
        await self.start(name, command, env=env)
        entry = self.processes[name]
        reason = 'completed'
        try:
            while entry['process'].poll() is None:
                if monotonic() - entry['started'] >= timeout:
                    reason = 'timed_out'
                    break
                if entry['log'].stat().st_size > self.settings.max_output_bytes:
                    reason = 'output_limit'
                    break
                await asyncio.sleep(0.05)
        finally:
            # Also kill descendants after their leader exits; cancellation never
            # leaves an install/build or docker container writing in the background.
            await self.stop(name)
        result = self.logs(name)
        if entry.get('output_limit'):
            reason = 'output_limit'
        result['status'] = reason if reason != 'completed' or result['returncode'] == 0 else 'failed'
        result['accepted'] = False
        return result

    async def stop_all(self):
        """Stop every running owned process; return their names for the repair feedback."""
        stopped = []
        for name in tuple(self.processes):
            if self.processes[name]['process'].poll() is None:
                await self.stop(name)
                stopped.append(name)
        return stopped

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        for task in tuple(self.monitors):
            task.cancel()
        await asyncio.gather(*self.monitors, return_exceptions=True)
        errors = []
        for name in tuple(self.processes):
            try:
                await self.stop(name)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError('Some session processes could not be cleaned up') from errors[0]
