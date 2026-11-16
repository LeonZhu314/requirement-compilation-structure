"""Mandatory host verification of the real application.

Fast checks run first and stop at the first blocking stage: integrity, dependencies,
build, startup, acceptance tests, visual comparison. An incremental round reuses the
installed dependencies and the last build when their inputs are unchanged, gives the
server a new database and replays the previously failing test files first. Success is
only declared from a clean round: the execution mirror is reset to the delivered
sources, rebuilt, started as it will be deployed, and the whole suite runs.
"""

import asyncio
from hashlib import sha256
from io import BytesIO
import json
import re
import time

from PIL import Image

from infrastructure.runtime.browser import BrowserSession
from infrastructure.runtime.budget import BudgetExceeded
from infrastructure.runtime.execution import EnvironmentUnavailable
from infrastructure.runtime.files import protected, source_files
from infrastructure.runtime.model import ProviderError
from .acceptance import AcceptanceSuite, PlaywrightTooling
from .coverage import DIVERGENT, MISSING_INTERFACE, SIMILAR, UNAVAILABLE
from .results import ENVIRONMENT, FAILED, INCOMPLETE, MISSING, NO_TESTS, PASSED, clean
from . import visual

CANDIDATE, INTEGRITY = 'candidate', 'integrity_violation'
TEST_CALL = re.compile(r'\btest(?:\.only)?\s*\(')
SERVICE = 'host-verification'
MANIFEST_ERRORS = ('ETARGET', 'E404', 'EJSONPARSE', 'ERESOLVE', 'EUNSUPPORTEDPROTOCOL', 'EINVALIDPACKAGENAME')


def protected_snapshot(workspace):
    return {relative: sha256(path.read_bytes()).hexdigest() for relative, path in source_files(workspace)
        if protected(relative)}


