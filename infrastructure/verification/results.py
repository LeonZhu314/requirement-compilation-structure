"""Normalize real command output into explicit statuses.

A check is `passed` only when tests actually executed and none failed, was skipped
or was flaky. Absent tests (`missing`), runs that executed nothing (`no_tests_executed`),
environment problems and inapplicable checks are distinct from both success and failure.
"""

import json
import re

PASSED, FAILED, MISSING = 'passed', 'failed', 'missing'
NO_TESTS, INCOMPLETE = 'no_tests_executed', 'incomplete'
ENVIRONMENT, NOT_APPLICABLE = 'environment_error', 'not_applicable'
ANSI = re.compile(r'\x1b\[[0-9;]*m')
ENVIRONMENT_SIGNS = ('ERR_DLOPEN_FAILED', 'browserType.launch', "Executable doesn't exist",
    'ENOSPC', 'EAI_AGAIN', 'ETIMEDOUT', 'ECONNRESET')
DEPENDENCY_SIGNS = ("Cannot find module '/workspace/node_modules", 'node_modules/typescript/bin/tsc',
    'tsx: not found', 'vite: not found', 'tsc: not found', "Cannot find package 'tsx'")


def clean(text, limit=1500):
    return ANSI.sub('', text or '').strip()[:limit]


ERROR_LINE = re.compile(r'error|ERR!|\bfail(ed|ure|ing)?\b|exception|cannot find|not found|unexpected|not ok\b|'
    r'TS\d{4}|ENOENT|EADDRINUSE|EACCES|ETARGET|E404|denied|unresolved|is not (defined|a function|assignable)|'
    r'[✘✗×]', re.IGNORECASE)


def error_excerpt(text, limit=2500, context=2):
    """Error lines of a build, compiler or npm log with a little context, first errors
    first, instead of the raw end of the output. Falls back to the end when no line
    looks like an error. The complete log stays available as an artifact."""
    text = ANSI.sub('', text or '').strip()
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    keep = set()
    for index, line in enumerate(lines):
        if ERROR_LINE.search(line):
            keep.update(range(max(0, index - 1), min(len(lines), index + context + 1)))
    if not keep:
        return text[-limit:]
    keep.update(range(max(0, len(lines) - 3), len(lines)))  # Summary lines: error count, exit status.
    shown, seen, previous = [], set(), None
    for index in sorted(keep):
        line = lines[index][:400]
        if line in seen:
            continue  # The same error repeated for every file adds no information.
        seen.add(line)
        if previous is not None and index != previous + 1:
            shown.append('[...]')
        shown.append(line)
        previous = index
    excerpt = '\n'.join(shown)
    if len(excerpt) > limit:
        excerpt = excerpt[:limit] + '\n[... more errors in the full log]'
    return excerpt


FRAME = re.compile(r'^\s*(>?\s*\d+ \||\|\s*\^|at .+:\d+:\d+\)?$)')


def symptom(text, limit=900):
    """A test error without the code frame and stack that quote protected test source."""
    lines = [line for line in ANSI.sub('', text or '').splitlines() if not FRAME.match(line)]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()[:limit]


def command_status(returncode, output):
    """Status for a plain command such as a build or a TypeScript compilation."""
    if returncode == 0:
        return PASSED
    if any(sign in output for sign in DEPENDENCY_SIGNS):
        return ENVIRONMENT  # Dependencies are not installed; this is not an application defect.
    return FAILED


def parse_tap(output, returncode):
    """Node test-runner TAP emitted by backend/scripts/test-api.mjs."""
    counts = {}
    for kind in ('tests', 'pass', 'fail', 'skipped', 'todo'):
        found = re.search(rf'^# {kind} (\d+)\s*$', output, re.MULTILINE)
        counts[kind] = int(found.group(1)) if found else 0
    failures = [clean(block) for block in re.findall(r'(?m)^\s*not ok[^\n]*\n(?:[ \t]+[^\n]*\n)*', output)]
    lifecycle = re.search(r'^BACKEND_(STARTUP|RUNTIME|RUNNER)_ERROR:[^\n]*', output, re.MULTILINE)
    if 'NO_API_TESTS:' in output:
        status = MISSING
    elif lifecycle and lifecycle.group(1) == 'RUNNER' and any(sign in output for sign in ENVIRONMENT_SIGNS):
        status = ENVIRONMENT
    elif returncode or counts['fail'] or lifecycle:
        status = FAILED
    elif not counts['tests'] or not counts['pass']:
        status = NO_TESTS
    elif counts['skipped'] or counts['todo']:
        status = INCOMPLETE
    else:
        status = PASSED
    result = {'status': status, **counts, 'failures': failures[:10]}
    if lifecycle:
        result['lifecycle_error'] = clean(lifecycle.group(0), 600)
    return result


def parse_playwright(stdout, returncode):
    """Playwright JSON reporter: per-test outcomes without copying test source."""
    try:
        start = stdout.index('{')
        report = json.loads(stdout[start:])
    except ValueError:
        environment = any(sign in stdout for sign in ENVIRONMENT_SIGNS)
        return {'status': ENVIRONMENT if environment else FAILED, 'tests': [], 'passed': 0, 'failed': 0,
            'skipped': 0, 'flaky': 0, 'errors': [clean(stdout[-3000:], 3000) or 'Playwright produced no JSON report']}
    tests = []

    def visit(suite, titles):
        for spec in suite.get('specs', []):
            title = ' › '.join([*titles, spec.get('title', '')])
            for test in spec.get('tests', []):
                runs = test.get('results', [])
                last = runs[-1] if runs else {}
                outcome = test.get('status', 'unexpected')  # expected | unexpected | flaky | skipped
                # Error messages carry locators and expected values (symptoms); code
                # frames of the protected test source are not reproduced.
                messages = [symptom(error.get('message', '')) for error in last.get('errors', [])]
                tests.append({'file': spec.get('file', suite.get('file', '')), 'title': title,
                    'status': {'expected': PASSED, 'unexpected': FAILED}.get(outcome, outcome),
                    'duration_ms': last.get('duration'), 'errors': [m for m in messages if m][:3]})
        for child in suite.get('suites', []):
            visit(child, [*titles, child.get('title', '')] if child.get('title') and child.get('title') != child.get('file') else titles)

    for suite in report.get('suites', []):
        visit(suite, [])
    stats = report.get('stats', {})
    errors = [symptom(error.get('message', ''), 1200) for error in report.get('errors', [])]
    counts = {'passed': stats.get('expected', 0), 'failed': stats.get('unexpected', 0),
        'skipped': stats.get('skipped', 0), 'flaky': stats.get('flaky', 0)}
    if errors and any(sign in ' '.join(errors) for sign in ENVIRONMENT_SIGNS):
        status = ENVIRONMENT
    elif errors or counts['failed'] or (returncode and not counts['passed']):
        status = FAILED
    elif not counts['passed']:
        status = NO_TESTS
    elif counts['skipped'] or counts['flaky']:
        status = INCOMPLETE
    else:
        status = PASSED if returncode == 0 else FAILED
    return {'status': status, **counts, 'tests': tests, 'errors': errors[:5]}
