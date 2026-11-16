"""Per-run persistence: session, events, usage, fingerprints and workspace checkpoints.

Files are versioned and written atomically, with the previous version kept so an
interrupted write can be recovered. Resuming a conversation never restores files:
the workspace is whatever the previous run left (including the effects of an
interrupted command), and explicit Git checkpoints record its state separately.
A saved state is refused when its inputs or instructions changed.
"""

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from .messages import Message, Usage

FORMAT_VERSION = 1
SECRET_PATTERNS = (re.compile(r'\bsk-[A-Za-z0-9_\-]{12,}'), re.compile(r'(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}'),
    re.compile(r'(?i)\b((?:api[_-]?key|authorization|password|secret|token)["\']?\s*[:=]\s*["\']?)[^\s"\',}]{8,}'))


class ResumeError(ValueError):
    """The saved state cannot be continued safely."""


def mask(text, secrets=()):
    """Remove known secret values and common credential shapes from persisted text."""
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, '***')
    text = SECRET_PATTERNS[0].sub('***', text)
    text = SECRET_PATTERNS[1].sub(lambda match: match.group(1) + ' ***', text)
    return SECRET_PATTERNS[2].sub(lambda match: match.group(1) + '***', text)


def fingerprint_input(directory):
    """Every input file: requirements, references and supplied tests."""
    directory = Path(directory)
    entries = {}
    for path in sorted(directory.rglob('*')):
        if path.is_file() and not path.is_symlink() and 'node_modules' not in path.parts:
            entries[path.relative_to(directory).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def fingerprint_profile(profile):
    """Instructions, tools, acceptance policy and execution image. Budget limits and
    model credentials may legitimately differ when a run is continued."""
    execution = {key: value for key, value in vars(profile.execution).items() if key in {'backend', 'docker_image', 'network'}}
    return sha256(json.dumps({'name': profile.name, 'tools': profile.tools, 'role': profile.role,
        'workflow': profile.workflow, 'image_mode': profile.image_mode, 'acceptance': vars(profile.acceptance),
        'execution': execution, 'model': profile.llm.model}, sort_keys=True, default=str).encode()).hexdigest()


class RunStore:
    def __init__(self, directory, secrets=()):
        self.directory, self.secrets = Path(directory), tuple(secrets)

    def write_json(self, name, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / name
        text = mask(json.dumps(data, ensure_ascii=False, indent=1, default=str), self.secrets)
        with tempfile.NamedTemporaryFile('w', dir=self.directory, prefix='.' + name + '.', suffix='.tmp',
                delete=False, encoding='utf-8') as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if path.is_file():
                shutil.copyfile(path, path.with_suffix(path.suffix + '.bak'))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read_json(self, name):
        """Current file, or the previous complete version after an interrupted write."""
        path = self.directory / name
        for candidate in (path, path.with_suffix(path.suffix + '.bak')):
            try:
                return json.loads(candidate.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
        raise ResumeError(f'No readable {name} in {self.directory}')

    def event(self, kind, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        line = mask(json.dumps({'time': round(time.time(), 3), 'kind': kind, 'data': data},
            ensure_ascii=False, default=str), self.secrets)
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(line + '\n')

    def events(self):
        """Complete events only: a line cut by an interruption is ignored."""
        result = []
        try:
            lines = (self.directory / 'events.jsonl').read_text(encoding='utf-8').splitlines()
        except OSError:
            return result
        for line in lines:
            try:
                result.append(json.loads(line))
            except ValueError:
                continue
        return result


def session_payload(state, budget, fingerprints, extra):
    return {'format_version': FORMAT_VERSION, 'session_id': state.id, 'status': state.status,
        'saved_at': round(time.time(), 3), 'messages': [message.to_dict() for message in state.messages],
        'todos': state.todos, 'notes': state.notes, 'interfaces': state.interfaces, 'checks': state.checks,
        'verifications': state.verifications, 'compactions': state.compactions, 'requests': state.requests,
        'auxiliary_requests': state.auxiliary_requests, 'usage': [asdict(usage) for usage in state.usage],
        'budget': {'requests': budget.requests, 'tool_calls': budget.tool_calls, 'tokens': budget.tokens,
            'usage_missing': budget.usage_missing, 'retries': budget.retries, 'elapsed': budget.elapsed(),
            'verifications': budget.verifications, 'stagnation_notices': budget.stagnation_notices,
            'seconds': budget.seconds, 'tool_seconds': budget.tool_seconds, 'pruned': budget.pruned,
            'input_tokens': budget.input_tokens, 'output_tokens': budget.output_tokens,
            'cached_tokens': budget.cached_tokens, 'reasoning_tokens': budget.reasoning_tokens},
        'fingerprints': fingerprints, **extra}


def restore_session(payload, state, budget):
    if payload.get('format_version') != FORMAT_VERSION:
        raise ResumeError(f'Unsupported session format {payload.get("format_version")!r}; expected {FORMAT_VERSION}')
    state.messages[:] = [Message.from_dict(item) for item in payload['messages']]
    state.todos, state.notes, state.interfaces = payload['todos'], payload['notes'], payload['interfaces']
    state.checks, state.verifications = payload['checks'], payload['verifications']
    state.compactions, state.requests = payload['compactions'], payload['requests']
    state.auxiliary_requests = payload['auxiliary_requests']
    state.usage[:] = [Usage(**item) for item in payload['usage']]
    saved = payload['budget']
    budget.requests.update(saved['requests'])
    budget.tool_calls, budget.tokens = saved['tool_calls'], saved['tokens']
    budget.usage_missing, budget.retries = saved['usage_missing'], saved['retries']
    budget.verifications, budget.stagnation_notices = dict(saved['verifications']), saved['stagnation_notices']
    # Measurements added after format 1 was defined: absent from older states.
    budget.seconds, budget.pruned = dict(saved.get('seconds', {})), dict(saved.get('pruned', budget.pruned))
    budget.tool_seconds = {name: list(entry) for name, entry in saved.get('tool_seconds', {}).items()}
    budget.input_tokens, budget.output_tokens = saved.get('input_tokens', 0), saved.get('output_tokens', 0)
    budget.cached_tokens = saved.get('cached_tokens', 0)
    budget.reasoning_tokens = saved.get('reasoning_tokens', 0)
    # Time already spent counts against the same total budget.
    budget.started = budget.clock() - saved['elapsed']


class WorkspaceCheckpoints:
    """Explicit restore points of the workspace files, independent of the conversation."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.git = shutil.which('git')

    def _run(self, *arguments):
        env = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'WINDIR', 'PATHEXT', 'COMSPEC') if key in os.environ}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
            GIT_AUTHOR_NAME='application-agent', GIT_AUTHOR_EMAIL='agent@localhost',
            GIT_COMMITTER_NAME='application-agent', GIT_COMMITTER_EMAIL='agent@localhost')
        return subprocess.run([self.git, '-C', str(self.workspace), '-c', 'core.hooksPath=' + os.devnull,
            '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', *arguments],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)

    def create(self, label):
        """Commit the current files; returns the commit id or None when Git cannot be used."""
        if not self.git:
            return None
        try:
            metadata = self.workspace / '.git'
            if metadata.is_symlink() or (metadata.exists() and not metadata.is_dir()):
                return None
            if not metadata.exists() and self._run('init', '--quiet').returncode:
                return None
            if self._run('add', '--all').returncode:
                return None
            self._run('commit', '--quiet', '--allow-empty', '--no-verify', '-m', label[:200])
            result = self._run('rev-parse', 'HEAD')
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
