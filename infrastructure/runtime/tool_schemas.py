"""Concise native schemas shared by profile validation and runtime dispatch."""


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def text(**extra):
    return {'type': 'string', **extra}


def integer(minimum=0, maximum=1000000):
    return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}


def array(items, maximum=100):
    return {'type': 'array', 'items': items, 'maxItems': maximum}


PAGING = {'offset': integer(), 'limit': integer(1, 100)}
TOOLS = {}


def define(name, description, properties, required=()):
    TOOLS[name] = {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': obj(properties, required)}}


define('read_file', 'Read paginated source lines; unchanged reads return a retrievable artifact.',
    {'path': text(), 'start_line': integer(1), 'end_line': integer(1)}, ['path'])
define('read_files', 'Read several files or line ranges in one call (200 lines per entry unless end_line is given). '
    'Prefer it to consecutive read_file calls. A missing or unreadable entry is reported without failing the others.',
    {'files': array(obj({'path': text(), 'start_line': integer(1), 'end_line': integer(1)}, ['path']), 8)}, ['files'])
define('write_files', 'Create or fully rewrite several application files in one call; every path and permission is '
    'validated before any file is written. Prefer it to consecutive write_file calls.',
    {'files': array(obj({'path': text(), 'content': text()}, ['path', 'content']), 30)}, ['files'])
define('delegate_tasks', 'Write independent parts of the application in parallel: each task runs in its own '
    'sub-agent at the same time, can read everything and write only its own write_paths (files or directories, '
    'disjoint between tasks). Sub-agents run no commands. Give every task the shared contract it must follow. '
    'Returns the changed files and summary; then integrate and verify.',
    {'contract': text(minLength=1), 'tasks': array(obj({'id': text(minLength=1), 'task': text(minLength=1),
        'write_paths': array(text(minLength=1), 20), 'requirements': array(text(), 20)},
        ['id', 'task', 'write_paths']), 4)}, ['contract', 'tasks'])
define('run_acceptance_tests', 'Run the host acceptance tests (supplied and generated from the requirements) against '
    'your current application: install, build, start on a fresh database, then every test. Returns each failure with '
    'its requirement id and symptom (the test source is host-owned). Much faster and more precise than testing '
    'journeys by hand with curl, the database or the browser. Not the final acceptance.', {})
define('edit_file','Create, replace one exact span, append or prepend application text.',
    {'path': text(), 'operation': text(enum=['create', 'replace', 'append', 'prepend']),
     'new_content': text(), 'old_content': text()}, ['path', 'operation', 'new_content'])
define('write_file', 'Write an application file, including a justified whole-file rewrite. Preserve existing behavior.',
    {'path': text(), 'content': text(), 'expected_sha256': text()}, ['path', 'content'])
define('apply_patch', 'Apply exact replacements across files after validating every edit and permission.',
    {'changes': array(obj({'path': text(), 'old_content': text(minLength=1), 'new_content': text()},
        ['path', 'old_content', 'new_content']), 50)}, ['changes'])
define('list_files', 'List application source paths, excluding private files and generated dependencies.',
    {'prefix': text(), **PAGING})
define('search_text', 'Find literal text in application sources; page through exact file and line matches.',
    {'query': text(minLength=1), 'prefix': text(), **PAGING}, ['query'])
define('read_artifact', 'Retrieve exact characters from a long observation or archived conversation.',
    {'identity': text(), 'offset': integer(), 'limit': integer(1, 12000)}, ['identity'])
define('requirement_catalog', 'Page all requirements, including non-leaf requirements and resource identifiers.', PAGING)
define('read_requirement', 'Read one original requirement/scenario/step with parent constraints and scenarios.',
    {'identity': text()}, ['identity'])
define('coverage', 'Inspect coverage per requirement: your declarations next to independent host verification.', PAGING)
define('todo_write', 'Replace the adaptable task list. Done is an implementation claim, never acceptance.',
    {'items': array(obj({'id': text(minLength=1), 'task': text(minLength=1),
        'status': text(enum=['pending', 'in_progress', 'done']), 'requirements': array(text())},
        ['id', 'task', 'status', 'requirements']), 1000)}, ['items'])
define('note_write', 'Retain concise contracts, evidenced causes and next checks across context compaction.',
    {'contracts': array(text(), 30), 'established_causes': array(text(), 30), 'next_checks': array(text(), 30)},
    ['contracts', 'established_causes', 'next_checks'])
define('run_command', 'Run a short argv command noninteractively (default timeout 120 s). Use sh -c only for shell '
    'syntax. Never start a server here: use process_start.',
    {'command': array(text(), 100), 'timeout': integer(1, 600),
        'env': obj({key: text() for key in ('PORT', 'HOST', 'NODE_ENV', 'DATABASE_URL')})}, ['command'])
define('install_dependencies', 'Install npm dependencies only if manifests, lockfile or environment changed.', {})
define('verify_application', 'Run a targeted local check: TypeScript compilation, build, backend tests '
    '(optionally selected files under backend/checks), or all three in order until one fails. Dependencies are '
    'installed first when manifests changed, so no separate install call is needed. Absent tests are reported as '
    'missing. Not acceptance.',
    {'kind': text(enum=['typecheck', 'build', 'backend_tests', 'all']), 'files': array(text(minLength=1), 30)}, ['kind'])
define('http_request', 'Send one real HTTP request to a running owned service and observe status, headers and body.',
    {'port': integer(1, 65535), 'path': text(minLength=1), 'method': text(enum=['GET', 'POST', 'PUT', 'PATCH', 'DELETE']),
        'body': text(), 'headers': obj({key: text() for key in ('Content-Type', 'Cookie', 'Authorization', 'Accept')})},
    ['port', 'path'])
define('database_query', 'Inspect an application SQLite database with one read-only SQL statement.',
    {'sql': text(minLength=1), 'database': text(minLength=1), 'limit': integer(1, 200)}, ['sql'])
define('interface_write', 'Declare the pages your application actually serves (path, purpose, reference image id). '
    'The host uses them to locate pages for verification; they never define expected behavior.',
    {'pages': array(obj({'path': text(minLength=1), 'description': text(), 'image': text()}, ['path']), 40)}, ['pages'])
define('process_start', 'Start/reuse a sandboxed service. Declare its ports and restart after non-watched changes. '
    'ready_timeout waits for an HTTP response on every declared port. probe_path also waits, then returns one GET '
    'of that path on the first port, replacing a separate http_request.',
    {'name': text(minLength=1), 'command': array(text(), 100), 'ports': array(integer(1, 65535), 8),
        'restart': {'type': 'boolean'}, 'ready_timeout': integer(0, 120), 'probe_path': text(minLength=1),
        'env': obj({key: text() for key in ('PORT', 'HOST', 'NODE_ENV', 'DATABASE_URL')})},
    ['name', 'command'])
define('process_status', 'Inspect an owned service and whether its sources have changed.', {'name': text()}, ['name'])
define('process_logs', 'Read an owned process output; page through the full retained log.',
    {'name': text(), 'offset': integer(), 'limit': integer(1, 12000)}, ['name'])
define('process_stop', 'Stop an owned process tree/container.', {'name': text()}, ['name'])
define('browser', 'Use the session browser on declared process ports; observe DOM, screenshots and network errors.',
    {'action': text(enum=['open', 'snapshot', 'click', 'fill', 'select', 'press', 'screenshot', 'logs', 'resize']),
        'url': text(), 'selector': text(), 'role': text(), 'name': text(), 'value': text(),
        'width': integer(320, 2560), 'height': integer(320, 2560)}, ['action'])
define('view_image', 'Inspect an original reference image or a screenshot artifact on demand.',
    {'identity': text(), 'question': text()}, ['identity'])
define('find_symbol', 'Locate where a function, type, component, SQL table or route is defined and where it is used.',
    {'name': text(minLength=2), 'prefix': text()}, ['name'])
define('read_skill', 'Read one short practice guide before working in its area. Names are listed in your instructions.',
    {'name': text(minLength=1)}, ['name'])
define('git_read', 'Read local Git status, diff or recent history without hooks, external diff or network.',
    {'action': text(enum=['status', 'diff', 'log'])}, ['action'])


def validate(value, schema, label='arguments'):
    kind = schema['type']
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
        'string': isinstance(value, str), 'integer': type(value) is int, 'boolean': type(value) is bool}[kind]
    if not valid:
        raise ValueError(f'{label} must be {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'Invalid {label}')
    if kind == 'object':
        if set(value) - schema['properties'].keys() or set(schema['required']) - value.keys():
            raise ValueError(f'Unexpected or missing fields in {label}')
        for key, item in value.items():
            validate(item, schema['properties'][key], f'{label}.{key}')
    elif kind == 'array':
        if len(value) > schema.get('maxItems', 100):
            raise ValueError(f'Too many entries in {label}')
        for item in value:
            validate(item, schema['items'], label)
    elif kind == 'integer' and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ValueError(f'{label} is outside its allowed range')
    elif kind == 'string' and len(value) < schema.get('minLength', 0):
        raise ValueError(f'{label} must not be empty')
