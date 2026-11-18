"""Owned native registry with explicit capabilities, bounded results and lifecycle."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess

from .artifacts import ArtifactStore
from .browser import BrowserSession
from .dependencies import DependencyManager
from .execution import EnvironmentUnavailable, ProcessManager, clean_environment
from .files import PROTECTED, WorkspaceFiles, protected
from .images import view_image
from .messages import ToolCall, ToolResult
from .model import OpenAIModel, ProviderError
from .tool_schemas import TOOLS, validate
from infrastructure.verification.checks import ApplicationChecks
from infrastructure.verification.coverage import CoverageRegistry
from infrastructure.verification.results import ENVIRONMENT, PASSED, error_excerpt

# A forgotten server in run_command blocked a real run for its whole 600 s timeout.
COMMAND_TIMEOUT = 120
SERVER_WORDS = ('npm start', 'npm run start', 'npm run dev', 'npm run preview', 'vite', 'tsx watch', 'node --watch',
    'nodemon', 'dist/server.js', 'src/server.ts', 'npm run dev:backend', 'npm run dev:frontend', 'serve ')


def long_running(command):
    text = ' '.join(command).replace('  ', ' ')
    if any(word in text for word in ('vite build', 'tsc', '--version', 'npm run build', 'timeout '))             or text.rstrip().endswith('&'):
        return False  # A build, a version check, or a command bounded or sent to the background.
    return any(word in text for word in SERVER_WORDS)


MANUAL_CHECKS = {'run_command', 'http_request', 'database_query', 'browser', 'process_start', 'process_logs'}
MANUAL_CHECK_REMINDER = 6

# Commands whose output is progress noise: the agent needs their errors, not their log.
NOISY = {'npm', 'npx', 'pnpm', 'yarn', 'tsc', 'vite'}

# Calls that change no file, process or declaration: consecutive ones of a response may
# run together. A GET http_request qualifies too (see ToolRegistry.concurrent).
CONCURRENT = {'read_file', 'read_files', 'list_files', 'search_text', 'read_artifact', 'requirement_catalog',
    'read_requirement', 'coverage', 'database_query', 'view_image', 'process_status', 'process_logs', 'git_read',
    'find_symbol', 'read_skill'}


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    session_id: str
    allowed: tuple[str, ...]
    protected: tuple[str, ...] = PROTECTED


class ToolRegistry:
    def __init__(self, context, state, profile, catalog=None):
        if set(context.allowed) - TOOLS.keys():
            raise ValueError('Unavailable tool in session capabilities')
        self.context, self.state, self.profile, self.catalog = context, state, profile, catalog
        self.artifacts = ArtifactStore(state.state_directory)
        self.files = WorkspaceFiles(context.workspace, self.artifacts, context.protected)
        self.processes = ProcessManager(context.workspace, state.state_directory, profile.execution, self.artifacts)
        self.dependencies = DependencyManager(self.processes, state.state_directory)
        self.browser = BrowserSession(self.processes, self.artifacts)
        self.checks = ApplicationChecks(self.processes, self.dependencies, self.artifacts, state)
        self.coverage = CoverageRegistry(catalog) if catalog else None
        self.observations = []
        # Requirement ids whose text this conversation currently holds; emptied by compaction.
        self.requirements_shown = set()
        self.requirements_inline = False  # The whole requirements file is in the task message.
        self.budget = None  # Attached by the session loop; shared with host verification.
        self.vision_factory = OpenAIModel
        # Sub-agents get their own client so their requests run concurrently.
        self.model_factory = lambda: OpenAIModel(profile.llm)
        self.event_sink = None  # Session event log, set by the application agent.
        self.acceptance_runner = None  # Set by the application agent once the host verifier exists.
        self.finish_requested = False
        self.finish_note = None
        self.image_cache = {}  # (image id, question) -> description: the vision model answers once.
        self.build_passed = False
        self.manual_checks = 0

    def can_write(self, path):
        return not protected(path, self.context.protected)

    def schemas(self):
        return [deepcopy(TOOLS[name]) for name in self.context.allowed]

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name not in self.context.allowed:
            return ToolResult(call.id, call.name, error='TOOL_NOT_ALLOWED')
        try:
            arguments = json.loads(call.arguments)
            validate(arguments, TOOLS[call.name]['function']['parameters'])
            self.processes.mirror.pull()
            result = await self.dispatch(call.name, arguments)
            result = self.steer(call.name, arguments, result)
            if call.name != 'read_files':  # Bounded per file: one long file never hides the others.
                result = self.artifacts.bound(result, self.profile.observation_chars)
            return ToolResult(call.id, call.name, result)
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            return ToolResult(call.id, call.name, error=str(error)[:2500])

    def steer(self, name, arguments, result):
        """In real runs the agent spent 10 to 20 minutes testing journeys by hand after its
        build passed. Once it has passed, a run of manual checks earns one reminder that
        the host acceptance tests answer faster."""
        if name == 'verify_application' and arguments.get('kind') == 'all' and isinstance(result, dict) \
                and result.get('status') == PASSED:
            self.build_passed = True
        if self.build_passed and self.acceptance_runner and name in MANUAL_CHECKS:
            self.manual_checks += 1
            if self.manual_checks == MANUAL_CHECK_REMINDER and isinstance(result, dict):
                result = {**result, 'reminder': f'{self.manual_checks} manual checks since the build passed. Call '
                    'run_acceptance_tests: it runs every acceptance journey on a fresh database and lists each '
                    'failure precisely. Or reply with your completion summary.'}
        return result

    def concurrent(self, call):
        """True when the call may run alongside its read-only neighbors."""
        if call.name == 'http_request':
            try:
                return json.loads(call.arguments).get('method', 'GET') == 'GET'
            except (ValueError, AttributeError):
                return True  # Rejected as an observation; it has no effect to order.
        return call.name in CONCURRENT and call.name in self.context.allowed

    def command_observation(self, result, command):
        """Filter the log of a package-manager, compiler or build command at the source:
        the end of a successful run, the error lines of a failed one. Other commands
        (cat, ls, a script whose output is the answer) are returned unchanged."""
        words = ' '.join(command).split() if command and command[0] in {'sh', 'bash'} else list(command or ())
        if not result.get('artifact') or not NOISY & {Path(word).name for word in words[:6]}:
            return result
        text = self.artifacts.path(result['artifact']).read_text(encoding='utf-8')
        if len(text) <= 2000:
            return result
        succeeded = result.get('status') == 'completed'
        shown = text[-1000:] if succeeded else error_excerpt(text, 4000)
        kept = {key: value for key, value in result.items() if key not in {'content', 'offset', 'next_offset'}}
        return {**kept, 'content': shown, 'total_chars': len(text), 'notice': ('Successful command: only the end of '
            'its output is shown. ' if succeeded else 'Failed command: only error lines and their context are shown. ')
            + 'read_artifact returns the full log.'}

    def read_range(self, path, start_line=1, end_line=None):
        if end_line is not None and end_line < start_line:
            raise ValueError('end_line precedes start_line')
        return self.files.read(path, start_line, end_line)

    def read_many(self, files):
        if not files:
            raise ValueError('read_files needs at least one file')
        items = []
        for item in files:
            try:
                items.append(self.artifacts.bound(self.read_range(**item), self.profile.observation_chars))
            except (ValueError, OSError) as error:
                items.append({'path': item['path'], 'error': str(error)[:500]})
        return {'files': items}

    async def dispatch(self, name, args):
        methods = {'read_file': self.read_range, 'read_files': self.read_many, 'write_file': self.files.write,
            'write_files': self.files.write_many, 'edit_file': self.files.edit,
            'apply_patch': self.files.patch, 'list_files': self.files.listing, 'search_text': self.files.search,
            'read_artifact': self.artifacts.read}
        if name in methods:
            result = methods[name](**args)
            if name in {'write_file', 'write_files', 'edit_file', 'apply_patch'} and self.processes.mirror.initialized:
                self.processes.mirror.push()
            return result
        if name in {'requirement_catalog', 'read_requirement', 'coverage'}:
            if self.catalog is None:
                raise ValueError('No requirements input is attached to this session')
            if name == 'requirement_catalog':
                return self.catalog.catalog(**args)
            if name == 'read_requirement':
                if self.requirements_inline:
                    self.requirements_shown.update(self.catalog.nodes)
                found = self.catalog.read(args['identity'], shown=self.requirements_shown,
                    descendants=bool(args.get('descendants')))
                if self.requirements_inline:
                    found['notice'] = ('The complete requirements are already in your first message (original_yaml): '
                        'read them there instead of calling read_requirement.')
                return found
            result = self.coverage.view(self.state.todos, self.processes.mirror.revision())
            rows = result['requirements']
            offset, limit = args.get('offset', 0), args.get('limit', 50)
            return {**result, 'requirements': rows[offset:offset + limit], 'total': len(rows),
                'next_offset': offset + limit if offset + limit < len(rows) else None}
        if name == 'todo_write':
            items = args['items']
            if len({item['id'] for item in items}) != len(items):
                raise ValueError('Task ids must be unique')
            if len(json.dumps(items)) > 80000:
                raise ValueError('Keep the task list below 80000 characters')
            if self.catalog and any(rid not in self.catalog.nodes for item in items for rid in item['requirements']):
                raise ValueError('Task references an unknown requirement')
            self.state.todos = deepcopy(items)
            return {'items': items, 'accepted': False}
        if name == 'note_write':
            if len(json.dumps(args)) > 10000:
                raise ValueError('Keep working notes below 10000 characters')
            self.state.notes = deepcopy(args)
            return {'saved': True, 'notice': 'Agent notes are claims; retain evidence references.'}
        if name == 'install_dependencies':
            installed = await self.dependencies.install()
            if isinstance(installed.get('diagnostic'), dict):
                installed = {**installed, 'diagnostic': self.command_observation(installed['diagnostic'], ['npm'])}
            return installed
        if name == 'run_command':
            if long_running(args['command']):
                raise ValueError('This command starts a server that never exits, so run_command would wait for its '
                    'timeout. Use process_start (with probe_path) for servers and watchers.')
            args = {'timeout': COMMAND_TIMEOUT, **args}
            result = await self.processes.run(**args)
            if result.get('status') == 'timed_out':
                result['notice'] = (f'Stopped after {args["timeout"]}s. Servers belong in process_start; pass a larger '
                    'timeout only for a command known to be slow.')
            return self.command_observation(result, args['command'])
        if name == 'verify_application':
            files = args.get('files', [])
            for path in files:
                self.files.path(path)  # Confined, existing application path.
            # Install and check in one call; an unchanged installation is reused at once.
            installed = {'status': 'no_manifest'}
            if (self.context.workspace / 'package.json').is_file():
                installed = await self.dependencies.install()
            if installed['status'] == 'installation_failed':
                return {'kind': args['kind'], 'status': ENVIRONMENT, 'dependencies': installed, 'accepted': False,
                    'notice': 'npm install failed, so nothing was checked. Not an application verdict.'}
            if args['kind'] != 'all':
                return {**await self.checks.run(args['kind'], files), 'dependencies': installed['status']}
            kinds, checks = ('typecheck', 'build', 'backend_tests'), []
            for kind in kinds:
                checks.append(await self.checks.run(kind, files if kind == 'backend_tests' else ()))
                if checks[-1]['status'] != PASSED:
                    break  # Later checks would only repeat the same cause.
            return {'kind': 'all', 'status': checks[-1]['status'], 'checks': checks,
                'not_run': list(kinds[len(checks):]), 'dependencies': installed['status'], 'accepted': False}
        if name == 'http_request':
            return await self.checks.http_request(**args)
        if name == 'database_query':
            return await self.checks.database_query(**args)
        if name == 'interface_write':
            pages = args['pages']
            if any(not page['path'].startswith('/') for page in pages):
                raise ValueError('Page paths start with /')
            if self.catalog and any(page.get('image') and page['image'] not in self.catalog.images for page in pages):
                raise ValueError('Unknown reference image id')
            self.state.interfaces = {'pages': deepcopy(pages)}
            return {'saved': len(pages), 'notice': 'Observed interfaces; the host still verifies behavior independently.'}
        if name == 'process_start':
            args = dict(args)
            probe = args.pop('probe_path', None)
            if probe is None:
                return await self.processes.start(**args)
            if not args.get('ports') or not probe.startswith('/'):
                raise ValueError('probe_path needs a declared port and an absolute path')
            args['ready_timeout'] = args.get('ready_timeout') or 30
            status = await self.processes.start(**args)
            if status.get('ready'):
                # Start, wait and first request in one call.
                response = await self.checks.http_request(args['ports'][0], probe)
                if isinstance(response.get('body'), str):
                    response['body'] = response['body'][:4000]
                status = {**status, 'probe': {'path': probe, **response}}
            return status
        if name == 'process_stop':
            return await self.processes.stop(**args)
        if name == 'process_status':
            return self.processes.status(**args)
        if name == 'process_logs':
            return self.processes.logs(**args)
        if name == 'browser':
            from playwright.async_api import Error
            try:
                return await self.browser.action(**args)
            except Error as error:
                return {'status': 'browser_error', 'message': str(error)[:2000],
                    'observations': list(self.browser.logs), 'accepted': False}
        if name == 'view_image':
            return await view_image(self, **args)
        if name == 'git_read':
            return await self.git_read(**args)
        if name == 'run_acceptance_tests':
            if self.acceptance_runner is None:
                raise ValueError('Host acceptance is not available in this session')
            self.manual_checks = 0
            disputes = args.get('disputes') or []
            return await (self.acceptance_runner(disputes) if disputes else self.acceptance_runner())
        if name == 'delegate_tasks':
            from .delegation import delegate
            return await delegate(self, args['contract'], args['tasks'])
        if name == 'find_symbol':
            return self.files.symbol(**args)
        if name == 'read_skill':
            skills = dict(self.profile.skills)
            if args['name'] not in skills:
                raise ValueError('Unknown skill; available: ' + ', '.join(skills))
            return {'skill': args['name'], 'guide': skills[args['name']],
                'notice': 'Practice guidance; the original requirements remain the authority.'}
        raise ValueError('Tool is not implemented')

    async def git_read(self, action):
        root = self.context.workspace
        metadata = root / '.git'
        if not metadata.is_dir() or metadata.is_symlink():
            raise ValueError('This workspace has no local Git repository')
        binary = shutil.which('git')
        if not binary:
            raise EnvironmentUnavailable('Git is unavailable')
        command = {'status': ['status', '--short'], 'diff': ['diff', '--no-ext-diff', '--no-textconv'],
            'log': ['log', '-10', '--oneline', '--no-decorate']}[action]
        env = {**clean_environment(), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
        result = await asyncio.to_thread(subprocess.run,
            [binary, '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull, *command],
            cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
        return {'returncode': result.returncode,
            'output': (result.stdout + result.stderr).decode('utf-8', 'replace')[:200000]}

    async def cancel_actions(self):
        for name in tuple(self.processes.processes):
            if self.processes.processes[name]['process'].poll() is None:
                await self.processes.stop(name)

    async def aclose(self):
        try:
            await self.browser.aclose()
        finally:
            await self.processes.aclose()
