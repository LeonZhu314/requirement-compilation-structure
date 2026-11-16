"""Targeted checks of the real application: compilation, tests, HTTP and database.

The commands, test paths and interfaces are those of the application itself. A
result is reused only when every relevant dependency is unchanged: sources (which
include configuration, scripts and the lockfile), toolchain versions, sandbox image
and the mirror generation. A test file's own hash never keeps a functional result.
"""

import asyncio
from hashlib import sha256
import http.client
import json

from .results import ENVIRONMENT, FAILED, PASSED, clean, command_status, error_excerpt, parse_tap

TSC = ['node', 'node_modules/typescript/bin/tsc', '--noEmit', '-p']
QUERY_SCRIPT = '''const Database = require("better-sqlite3");
const [file, sql, limit] = process.argv.slice(1);
const db = new Database(file, { readonly: true, fileMustExist: true });
try {
  const statement = db.prepare(sql);
  if (!statement.reader) throw new Error("Only read statements are allowed");
  const rows = [];
  for (const row of statement.iterate()) { rows.push(row); if (rows.length >= Number(limit)) break; }
  console.log("ROWS:" + JSON.stringify(rows));
} finally { db.close(); }'''


class ApplicationChecks:
    def __init__(self, processes, dependencies, artifacts, state):
        self.processes, self.dependencies, self.artifacts, self.state = processes, dependencies, artifacts, state
        self.cache = {}
        self.cache_hits = 0

    def log(self, result):
        identity = result.get('artifact')
        return self.artifacts.path(identity).read_text(encoding='utf-8') if identity else result.get('content', '')

    async def fingerprint(self, kind, files=()):
        mirror = self.processes.mirror
        return sha256(json.dumps([kind, sorted(files), mirror.revision(), mirror.generation,
            await self.dependencies.fingerprint()]).encode()).hexdigest()

    async def run(self, kind, files=(), *, use_cache=True):
        """Run one targeted check; `files` selects backend test files."""
        files = list(files or ())
        if files and kind != 'backend_tests':
            raise ValueError('files select backend tests only')
        key = await self.fingerprint(kind, files)
        if use_cache and key in self.cache:
            self.cache_hits += 1
            return {**self.cache[key], 'cached': True}
        if kind == 'typecheck':
            evidence = await self._typecheck()
        elif kind == 'build':
            result = await self.processes.run(['npm', 'run', 'build'])
            evidence = self._evidence(kind, result, command_status(result['returncode'], self.log(result)))
        elif kind == 'backend_tests':
            command = ['node', 'backend/scripts/test-api.mjs', *files] if files else ['npm', 'run', 'test:backend']
            result = await self.processes.run(command)
            tap = parse_tap(self.log(result), result['returncode'])
            evidence = self._evidence(kind, result, tap.pop('status'), tap)
        else:
            raise ValueError('Unknown check kind')
        evidence['cached'] = False
        # A command may itself change sources; only a stable state is reusable.
        if evidence['status'] in {PASSED, FAILED} and await self.fingerprint(kind, files) == key:
            self.cache[key] = evidence
        self.state.checks.append({k: evidence[k] for k in
            ('kind', 'status', 'returncode', 'source_revision', 'artifact', 'accepted')})
        return evidence

    def _evidence(self, kind, result, status, summary=None):
        if result['status'] in {'timed_out', 'output_limit'}:
            status = FAILED
        evidence = {'kind': kind, 'status': status, 'returncode': result['returncode'],
            'process_status': result['status'], 'source_revision': self.processes.mirror.revision(),
            'artifact': result.get('artifact'), 'accepted': False}
        if summary:
            evidence['summary'] = summary
        if status != PASSED:
            evidence['output_tail'] = clean(error_excerpt(self.log(result), 2500), 2600)
        if status == ENVIRONMENT:
            evidence['notice'] = 'Dependencies or tools are unavailable; run install_dependencies. Not an application verdict.'
        return evidence

    async def _typecheck(self):
        parts, worst, last = [], PASSED, None
        for project in ('backend/tsconfig.test.json', 'frontend/tsconfig.json'):
            last = await self.processes.run([*TSC, project])
            status = command_status(last['returncode'], self.log(last))
            parts.append({'project': project, 'status': status,
                **({'output_tail': clean(error_excerpt(self.log(last), 2000), 2100)} if status != PASSED else {})})
            worst = ENVIRONMENT if ENVIRONMENT in (worst, status) else FAILED if FAILED in (worst, status) else PASSED
        evidence = self._evidence('typecheck', last, worst, {'projects': parts})
        evidence['returncode'] = 0 if worst == PASSED else 1
        return evidence

    async def http_request(self, port, path='/', method='GET', body=None, headers=None):
        """One real HTTP request to a service this session owns."""
        if port not in self.processes.ports():
            raise ValueError('http_request reaches only a running owned service on its declared port')
        if not path.startswith('/') or method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
            raise ValueError('Use an absolute path and GET/POST/PUT/PATCH/DELETE')
        allowed = {'content-type', 'cookie', 'authorization', 'accept'}
        sent = {key: value for key, value in (headers or {}).items() if key.lower() in allowed}
        if set(headers or {}) - set(sent):
            raise ValueError('Only Content-Type, Cookie, Authorization and Accept headers may be set')
        if body is not None and not any(key.lower() == 'content-type' for key in sent):
            sent['Content-Type'] = 'application/json'

        def request():
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
            try:
                connection.request(method, path, body=body.encode('utf-8') if body is not None else None, headers=sent)
                response = connection.getresponse()
                data = response.read(200_000)
                return {'status': response.status, 'headers': {key: value for key, value in response.getheaders()
                    if key.lower() in {'content-type', 'set-cookie', 'location', 'cache-control'}},
                    'body': data.decode('utf-8', 'replace'), 'accepted': False}
            finally:
                connection.close()
        try:
            return await asyncio.to_thread(request)
        except OSError as error:
            return {'status': None, 'error': f'{type(error).__name__}: {error}', 'accepted': False,
                'notice': 'No HTTP response; inspect process_status and process_logs.'}

    async def database_query(self, sql, database='backend/data/app.db', limit=50):
        """Read-only inspection of an application SQLite file inside the sandbox."""
        if '..' in database.split('/') or database.startswith('/') or '\x00' in database:
            raise ValueError('database must be a relative path inside the application')
        result = await self.processes.run(['node', '-e', QUERY_SCRIPT, database, sql, str(limit)], timeout=60)
        log = self.log(result)
        for line in log.splitlines():
            if line.startswith('ROWS:'):
                rows = json.loads(line[5:])
                return {'rows': rows, 'count': len(rows), 'limit': limit, 'accepted': False}
        return {'error': clean(log[-1500:]), 'accepted': False,
            'notice': 'The database file exists only after the application or db:init has run in the sandbox.'}
