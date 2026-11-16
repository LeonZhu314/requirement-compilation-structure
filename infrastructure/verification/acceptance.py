"""Independent acceptance suite, isolated from the workspace the agent can modify.

The oracle is the original requirements (scenarios, parent constraints, startup
data) and the external tests supplied with the task. Interfaces observed in the
running application only help locate elements: they never define correct behavior.
Supplementary tests are generated only for scenarios no independent test covers,
kept under a recorded version, and reviewed only against the requirement or the
environment, never adapted to an incorrect application output.
"""

import asyncio
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from infrastructure.runtime.execution import EnvironmentUnavailable, clean_environment
from infrastructure.runtime.messages import Message
from infrastructure.utils.processes import npm_command, process_options, stop_process
from .coverage import token
from infrastructure.requirements.contract import locator
from .results import ENVIRONMENT, clean, parse_playwright

SPEC = re.compile(r'\.(spec|test)\.[cm]?[jt]s$')
TITLE = re.compile(r'''\btest(?:\.(?!skip|fixme|only|describe)\w+)?\(\s*(['"`])((?:\\.|(?!\1).)+)\1''')
FENCE = re.compile(r'```(?:ts|typescript)?\s*\n(.*?)```', re.DOTALL)
FORBIDDEN = re.compile(r'\.(skip|only|fixme)\s*\(|process\.env|child_process|\brequire\s*\(')
IMPORT = re.compile(r'''^\s*import\s[^;]*?from\s*['"]([^'"]+)['"]''', re.MULTILINE)

CONFIG = '''// Host-owned configuration; the application under test cannot change it.
const { defineConfig } = require("@playwright/test");
if (!process.env.ACCEPTANCE_BASE_URL) throw new Error("The host acceptance runner sets ACCEPTANCE_BASE_URL");
module.exports = defineConfig({
  testDir: ".", outputDir: "./results/output", retries: 0,
  workers: Number(process.env.ACCEPTANCE_WORKERS || 1), fullyParallel: process.env.ACCEPTANCE_WORKERS > 1,
  forbidOnly: true, timeout: Number(process.env.ACCEPTANCE_TEST_TIMEOUT || 30000), expect: { timeout: 5000 },
  reporter: [["json"]],
  use: { baseURL: process.env.ACCEPTANCE_BASE_URL, browserName: "chromium", headless: true,
    screenshot: "only-on-failure", trace: "off" },
});
'''

GENERATION_CONCURRENCY = 4

AUTHOR = '''Write independent acceptance tests for ONE original requirement.
Derive every expected result from original_requirement, its Given/When/Then scenarios and its
ancestor constraints. observed_interfaces lists routes and accessible names seen in the running
application: use them only to locate elements. They are observations, not expectations; when the
requirement names a control, locate it by that required role/name even if it was not observed, so a
missing or misnamed control fails. Never weaken an outcome to match what the application shows.
required_locators are elements the requirement names with an explicit role: locate them exactly
that way (same role, same full name, exact: true), never by text or CSS instead.
The tests run in parallel against one shared database that keeps every record created by other
tests: give created data unique names and never assume a list contains only your records.
Assert a URL, redirect target or route only when the requirement states it; otherwise check the
visible outcome (headings, texts, list entries). Other tests of the same application cover other
requirements, so never assume a navigation the requirement leaves open.

Write one Playwright Test file in TypeScript: import { test, expect } from '@playwright/test'.
The tests are black-box: drive the real application through the browser with relative URLs
(a baseURL is configured), without mocks, injected state or database access. Data that the
requirement states as already existing is provided by the application's startup data; create any
other Given through the user interface with unique values (randomUUID from node:crypto), because
all tests of a run share one database.

Write exactly one test per entry of scenarios_to_cover; its title starts with the scenario id
followed by a colon. Cover the listed required_aspects of each scenario: rejections must verify the
rejected outcome did not take effect, identity checks need two distinct identities, refresh checks
must reload the page. Assert user-visible business outcomes, not styling or unspecified internals.
Do not use test.skip, test.only, test.fixme, fixed sleeps, process.env or other modules.
Reply with the complete file in a single ```ts fenced block and nothing else.'''

REVIEWER = '''Review a generated acceptance test that failed against the application.
The original requirement is the authority. Decide whether the TEST is wrong: it contradicts the
requirement, demands something the requirement does not state, or misuses the test environment
(for example a locator that cannot match a correctly named control, or data that is not unique).
If the application or its environment is at fault, the failure must stand: reply KEEP followed by
one sentence. Otherwise reply with one sentence quoting the requirement or environment evidence,
then the complete corrected file in a single ```ts fenced block. Keep every required outcome and
every test title. Never change an expected value merely to match the observed output.'''