class HostVerifier:
    def __init__(self, tools, profile, state, budget, model, input_dir=None, *, tooling=None):
        self.tools, self.profile, self.state, self.budget, self.model = tools, profile, state, budget, model
        self.settings = profile.acceptance
        self.processes, self.checks, self.registry = tools.processes, tools.checks, tools.coverage
        self.tooling = tooling or PlaywrightTooling(state.state_directory.parent / '_tooling')
        self.suite = AcceptanceSuite(self.tooling.root / 'sessions' / state.id, tools.catalog,
            self.registry, self.settings, input_dir) if tools.catalog else None
        self.protected = protected_snapshot(tools.context.workspace)
        self.start_command = ['npm', 'run', 'start']
        self.port = profile.execution.verification_port
        self.rounds = 0
        self.failed_files = set()
        self.generated = False
        self.validated_revision = None
        self.reports = []
        self._mark = budget.clock()

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.port}'

    async def verify(self, *, clean_state):
        """One verification round; returns a report whose status decides the next step."""
        self.rounds += 1
        report = {'round': self.rounds, 'clean_state': clean_state, 'status': None, 'stage': None,
            'stages': [], 'failures': [], 'stopped_services': [], 'accepted': False}
        started = self._mark = self.budget.clock()
        self._say(f'round {self.rounds} started ({"clean delivery state" if clean_state else "current sources"})')
        try:
            self.budget.reserve_verification('clean' if clean_state else 'incremental')
            await self._verify(report, clean_state)
        except EnvironmentUnavailable as error:
            report.update(status=ENVIRONMENT, diagnostic=str(error)[:1500])
        except (OSError, ValueError, RuntimeError) as error:
            if isinstance(error, BudgetExceeded):
                raise
            # A defect of the host runner is reported as such, never as an application verdict.
            report.update(status=ENVIRONMENT, diagnostic=f'verification runner error: {type(error).__name__}: {error}'[:1500])
        finally:
            try:
                if SERVICE in self.processes.processes:
                    await self.processes.stop(SERVICE)
            except Exception as error:  # Cleanup problems are reported, never hidden.
                report['cleanup_error'] = str(error)[:300]
            self.budget.add_time('verification', self.budget.clock() - started)
            report['seconds'] = round(self.budget.clock() - started, 1)
            report['source_revision'] = self.processes.mirror.revision()
            if self.registry:
                report['coverage'] = self.registry.summary()
            names = sorted(f['key'] if 'key' in f else f.get('stage', '') for f in report['failures'])
            report['fingerprint'] = sha256(json.dumps([report['status'], report['stage'], names]).encode()).hexdigest()
            report['evidence'] = self.tools.artifacts.put(json.dumps(report, ensure_ascii=False, indent=1), '.json')
            self.reports.append({**{key: report[key] for key in
                ('round', 'clean_state', 'status', 'stage', 'source_revision', 'evidence', 'fingerprint', 'seconds')},
                'stage_seconds': {stage['stage']: stage.get('seconds') for stage in report['stages']},
                # Timing facts for evaluation: when a usable application first existed.
                'finished_at': round(time.time(), 3), 'elapsed_seconds': round(self.budget.elapsed(), 1),
                'usable': any(stage['stage'] == 'startup' and stage['status'] == PASSED for stage in report['stages'])})
            self.state.verifications.append(self.reports[-1])
        report['accepted'] = report['status'] == PASSED and clean_state
        if report['accepted']:
            self.validated_revision = report['source_revision']
        return report

    def _lap(self, name):
        """Attribute the time since the previous lap to one verification phase."""
        now = self.budget.clock()
        seconds, self._mark = now - self._mark, now
        self.budget.add_time('verification.' + name, seconds)
        return round(seconds, 1)

    def _say(self, text):
        sink = getattr(self.tools, 'event_sink', None)
        if sink:
            sink('verification', {'text': text})

    def _stage(self, report, name, status, **details):
        report['stages'].append({'stage': name, 'status': status, 'seconds': self._lap(name), **details})
        self._say(f'{name}: {status} ({report["stages"][-1]["seconds"]}s)')
        report['stage'] = name
        return status

    def _fail(self, report, stage, status=FAILED, **failure):
        report['status'] = status
        report['failures'].append({'stage': stage, **failure})

    async def _verify(self, report, clean_state):
        # 1. Integrity: neither requirements nor protected tests were rewritten.
        problems = self.suite.integrity() if self.suite else []
        current = protected_snapshot(self.tools.context.workspace)
        problems += [f'protected file changed: {path}' for path in sorted(current.keys() | self.protected.keys())
            if current.get(path) != self.protected.get(path)]
        catalog = self.tools.catalog
        if catalog:
            source = catalog.directory / 'requirements.yaml'
            if not source.is_file() or sha256(source.read_bytes()).hexdigest() != catalog.source_sha256:
                problems.append('original requirements.yaml changed during the run')
        if self._stage(report, 'integrity', FAILED if problems else PASSED) == FAILED:
            return self._fail(report, 'integrity', INTEGRITY, problems=problems)
        if self.suite:
            await self.tooling.ensure()
            self.suite.assemble()
            self._lap('test_runner_setup')

        # 2. State and dependencies.
        mirror = self.processes.mirror
        if clean_state:
            report['stopped_services'] = [name for name in await self.processes.stop_all() if name != SERVICE]
            mirror.reset(keep=('.npm-cache',) if self.settings.clean_install else ('node_modules', '.npm-cache'))
        else:
            mirror.pull()
            mirror.push()
        if self.registry:
            self.registry.invalidate(mirror.revision())
        installed = await self.tools.dependencies.install()
        if installed['status'] == 'installation_failed':
            log = self.checks.log(installed.get('diagnostic', {}))
            manifest = any(sign in log for sign in MANIFEST_ERRORS)
            self._stage(report, 'dependencies', FAILED if manifest else ENVIRONMENT)
            return self._fail(report, 'dependencies', FAILED if manifest else ENVIRONMENT,
                errors=[clean(log[-2000:], 2000)], artifact=installed.get('diagnostic', {}).get('artifact'))
        self._stage(report, 'dependencies', PASSED, reuse=installed['status'])

        # 3. Build: never reused for the clean delivery state.
        build = await self.checks.run('build', use_cache=not clean_state)
        self._stage(report, 'build', build['status'], cached=build['cached'], artifact=build['artifact'])
        if build['status'] != PASSED:
            return self._fail(report, 'build', ENVIRONMENT if build['status'] == ENVIRONMENT else FAILED,
                errors=[build.get('output_tail', '')], artifact=build['artifact'])

        # 4. Start the real server; an incremental round gets its own new database.
        env = {'PORT': str(self.port), 'NODE_ENV': 'production'}
        if not clean_state:
            env['DATABASE_URL'] = f'/workspace/.verification/round-{self.rounds}/app.db'
        started = await self.processes.start(SERVICE, self.start_command, ports=[self.port], env=env, restart=True,
            ready_timeout=self.settings.startup_timeout_seconds, host=True)
        if not started.get('ready'):
            logs = self.processes.logs(SERVICE)
            self._stage(report, 'startup', FAILED, artifact=logs['artifact'])
            return self._fail(report, 'startup', errors=['The built application did not answer HTTP on its PORT within '
                f'{self.settings.startup_timeout_seconds}s.', clean(logs['content'][-2000:], 2000)], artifact=logs['artifact'])
        self._stage(report, 'startup', PASSED)

        # 5. Independent acceptance tests.
        await self._acceptance(report, clean_state)
        if report['status'] in {ENVIRONMENT, INTEGRITY}:
            return
        # 6. Visual conformance is a separate dimension, measured on the full round.
        if clean_state and self.registry and self.registry.visual and self.settings.visual != 'off':
            await self._visual(report)
        if report['status'] is None:
            report['status'] = PASSED if clean_state else CANDIDATE

    async def _compile(self, relative):
        result = await self.tooling.run(self.suite.directory, [relative], self.base_url, 120, list_only=True)
        if result['status'] == ENVIRONMENT:
            raise EnvironmentUnavailable('; '.join(result['errors']))
        return None if result.get('returncode') == 0 and not result['errors'] else \
            '; '.join(result['errors']) or result.get('output_tail', 'The test file does not compile')

    async def _acceptance(self, report, clean_state):
        if not self.suite:
            self._stage(report, 'acceptance', MISSING, reason='No requirements input is attached')
            return self._fail(report, 'acceptance', MISSING, errors=['No independent acceptance is available'])
        if not self.generated:
            # Generated once and then kept: later rounds reuse the recorded version.
            self.generated = True
            if self.settings.generate and self.suite.uncovered():
                try:
                    self._say(f'generating tests for {len(self.suite.uncovered())} uncovered scenarios')
                    interfaces = await self._observe()
                    report['generated_tests'] = await self.suite.generate(self.model, self.budget, interfaces, self._compile)
                    self._lap('test_generation')
                except (ProviderError, BudgetExceeded) as error:
                    report['generation_error'] = str(error)[:300]
        specs = self.suite.specs()
        if not specs:
            self._stage(report, 'acceptance', MISSING)
            return self._fail(report, 'acceptance', MISSING, errors=['No external test was supplied and none could be '
                'generated: functional behavior is unverified.'])
        focus = sorted(self.failed_files & set(specs)) if not clean_state else []
        files = focus or specs
        self._say(f'running {len(files)} test files')
        result = await self._run(files)
        if result['status'] == ENVIRONMENT:
            self._stage(report, 'acceptance', ENVIRONMENT)
            return self._fail(report, 'acceptance', ENVIRONMENT, errors=result['errors'] or [result.get('output_tail', '')])
        tests = self.suite.annotate(result['tests'])
        # A generated test may be wrong; an external test never is reviewed or changed.
        reviewed = False
        suspects = sorted({t['file'] for t in tests if t['status'] == FAILED and t['origin'] == 'generated'})
        if suspects:
            # Independent files: reviewed at once, then the corrected ones rerun together.
            self._say(f'reviewing {len(suspects)} failing generated test files')

            async def review(relative):
                failing = [t for t in tests if t['file'] == relative and t['status'] == FAILED]
                return relative, await self.suite.review(self.model, self.budget, relative, failing, self._compile)
            corrected = []
            for outcome in await asyncio.gather(*(review(relative) for relative in suspects), return_exceptions=True):
                if isinstance(outcome, (ProviderError, BudgetExceeded)):
                    report['review_error'] = str(outcome)[:300]
                elif isinstance(outcome, BaseException):
                    raise outcome
                elif outcome[1]:
                    corrected.append(outcome[0])
            if corrected:
                reviewed = True
                self._say(f'rerunning {len(corrected)} corrected test files')
                rerun = await self._run(corrected)
                tests = [t for t in tests if t['file'] not in corrected] + self.suite.annotate(rerun['tests'])
                result['errors'] += rerun['errors']
        complete = files == specs
        evidence = self.tools.artifacts.put(json.dumps({'tests': tests, 'errors': result['errors']},
            ensure_ascii=False, indent=1), '.json')
        if self.registry:
            self.registry.record_functional(tests, self.processes.mirror.revision(), evidence, complete=complete)
        failed = [t for t in tests if t['status'] not in {PASSED}]
        self.failed_files = {t['file'] for t in failed} | ({f for f in self.failed_files if f not in files})
        counts = {'passed': sum(t['status'] == PASSED for t in tests), 'failed': sum(t['status'] == FAILED for t in tests),
            'other': sum(t['status'] not in {PASSED, FAILED} for t in tests), 'files': len(files), 'complete': complete}
        status = FAILED if failed or result['errors'] else PASSED if tests else NO_TESTS
        self._stage(report, 'acceptance', status, artifact=evidence, counts=counts, reviewed=reviewed,
            suite_version=self.suite.version(), focus=bool(focus))
        if result['status'] in {INCOMPLETE} and not failed:
            return self._fail(report, 'acceptance', errors=['Skipped or flaky tests are not accepted'])
        if status == NO_TESTS:
            return self._fail(report, 'acceptance', MISSING, errors=['The suite executed no test'])
        if status == FAILED:
            report['status'] = FAILED
            for test in failed:
                report['failures'].append({'stage': 'acceptance', 'key': test['key'], 'title': test['title'],
                    'covers': test['covers'], 'origin': test['origin'], 'status': test['status'], 'errors': test['errors']})
            for error in result['errors']:
                report['failures'].append({'stage': 'acceptance', 'key': 'suite-error', 'errors': [error]})
        if not complete and status == PASSED:
            report['focus_only'] = True

    async def _run(self, files):
        # The suite deadline grows with the number of tests: the setting is a floor, each
        # test is still bounded by test_timeout_seconds.
        tests = 0
        for relative in files:
            try:
                tests += len(TEST_CALL.findall((self.suite.directory / relative).read_text(encoding='utf-8')))
            except (OSError, UnicodeError):
                tests += 1
        timeout = max(self.settings.suite_timeout_seconds, 120 + tests * self.settings.test_timeout_seconds)
        return await self.tooling.run(self.suite.directory, files, self.base_url, timeout, self.settings.test_timeout_seconds,
            workers=self.settings.workers)

    async def _observe(self):
        """Routes and accessible names of the running application, for locating only."""
        pages = self.state.interfaces.get('pages', [])
        paths = list(dict.fromkeys(['/', *(page['path'] for page in pages)]))[:8]
        snapshots = {}
        browser = BrowserSession(self.processes, self.tools.artifacts)
        try:
            for path in paths:
                try:
                    snapshots[path] = (await browser.action('open', url=self.base_url + path))['dom'][:3000]
                except EnvironmentUnavailable:
                    raise
                except Exception as error:
                    snapshots[path] = 'unavailable: ' + str(error)[:200]
        except EnvironmentUnavailable as error:
            snapshots = {'unavailable': str(error)[:300]}
        finally:
            await browser.aclose()
        return {'declared_pages': pages, 'accessibility_snapshots': snapshots}

    async def _visual(self, report):
        revision = self.processes.mirror.revision()
        declared = {page['image']: page['path'] for page in self.state.interfaces.get('pages', []) if page.get('image')}
        results = {}
        browser = BrowserSession(self.processes, self.tools.artifacts)
        try:
            for image in self.registry.visual:
                if image not in declared:
                    self.registry.record_visual(image, MISSING_INTERFACE, revision,
                        reason='No page path was declared for this reference (interface_write)')
                    results[image] = {'status': MISSING_INTERFACE}
                    continue
                try:
                    results[image] = await self._compare(browser, image, declared[image], revision)
                except EnvironmentUnavailable as error:
                    self.registry.record_visual(image, UNAVAILABLE, revision, reason=str(error)[:300])
                    results[image] = {'status': UNAVAILABLE, 'reason': str(error)[:300]}
                except Exception as error:
                    self.registry.record_visual(image, UNAVAILABLE, revision, reason=str(error)[:300])
                    results[image] = {'status': UNAVAILABLE, 'reason': f'{type(error).__name__}: {error}'[:300]}
        finally:
            await browser.aclose()
        report['visual'] = results
        statuses = {item['status'] for item in results.values()}
        self._stage(report, 'visual', DIVERGENT if DIVERGENT in statuses else
            SIMILAR if statuses == {SIMILAR} else UNAVAILABLE, mode=self.settings.visual)
        if self.settings.visual == 'require' and report['status'] is None and statuses != {SIMILAR}:
            status = FAILED if DIVERGENT in statuses else MISSING
            for image, item in results.items():
                if item['status'] != SIMILAR:
                    self._fail(report, 'visual', status, key='visual:' + image, covers=[self.registry.visual[image]['requirement']],
                        errors=[json.dumps(item, ensure_ascii=False)[:900]])

    async def _compare(self, browser, image, path, revision):
        reference = self.tools.catalog.resource_data[image]
        with Image.open(BytesIO(reference)) as source:
            width, height = max(320, min(source.width, 1920)), max(320, min(source.height, 2560))
        await browser.action('resize', width=width, height=height)
        browser.logs.clear()
        await browser.action('open', url=self.base_url + path)
        try:
            await browser.page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        capture = await browser.page.screenshot(full_page=True)
        broken = [entry['text'][:200] for entry in browser.logs if entry['kind'] == 'requestfailed'
            or (entry['kind'] == 'response' and entry['text'][:1] in '45'
                and entry['text'].split('?')[0].lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.css', '.woff2', '.woff')))]
        metrics = visual.compare(reference, capture)
        status = visual.verdict(metrics, self.settings.visual_threshold, broken)
        evidence = self.tools.artifacts.put(capture, '.png')
        details = {'path': path, 'metrics': metrics, 'broken_resources': broken[:8], 'viewport': [width, height],
            'review': 'not_requested'}
        if self.profile.image_mode != 'disabled':
            details['review'] = 'unavailable'
            model = None
            try:
                self.budget.reserve_request('visual_review', final=True)
                files = []
                for data in (reference, capture):
                    with Image.open(BytesIO(data)) as source:
                        picture = source.convert('RGB')
                        picture.thumbnail((1600, 1600))
                        output = BytesIO()
                        picture.save(output, 'JPEG', quality=85)
                    identity = self.tools.artifacts.put(output.getvalue(), '.jpg')
                    files.append((self.tools.artifacts.path(identity), sha256(output.getvalue()).hexdigest()))
                model = self.tools.vision_factory(self.profile.vision)
                judged, usage = await visual.review(model, *files[0], *files[1])
                self.state.usage.append(usage)
                self.budget.record_usage(usage)
                if judged:
                    # The model judges text and structure; broken resources stay divergent.
                    status = DIVERGENT if broken else judged['verdict']
                    details.update(review='completed', differences=judged['differences'])
            except (ProviderError, BudgetExceeded, ValueError, OSError) as error:
                details['review_error'] = str(error)[:200]
            finally:
                if model is not None:
                    await model.aclose()
        self.registry.record_visual(image, status, revision, evidence, **details)
        return {'status': status, 'evidence': evidence, **details}
