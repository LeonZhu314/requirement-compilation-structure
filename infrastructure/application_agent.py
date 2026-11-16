"""Project-owned application agent: one persistent session per generated application."""

import asyncio
from pathlib import Path
import json
import time

from infrastructure.runtime.composer import compose
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.loop import AgentLoop
from infrastructure.runtime.messages import Message
from infrastructure.runtime.model import OpenAIModel
from infrastructure.runtime.persistence import (ResumeError, RunStore, WorkspaceCheckpoints, fingerprint_input,
    fingerprint_profile, restore_session, session_payload)
from infrastructure.runtime.state import SessionState
from infrastructure.runtime.tools import ToolContext, ToolRegistry
from infrastructure.runtime.requirements import RequirementCatalog
from infrastructure.shared.project.initialize import initialize_project

DEFAULT_TASK = ('Implement the complete application from the original requirements. Choose the '
    'order of work, maintain an adaptable todo list, preserve parent constraints, and verify usable '
    'workflows. Changes may span SQL, API, UI, styles and navigation in one task.')


class ApplicationAgent:
    """A new session starts with empty working state; `resume` continues a saved one.

    Session state lives under `state_root` (default: beside the workspace), never in
    the application sources, and is never shared between two sessions.
    """

    def __init__(self, workspace, *, profile=None, model=None, input_dir=None, port=3000,
            state_root=None, resume=None):
        self.profile = profile or load_profile()
        workspace = Path(workspace).expanduser().resolve()
        self.catalog = RequirementCatalog(input_dir) if input_dir is not None else None
        self.input_dir = Path(input_dir).resolve() if input_dir is not None else None
        self.port = port
        if self.catalog and (self.catalog.directory.is_relative_to(workspace) or workspace.is_relative_to(self.catalog.directory)):
            raise ValueError('Input requirements and application workspace must be disjoint directories')
        state_root = Path(state_root).expanduser().resolve() if state_root else workspace.parent / '.agent-state'
        if self.input_dir and state_root.is_relative_to(self.input_dir):
            raise ValueError('Session state cannot be stored inside the input directory')
        if resume is not None and not (state_root / resume / 'session.json').is_file() \
                and not (state_root / resume / 'session.json.bak').is_file():
            raise ResumeError(f'No saved session {resume!r} under {state_root}')
        workspace.mkdir(parents=True, exist_ok=True)
        if self.catalog:
            initialize_project(workspace, port=port)
        self.state = SessionState(workspace, state_root=state_root, **({'id': resume} if resume else {}))
        self.store = RunStore(self.state.state_directory, (self.profile.llm.api_key, self.profile.vision.api_key))
        self.tools = ToolRegistry(ToolContext(workspace, self.state.id, self.profile.tools),
            self.state, self.profile, self.catalog)
        self.loop = AgentLoop(self.state, model or OpenAIModel(self.profile.llm), self.tools, self.profile)
        self.loop.on_event, self.loop.on_save = self._event, self.save
        self.tools.event_sink = self._event
        self.checkpointer = WorkspaceCheckpoints(workspace)
        self.checkpoints = []
        self.fingerprints = {'input': fingerprint_input(self.input_dir) if self.input_dir else None,
            'profile': fingerprint_profile(self.profile)}
        self._initial_context_sent = False
        self._resume_notice = None
        self._saved_acceptance = None
        self.verifier = None
        if resume:
            self._restore()
        else:
            self.state.messages.append(Message('system', compose(self.profile)))

    # ----- persistence ---------------------------------------------------------------

    def _event(self, kind, data):
        text = json.dumps(data, ensure_ascii=False, default=str)
        self.store.event(kind, data if len(text) <= 4000 else {'truncated': text[:4000]})

    def save(self):
        acceptance = None
        if self.verifier is not None:
            acceptance = {'rounds': self.verifier.rounds, 'generated': self.verifier.generated,
                'failed_files': sorted(self.verifier.failed_files), 'validated_revision': self.verifier.validated_revision,
                'suite_version': self.verifier.suite.version() if self.verifier.suite else None}
        elif self._saved_acceptance:
            acceptance = self._saved_acceptance
        self.store.write_json('session.json', session_payload(self.state, self.loop.budget,
            {**self.fingerprints, 'workspace_revision': self.tools.processes.mirror.revision()},
            {'checkpoints': self.checkpoints, 'port': self.port, 'acceptance': acceptance,
             'consulted': sorted(self.catalog.consulted) if self.catalog else [],
             'viewed': sorted(self.catalog.viewed) if self.catalog else []}))

    def _restore(self):
        saved = self.store.read_json('session.json')
        for key, label in (('input', 'input requirements, references or tests'), ('profile', 'profile instructions or policy')):
            if saved['fingerprints'].get(key) != self.fingerprints[key]:
                raise ResumeError(f'Cannot resume session {self.state.id}: the {label} changed since it was saved. '
                    'Start a new run for the changed inputs.')
        restore_session(saved, self.state, self.loop.budget)
        self.checkpoints = saved.get('checkpoints', [])
        self._saved_acceptance = saved.get('acceptance')
        self._initial_context_sent = True
        if self.catalog:
            self.catalog.consulted.update(saved.get('consulted', []))
            self.catalog.viewed.update(saved.get('viewed', []))
        self.loop.context.memory = next((m for m in self.state.messages
            if m.role == 'assistant' and m.content.startswith('Working memory:')), None)
        notes = ['This session was resumed from its saved state. Earlier verification results and cached checks '
            'are not carried over; re-check what you rely on.']
        if saved['status'] in {'running', 'cancelled'}:
            notes.append('The previous run was interrupted: a command or write in progress may have taken partial '
                'effect. Inspect the files and services before continuing.')
        if saved['fingerprints'].get('workspace_revision') != self.tools.processes.mirror.revision():
            notes.append('The workspace files differ from the saved state; read the current files before editing.')
        notes.append('No service is running: restart the ones you need.')
        self._resume_notice = ' '.join(notes)
        self.state.status = 'ready'
        self._event('resumed', {'saved_status': saved['status'], 'requests': self.state.requests})

    def checkpoint(self, label):
        """Explicit workspace restore point; independent of resuming the conversation."""
        commit = self.checkpointer.create(label)
        entry = {'label': label, 'commit': commit, 'time': round(time.time(), 3),
            'workspace_revision': self.tools.processes.mirror.revision(), 'requests': self.state.requests}
        self.checkpoints.append(entry)
        return entry

    def record_outcome(self, outcome):
        self.save()
        self.store.write_json('run-summary.json', {'format_version': 1, 'session_id': self.state.id,
            'outcome': outcome.to_dict(), 'fingerprints': self.fingerprints, 'checkpoints': self.checkpoints,
            'model': self.profile.llm.model, 'reasoning': self.profile.llm.reasoning,
            'state_directory': str(self.state.state_directory), 'details': {'session': 'session.json',
                'events': 'events.jsonl', 'artifacts': 'artifacts/', 'process_logs': 'process-logs/'}})

    # ----- work ----------------------------------------------------------------------

    async def generate(self, task=None, *, tooling=None):
        """Work, then let the host verify; failures return to this same session for repair."""
        from infrastructure.verification.driver import FinalizationDriver
        from infrastructure.verification.verifier import HostVerifier
        if self.verifier is None:
            self.verifier = HostVerifier(self.tools, self.profile, self.state, self.loop.budget, self.loop.model,
                self.input_dir, tooling=tooling)
            if self._saved_acceptance:
                self.verifier.rounds = self._saved_acceptance['rounds']
                self.verifier.generated = self._saved_acceptance['generated']
                self.verifier.failed_files = set(self._saved_acceptance['failed_files'])
        self.tools.acceptance_runner = self.acceptance_now
        warm = asyncio.create_task(self.warm_up())
        try:
            outcome = await FinalizationDriver(self, self.verifier).run(task)
            # By now verification has used the same installations: this returns at once.
            await asyncio.gather(warm, return_exceptions=True)
            return outcome
        finally:
            if not warm.done():  # Interrupted: never leave an npm process running behind.
                warm.cancel()
                await asyncio.gather(warm, return_exceptions=True)

    async def acceptance_now(self):
        """A host verification round on request of the agent (fresh database, all tests,
        generated tests reviewed). The final acceptance still comes from the driver."""
        from infrastructure.verification.driver import feedback
        report = await self.verifier.verify(clean_state=False)
        self.save()
        passed = report['status'] in {'passed', 'candidate'}
        return {'status': 'passed' if passed else report['status'], 'stage': report['stage'],
            'report': 'Every acceptance test passed. Reply with your completion summary.' if passed
                else feedback(report, repeated=False, remaining={}), 'accepted': False}

    async def warm_up(self):
        """Act while thinking (cf. PASTE, 2026): work the host will need anyway starts at
        once instead of waiting for the agent or the first verification. The template
        dependencies are installed from the shipped lockfile and the acceptance test runner
        is prepared while the model reads the requirements. Both are reused later; a
        failure here is only recorded, the normal path retries it."""
        started = time.monotonic()
        steps = {}
        for name, action in (('dependencies', self.tools.dependencies.install),
                ('test_runner', self.verifier.tooling.ensure if self.verifier and self.verifier.suite else None)):
            if action is None:
                continue
            try:
                result = await action()
                steps[name] = (result or {}).get('status', 'ready') if isinstance(result, dict) else 'ready'
            except asyncio.CancelledError:
                raise
            except Exception as error:  # Environment problems surface again where they matter.
                steps[name] = f'failed: {type(error).__name__}: {str(error)[:200]}'
        self._event('warm_up', {'steps': steps, 'seconds': round(time.monotonic() - started, 1)})

    def _building_blocks(self):
        """The workspace's own guide to its generic code, given once in the first message so
        the agent neither reads it with a request nor rewrites what already exists."""
        guide = self.state.workspace / 'BUILDING_BLOCKS.md'
        try:
            text = guide.read_text(encoding='utf-8-sig').strip() if guide.is_file() else ''
        except (OSError, UnicodeError):
            return ''
        return f'\n\nWorkspace building blocks (BUILDING_BLOCKS.md):\n{text[:8000]}' if text else ''

    async def run(self, task=None):
        if self.catalog and not self._initial_context_sent:
            task = (task or DEFAULT_TASK) + (
                '\nDelivery contract: from a clean copy, `npm install`, `npm run build` and `npm run start` must '
                f'serve the UI and API on the PORT environment variable (default {self.port}) with a newly '
                'initialized database that already contains every record the requirements describe as existing.'
                ) + self._building_blocks() + '\n\nOriginal task context:\n' + json.dumps(self.catalog.initial_context(), ensure_ascii=False)
            self._initial_context_sent = True
        if self._resume_notice:
            task = self._resume_notice + '\n\n' + (task or 'Continue the work from where it stopped.')
            self._resume_notice = None
        return await self.loop.run(task)

    def cancel(self):
        self.loop.cancel()

    async def aclose(self):
        await self.loop.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()