def host_environment(extra=None):
    """Clean variables plus what a browser needs to find its installation and profile."""
    names = ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP', 'PLAYWRIGHT_BROWSERS_PATH')
    return {**clean_environment(), **{name: os.environ[name] for name in names if name in os.environ}, **(extra or {})}


async def host_run(argv, cwd, env, timeout):
    """Run a host-owned tool; its whole process tree is killed on timeout or cancellation."""
    holder = {}

    def work():
        with tempfile.TemporaryFile() as output:
            options = process_options()
            if os.name == 'nt':
                options['creationflags'] |= subprocess.CREATE_NO_WINDOW
            process = holder['process'] = subprocess.Popen([str(part) for part in argv], cwd=cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, **options)
            timed_out = False
            try:
                process.wait(timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_process(process)
            output.seek(0)
            return process.returncode, output.read().decode('utf-8', 'replace'), timed_out
    try:
        return await asyncio.to_thread(work)
    except asyncio.CancelledError:
        if holder.get('process') and holder['process'].poll() is None:
            await asyncio.to_thread(stop_process, holder['process'])
        raise


class PlaywrightTooling:
    """Host-owned test runner shared by sessions; versioned with the installed browsers."""

    def __init__(self, root):
        self.version = metadata.version('playwright')
        # Python and npm releases share the minor version (same browser builds) but not
        # the patch number: an exact pin may name an npm version that does not exist.
        self.requirement = '~' + '.'.join(self.version.split('.')[:2]) + '.0'
        self.root = Path(root) / f'playwright-{self.version}'
        self.cli = self.root / 'node_modules/@playwright/test/cli.js'
        self.browser_checked = False

    async def ensure(self):
        if not hasattr(self, '_lock'):
            self._lock = asyncio.Lock()
        async with self._lock:
            return await self._ensure()

    async def _ensure(self):
        node = shutil.which('node')
        if not node:
            raise EnvironmentUnavailable('Node.js is required on the host to run acceptance tests')
        self.node = str(Path(node).resolve())
        if self.cli.is_file():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'package.json').write_text('{"name": "acceptance-tooling", "private": true}\n', encoding='utf-8')
        try:
            command = npm_command()
        except ValueError as error:
            raise EnvironmentUnavailable(str(error)) from error
        code, output, timed_out = await host_run([*command, 'install', '--no-audit', '--no-fund', '--no-save',
            f'@playwright/test@{self.requirement}'], self.root, host_environment(), 600)
        if code or timed_out or not self.cli.is_file():
            raise EnvironmentUnavailable('Cannot install the acceptance test runner: ' + clean(output[-1500:]))

    async def run(self, suite, files, base_url, timeout, test_timeout=30, list_only=False, workers=1):
        results = suite / 'results'
        results.mkdir(parents=True, exist_ok=True)
        report = results / f'report-{len(list(results.glob("report-*.json")))}.json'
        argv = [self.node, self.cli, 'test', '--config', suite / 'playwright.config.cjs', *files]
        if list_only:
            argv.append('--list')
        env = host_environment({'ACCEPTANCE_BASE_URL': base_url, 'PLAYWRIGHT_JSON_OUTPUT_NAME': str(report),
            'ACCEPTANCE_TEST_TIMEOUT': str(test_timeout * 1000), 'ACCEPTANCE_WORKERS': str(workers)})
        for attempt in range(2):
            code, output, timed_out = await host_run(argv, suite, env, timeout)
            missing_browser = "Executable doesn't exist" in output or (report.is_file()
                and "Executable doesn't exist" in report.read_text(encoding='utf-8', errors='replace'))
            if not missing_browser or self.browser_checked:
                break
            # The browser revision of this runner is installed once, on demand.
            self.browser_checked = True
            install = await host_run([self.node, self.cli, 'install', 'chromium'], self.root, host_environment(), 900)
            if install[0]:
                return {'status': ENVIRONMENT, 'tests': [], 'passed': 0, 'failed': 0, 'skipped': 0, 'flaky': 0,
                    'errors': ['Chromium installation failed: ' + clean(install[1][-1200:])]}
            report.unlink(missing_ok=True)
        text = report.read_text(encoding='utf-8', errors='replace') if report.is_file() else output
        parsed = parse_playwright(text, code)
        if timed_out:
            parsed['status'] = 'failed'
            parsed['errors'] = [*parsed['errors'], f'Acceptance suite exceeded {timeout}s']
        parsed['returncode'], parsed['output_tail'] = code, clean(output[-2000:], 2000)
        return parsed


