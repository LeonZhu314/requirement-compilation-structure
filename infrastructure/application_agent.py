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

def visual_differences(report):
    """Structural differences between captured pages and their references, as one instruction."""
    lines = []
    for image, item in (report.get('visual') or {}).items():
        if item.get('status') == 'divergent' and item.get('differences'):
            lines.append(f'- {image} ({item.get("path")}): ' + ' | '.join(item['differences'][:6]))
        elif item.get('status') == 'missing_interface':
            lines.append(f'- {image}: no page declared for it with interface_write.')
    if not lines:
        return ''
    return ('Every acceptance test passed. Your pages still differ from the reference images:\n' + '\n'.join(lines[:10])
        + '\nFix the structure and visible texts that differ (layout regions, navigation, section order, labels), '
        'without changing behavior the tests verified, then call run_acceptance_tests again. Ignore differences in '
        'photos, icons or exact colors.')


REPEATED_FAILURE = ('\nThis exact failure has now come back {count} times in a row. Re-read the requirement it '
    'names. If your application already does what the requirement states, the generated test is probably wrong: '
    'do not change correct behavior or the requirement\'s controls (for example a password field must stay '
    'hidden) to satisfy it. Look at what the page showed when it failed (page_alerts, the page in the evidence): if '
    'the test entered data a requirement rejects or demands something no requirement states, call '
    'run_acceptance_tests with disputes naming the scenario and the requirement text the test contradicts.')

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
        self._last_failure, self._same_failure = None, 0
        self._pending_attachments = None
        self._visual_feedback_given = False
        self._disputed_shown = False
        self.stuck = False
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

    async def acceptance_now(self, disputes=()):
        """A host verification round on request of the agent (fresh database, all tests,
        generated tests reviewed). The final acceptance still comes from the driver.
        `disputes`: the agent's arguments that some generated tests are wrong; each is judged
        by a review before the round, and a corrected test is run even on unchanged sources."""
        from infrastructure.verification.driver import (NO_PROGRESS_REQUESTS, disputed_review, feedback,
            requests_without_progress, rounds_without_progress)
        settings = self.profile.acceptance
        claims = await self.verifier.review_claims(list(disputes)) if disputes else []
        corrected = any(claim['outcome'] == 'test corrected' for claim in claims)
        last = self.verifier.last_report
        if last and last['status'] in {'failed', 'candidate'} and not corrected \
                and last['source_revision'] == self.tools.processes.mirror.revision():
            # No source changed since that round: its tests would fail the same way (real run:
            # three rounds of 7 minutes on one revision). The report is given again at once.
            report, unchanged = last, True
        else:
            # The first round deploys as the benchmark does (sources only, rebuilt, default
            # database): a defect of the delivery itself shows up while it can still be fixed.
            first = not any(past['clean_state'] for past in self.verifier.reports)
            visual = settings.visual_feedback and not self._visual_feedback_given
            report = await self.verifier.verify(clean_state=first, visual=visual)
            unchanged = False
        self.save()
        passed = report['status'] in {'passed', 'candidate'}
        # A real run repeated the same failing result 8 times in a row, changing the application
        # in ways the requirements forbid to satisfy one generated test.
        fingerprint = report.get('fingerprint')
        self._same_failure = (self._same_failure + 1) if not passed and fingerprint == self._last_failure else 0
        self._last_failure = None if passed else fingerprint
        coverage = report.get('coverage') or {}
        complete = passed and not coverage.get('omissions') \
            and set(coverage.get('functional', {})) <= {'passed', 'disputed'}
        differences = visual_differences(report) if passed and settings.visual_feedback \
            and not self._visual_feedback_given else ''
        if passed and not differences and report.get('disputed') and not self._disputed_shown:
            # Set-aside tests are shown once before the end: in a real run 2 of 4 of them were
            # application defects (a missing avatar, a duplicate "Log in" button).
            self._disputed_shown = True
            differences = disputed_review(report)
        if passed and report.get('visual') is not None:
            self._visual_feedback_given = True
        if complete and self.profile.acceptance.finish_on_pass and not differences:
            # Every scenario has a passing test: the host takes over for the final clean round.
            self.tools.finish_requested = True
        # The same failures for the fifth time in a row: more rounds do not change them (real
        # run: 17 rounds on a defect of the generated test). The application is delivered as it is.
        stuck = not passed and self._same_failure > self.profile.budget.stagnation_repeats
        # Failures that change a little every round (16, 17, 16, 17, 18 passing) never repeat
        # exactly: the run went on for 99 minutes. No new passing test for a few rounds stops it.
        idle = rounds_without_progress(self.verifier.reports)
        stalled = not passed and not unchanged and (idle >= self.profile.budget.stagnation_repeats or (idle and
            requests_without_progress(self.verifier.reports, self.state.requests) >= NO_PROGRESS_REQUESTS))
        if stuck or stalled:
            self.stuck = True
            self.tools.finish_requested = True
            self.tools.finish_note = (f'The same acceptance failures came back {self._same_failure + 1} times in a row'
                if stuck else f'No new acceptance test passed in the last {idle} verification rounds') \
                + '; the host ended the work turn.'
            stuck = True
        return {'status': 'passed' if passed else report['status'], 'stage': report['stage'],
            **({'disputes': claims} if claims else {}),
            'report': ('Every acceptance test passed and every scenario is covered. The host now ends your work '
                'turn and runs the final verification from a clean state.' if self.tools.finish_requested
                else differences or 'Every acceptance test passed. Reply with your completion summary.') if passed
                else (f'No source file changed since verification round {report["round"]}: the host did not run the '
                    'tests again. Change the application before calling run_acceptance_tests.\n' if unchanged else '')
                    + feedback(report, repeated=self._same_failure > 0, remaining={})
                    + (REPEATED_FAILURE.format(count=self._same_failure + 1) if self._same_failure >= 2 else '')
                    + ('\nThe host now ends your work turn and delivers the application as it is.' if stuck else ''),
            'accepted': False}

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

    async def describe_references(self):
        """All reference images described at once, before the first request: the agent used
        to spend its first minutes viewing them one response at a time."""
        from infrastructure.runtime.images import view_image
        images = list(self.catalog.images)[:12] if self.catalog else []
        if not images or self.profile.image_mode != 'fallback' or 'view_image' not in self.profile.tools:
            return ''
        before = len(self.state.usage)
        with self.loop.budget.timed('tools'):
            results = await asyncio.gather(*(view_image(self.tools, identity) for identity in images),
                return_exceptions=True)
        for usage in self.state.usage[before:]:
            self.loop.budget.record_usage(usage)
        lines = []
        for identity, result in zip(images, results):
            if isinstance(result, dict) and result.get('description'):
                page = (self.catalog.images[identity][1] or {}).get('page', '')
                lines.append(f'- {identity}' + (f' (page {page})' if page else '') + f': {result["description"][:3000]}')
        self._event('references_described', {'images': len(images), 'described': len(lines)})
        return ('\n\nReference images, already described by the vision model (view_image returns the same '
            'description; ask it a specific question only for a detail missing here):\n' + '\n'.join(lines)) if lines else ''

    async def run(self, task=None):
        if self.catalog and not self._initial_context_sent:
            task = (task or DEFAULT_TASK) + (
                '\nDelivery contract: from a clean copy, `npm install`, `npm run build` and `npm run start` must '
                f'serve the UI and API on the PORT environment variable (default {self.port}) with a newly '
                'initialized database that already contains every record the requirements describe as existing.'
                ) + self._building_blocks() + await self.describe_references() + '\n\nOriginal task context:\n' + json.dumps(self.catalog.initial_context(
                # Kept whole while they fit: a catalogue forces hundreds of reads that compaction erases.
                max_chars=int((self.profile.context_ceiling_bytes or self.profile.max_context_bytes) * 0.3)), ensure_ascii=False)
            self.tools.requirements_inline = self.catalog.inline
            self._initial_context_sent = True
            self._pending_attachments = self.attach_references()
        if self._resume_notice:
            task = self._resume_notice + '\n\n' + (task or 'Continue the work from where it stopped.')
            self._resume_notice = None
        attachments = self._pending_attachments
        self._pending_attachments = None
        result = await self.loop.run(task, attachments)
        if attachments and result.status == 'provider_error' and self.loop.budget.requests['main'] <= 1:
            # The provider refused images in the main conversation: continue with the descriptions.
            self.state.messages[:] = [m for m in self.state.messages if not m.images]
            self._event('reference_images', {'attached': False, 'reason': 'provider refused images'})
            result = await self.loop.run('Continue the task; the reference images are described above.')
        return result

    def attach_references(self):
        """The reference images, reduced, as one message right after the task."""
        from hashlib import sha256
        from io import BytesIO
        from PIL import Image, ImageOps
        from infrastructure.runtime.messages import ImageAttachment
        if not self.catalog or self.profile.reference_images != 'attach' or self.profile.image_mode == 'disabled':
            return None
        attachments, names = [], []
        for identity in list(self.catalog.images)[:8]:
            try:
                with Image.open(BytesIO(self.catalog.resource_data[identity])) as source:
                    picture = ImageOps.exif_transpose(source).convert('RGB')
                    picture.thumbnail((1280, 1280))
                    output = BytesIO()
                    picture.save(output, 'JPEG', quality=80)
            except (OSError, ValueError):
                continue
            data = output.getvalue()
            artifact = self.tools.artifacts.put(data, '.jpg')
            attachments.append(ImageAttachment(str(self.tools.artifacts.path(artifact)), 'image/jpeg', sha256(data).hexdigest()))
            page = (self.catalog.images[identity][1] or {}).get('page', '')
            names.append(identity + (f' (page {page})' if page else ''))
        if not attachments:
            return None
        self._event('reference_images', {'attached': len(attachments)})
        return ('Reference images, in this order: ' + ', '.join(names) + '. Reproduce their page structure (header, '
            'navigation, sidebars, columns, ordering of sections) and visible texts where the requirements do not say '
            'otherwise.', attachments)

    def cancel(self):
        self.loop.cancel()

    async def aclose(self):
        await self.loop.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()