class AcceptanceSuite:
    def __init__(self, directory, catalog, registry, settings, input_dir):
        self.directory, self.catalog, self.registry, self.settings = Path(directory), catalog, registry, settings
        self.input_tests = Path(input_dir) / 'tests' if input_dir else None
        self.files = {}      # suite-relative path -> {origin, sha256, source_sha256?}
        self.titles = {}     # spec path -> [test titles]
        self.reviews = []
        self.reviewed = set()
        self.generation_failures = {}
        self.assembled = False

    def assemble(self):
        """Copy the supplied external tests once; they are never edited or reviewed."""
        if self.assembled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        previous = {}
        try:
            previous = json.loads((self.directory / 'manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        # A resumed session keeps the recorded version of its generated tests.
        for relative, item in previous.get('files', {}).items():
            path = self.directory / relative
            if item.get('origin') == 'generated' and path.is_file() \
                    and sha256(path.read_bytes()).hexdigest() == item['sha256']:
                self._write(relative, path.read_bytes(), 'generated', requirement=item['requirement'])
        self.reviews = list(previous.get('reviews', []))
        self.generation_failures = dict(previous.get('generation_failures', {}))
        self._write('playwright.config.cjs', CONFIG.encode(), 'host')
        if self.settings.external_tests and self.input_tests and self.input_tests.is_dir():
            for source in sorted(self.input_tests.rglob('*')):
                relative = source.relative_to(self.input_tests).as_posix()
                if (source.is_symlink() or not source.is_file() or source.stat().st_size > 2_000_000
                        or source.suffix not in {'.ts', '.js', '.mjs', '.cjs', '.json'} or 'node_modules' in source.parts):
                    continue
                data = source.read_bytes()
                self._write('external/' + relative, data, 'external', source_sha256=sha256(data).hexdigest())
        self.assembled = True
        self._manifest()

    def _write(self, relative, data, origin, **extra):
        path = self.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.files[relative] = {'origin': origin, 'sha256': sha256(data).hexdigest(), **extra}
        if SPEC.search(relative):
            self.titles[relative] = [match.group(2) for match in TITLE.finditer(data.decode('utf-8', 'replace'))]

    def _manifest(self):
        manifest = {'version': self.version(), 'files': self.files, 'reviews': self.reviews,
            'generation_failures': self.generation_failures}
        (self.directory / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')

    def version(self):
        return sha256(json.dumps({path: item['sha256'] for path, item in self.files.items()},
            sort_keys=True).encode()).hexdigest()

    def integrity(self):
        """Suite files and their originals must be exactly what the host recorded."""
        problems = []
        for relative, item in self.files.items():
            path = self.directory / relative
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != item['sha256']:
                problems.append(f'acceptance file altered: {relative}')
            if item['origin'] == 'external':
                original = self.input_tests / relative.removeprefix('external/')
                if not original.is_file() or sha256(original.read_bytes()).hexdigest() != item['source_sha256']:
                    problems.append(f'original external test altered: {relative}')
        return problems

    def specs(self):
        return sorted(self.titles)

    def covers(self, relative, title):
        text = (self.directory / relative).read_text(encoding='utf-8', errors='replace')
        header = '\n'.join(line for line in text.splitlines()[:8] if line.lstrip().startswith(('//', '/*', '*')))
        return self.registry.covers(title, header, Path(relative).name.split('.')[0])

    def planned(self):
        """Ids some existing test is written for, before anything runs."""
        return {identity for relative, titles in self.titles.items() for title in titles
            for identity in self.covers(relative, title)}

    def uncovered(self):
        planned = self.planned()
        # A requirement-level external test does not prove each of its scenarios.
        return [sid for sid in self.catalog.scenarios if sid not in planned and sid not in self.generation_failures]

    def annotate(self, tests):
        for test in tests:
            relative = test['file'].replace('\\', '/')
            test['covers'] = self.covers(relative, test['title']) if relative in self.files else []
            test['origin'] = self.files.get(relative, {}).get('origin')
            test['key'] = relative + ' › ' + test['title']
        return tests

    # ----- supplementary generation -------------------------------------------------

    def generated_path(self, requirement):
        return 'generated/' + sha256(requirement.encode()).hexdigest()[:12] + '.spec.ts'

    def validate(self, source, scenarios):
        if FORBIDDEN.search(source):
            return 'Do not use skip/only/fixme, process.env, require or child processes'
        modules = set(IMPORT.findall(source))
        if modules - {'@playwright/test', 'node:crypto'}:
            return 'Import only @playwright/test and node:crypto'
        titles = [match.group(2) for match in TITLE.finditer(source)]
        for sid in scenarios:
            if sum(bool(token(sid).search(title)) and title.startswith(sid) for title in titles) != 1:
                return f'Write exactly one test whose title starts with "{sid}:"'
        if len(titles) != len(scenarios):
            return 'Write tests only for scenarios_to_cover'
        return None

    def task(self, requirement, scenarios, interfaces):
        context = self.catalog.read(requirement, record=False)
        return {'original_requirement': context['requirement'],
            'ancestor_requirements': context['ancestor_requirements'],
            'scenarios_to_cover': scenarios,
            'required_aspects': {sid: self.registry.entries[sid]['required_aspects'] for sid in scenarios},
            'required_locators': [locator(entry) for entry in self.catalog.contract_for(requirement)],
            'observed_interfaces': {'notice': 'Observations to locate elements; not expected behavior.', **interfaces}}

    async def generate(self, model, budget, interfaces, compile_check):
        """One request per requirement that still has scenarios without an independent test."""
        if not self.settings.generate:
            return []
        groups = {}
        uncovered = self.uncovered()
        for sid in uncovered[:self.settings.max_generated_scenarios or len(uncovered)]:  # 0: every scenario.
            groups.setdefault(self.catalog.scenarios[sid][0], []).append(sid)
        created = []

        async def one(requirement, scenarios):
            relative = self.generated_path(requirement)
            messages = [Message('system', AUTHOR),
                Message('user', json.dumps(self.task(requirement, scenarios, interfaces), ensure_ascii=False))]
            problem = None
            for attempt in range(2):
                budget.reserve_request('acceptance_generation', final=True)
                response = await model.respond(messages, [])
                budget.record_usage(response.usage)
                found = FENCE.search(response.content or '')
                source = found.group(1) if found else ''
                problem = ('Reply with the complete file in one ```ts fenced block' if not source or
                    response.finish_reason != 'stop' else self.validate(source, scenarios))
                if not problem:
                    self._write(relative, source.encode('utf-8'), 'generated', requirement=requirement)
                    problem = await compile_check(relative)
                if not problem:
                    created.append(relative)
                    break
                self._discard(relative)
                messages += [Message('assistant', response.content or '(empty)'),
                    Message('user', 'The file was rejected: ' + problem[:1500] + '\nReply with the corrected complete file.')]
            if problem:
                # An explicit gap: these scenarios stay `missing`, never silently passing.
                for sid in scenarios:
                    self.generation_failures[sid] = problem[:300]

        # Requirements are independent: their files are written concurrently, a few at a time.
        limit = asyncio.Semaphore(GENERATION_CONCURRENCY)

        async def bounded(requirement, scenarios):
            async with limit:
                await one(requirement, scenarios)
        results = await asyncio.gather(*(bounded(r, s) for r, s in groups.items()), return_exceptions=True)
        self._manifest()
        for result in results:
            if isinstance(result, BaseException):
                raise result  # Budget or provider stop: reported by the verifier as before.
        return sorted(created)

    def _discard(self, relative):
        (self.directory / relative).unlink(missing_ok=True)
        self.files.pop(relative, None)
        self.titles.pop(relative, None)

    async def review(self, model, budget, relative, failures, compile_check):
        """Requirement-grounded review of one failing generated file, once per evidence."""
        item = self.files.get(relative)
        if not item or item['origin'] != 'generated':
            return False
        fingerprint = (relative, item['sha256'], tuple(sorted(error for test in failures for error in test['errors'])))
        if fingerprint in self.reviewed:
            return False
        self.reviewed.add(fingerprint)
        before = (self.directory / relative).read_text(encoding='utf-8')
        requirement = item['requirement']
        context = self.catalog.read(requirement, record=False)
        payload = {'original_requirement': context['requirement'], 'ancestor_requirements': context['ancestor_requirements'],
            'test_file': before, 'failures': [{'title': test['title'], 'errors': test['errors']} for test in failures]}
        budget.reserve_request('test_review', final=True)
        response = await model.respond([Message('system', REVIEWER),
            Message('user', json.dumps(payload, ensure_ascii=False))], [])
        budget.record_usage(response.usage)
        found = FENCE.search(response.content or '')
        reason = clean((response.content or '').split('```')[0], 400)
        record = {'file': relative, 'before': item['sha256'], 'decision': 'kept', 'reason': reason}
        changed = False
        if found and response.finish_reason == 'stop' and not (response.content or '').lstrip().startswith('KEEP'):
            source = found.group(1)
            scenarios = [sid for sid in self.catalog.scenarios
                if any(title.startswith(sid) for title in self.titles.get(relative, []))]
            problem = self.validate(source, scenarios)
            if not problem:
                self._write(relative, source.encode('utf-8'), 'generated', requirement=requirement)
                problem = await compile_check(relative)
            if problem:
                self._write(relative, before.encode('utf-8'), 'generated', requirement=requirement)
                record.update(decision='rejected_correction', problem=problem[:300])
            else:
                changed = True
                record.update(decision='corrected', after=self.files[relative]['sha256'])
        self.reviews.append(record)
        self._manifest()
        return changed
