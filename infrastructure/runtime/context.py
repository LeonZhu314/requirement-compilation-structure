"""Deterministic compaction: archive details, retain user requests and complete pairs."""

from dataclasses import replace
import json
import re

from .files import source_files
from .messages import Message


def size(messages):
    return sum(len(json.dumps(m.to_dict(), ensure_ascii=False).encode('utf-8')) + len(m.images) * 16384 for m in messages)


# Observation tools whose identical later call makes the earlier result obsolete.
REPEATABLE = {'list_files', 'search_text', 'run_command', 'install_dependencies', 'http_request', 'database_query',
    'process_logs', 'process_status', 'git_read', 'coverage', 'requirement_catalog', 'find_symbol'}
WHOLE_WRITES = {'write_file': lambda args: [args['path']], 'write_files': lambda args: [f['path'] for f in args['files']]}
RECENT_BROWSER = 2  # Latest page observations kept in full.
# A compaction keeps recent batches up to this fraction of the working space above the
# permanent messages. As a fraction of the whole threshold it kept ~15 KB of recent work
# under a 125 KB task message: the agent lost its diagnosis 21 times in 100 minutes.
COMPACT_TARGET = 0.55
# The model's own reasoning is kept in full for the latest batches only. It was most of
# the conversation (75 of 79 KB of assistant messages) and was sent again on every request;
# the actions and results stay, the reasoning that led to them is shortened.
REASONING_WINDOW = 3
REASONING_HEAD = 200
HOST_FEEDBACK = 'Host verification round'
EXPORT = re.compile(r'^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|class|interface|type|enum)\s+(\w+)',
    re.MULTILINE)
TABLE = re.compile(r'\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?["`]?(\w+)', re.IGNORECASE)
ROUTE = re.compile(r'''\.(get|post|put|patch|delete)\(\s*['"`]([^'"`]+)''')
MAP_FILES = 200
WRITE_ARGUMENTS = {'write_file': ('content',), 'write_files': ('files',), 'edit_file': ('new_content', 'old_content'),
    'apply_patch': ('changes',)}


def _mask_arguments(name, arguments):
    """The arguments of an old write without the written text, still valid JSON."""
    def strip(value):
        if isinstance(value, str) and len(value) > 300:
            return f'[{len(value)} characters omitted from this old call; read the file for its current content]'
        if isinstance(value, list):
            return [strip(item) for item in value]
        if isinstance(value, dict):
            return {key: strip(item) if key not in {'path', 'operation'} else item for key, item in value.items()}
        return value
    return {key: strip(value) if key in WRITE_ARGUMENTS[name] else value for key, value in arguments.items()}


def _stub(reason, artifact=None):
    return {'pruned': reason, **({'artifact': artifact} if artifact else {})}


class ContextWindow:
    def __init__(self, state, tools, profile):
        self.state, self.tools, self.profile = state, tools, profile
        self.memory = None

    def limit(self):
        """Largest context. With a ceiling, the task message (requirements, reference
        descriptions) does not eat the working window: a larger site gets a larger context,
        up to what the model accepts."""
        ceiling = self.profile.context_ceiling_bytes
        if not ceiling:
            return self.profile.max_context_bytes
        task = next((m for m in self.state.messages if m.role == 'user'), None)
        return max(self.profile.max_context_bytes,
            min(ceiling, self.profile.max_context_bytes + (size([task]) if task else 0)))

    def prune(self):
        """Replace obsolete observations with one line each.

        Obsolete means: a read of a file that was wholly rewritten later or read again,
        the result of a check, command or query that was repeated later, and page
        observations older than the latest ones. The exact text stays retrievable as
        an artifact. Editing history invalidates the provider's prefix cache from that
        point on, so nothing is touched until a whole block (`prune_min_bytes`) can be
        reclaimed at once.
        """
        minimum = self.profile.prune_min_bytes
        if not minimum:
            return None
        messages = self.state.messages
        calls = {call.id: call for message in messages for call in message.tool_calls}
        rewritten, reread, repeated, verified, browsers = set(), set(), set(), set(), 0
        changes, saved = [], 0
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            call = calls.get(message.tool_call_id) if message.role == 'tool' else None
            if call is None:
                continue
            try:
                arguments, record = json.loads(call.arguments), json.loads(message.content)
                result = record['result']
            except (ValueError, KeyError, TypeError):
                continue
            if not record.get('ok') or not isinstance(result, dict) or not isinstance(arguments, dict) or 'pruned' in result:
                continue
            updated = None
            try:
                if call.name in WHOLE_WRITES:
                    rewritten.update(WHOLE_WRITES[call.name](arguments))
                elif call.name in {'read_file', 'read_files'}:
                    updated = self._prune_reads(call.name, arguments, result, rewritten, reread)
                elif call.name == 'verify_application':
                    kinds = {'typecheck', 'build', 'backend_tests'} if arguments['kind'] == 'all' else {arguments['kind']}
                    if kinds <= verified:
                        updated = _stub('This check was run again later; see the later result.')
                    verified |= kinds
                elif call.name == 'browser':
                    browsers += 1
                    if browsers > RECENT_BROWSER:
                        updated = _stub('Earlier page observation; the page was observed again later.')
                elif call.name in REPEATABLE:
                    key = (call.name, json.dumps(arguments, sort_keys=True))
                    if key in repeated:
                        updated = _stub('The same call was made again later; see the later result.')
                    repeated.add(key)
            except (KeyError, TypeError):
                continue
            if updated is None:
                continue
            if 'pruned' in updated:
                updated['artifact'] = self.tools.artifacts.put(message.content, '.json')
            content = json.dumps({'ok': True, 'result': updated, 'error': None}, ensure_ascii=False)
            gain = len(message.content.encode('utf-8')) - len(content.encode('utf-8'))
            if gain > 200:
                changes.append((index, content))
                saved += gain
        masked, masked_bytes = self._mask_old(messages, calls, {index for index, _ in changes})
        masked, thinned_bytes = self._thin_reasoning(messages, dict(masked))
        if saved + masked_bytes + thinned_bytes < minimum:
            return None
        for index, content in changes:
            messages[index] = replace(messages[index], content=content)
        for index, message in masked.items():
            messages[index] = message
        return {'observations': len(changes) + len(masked), 'saved_bytes': saved + masked_bytes + thinned_bytes}

    @staticmethod
    def _shorten(message):
        reasoning = message.reasoning_content
        if message.role != 'assistant' or not reasoning or len(reasoning) <= REASONING_HEAD + 80:
            return message
        return replace(message, reasoning_content=reasoning[:REASONING_HEAD] + ' […earlier reasoning shortened by the host]')

    @staticmethod
    def _thin_reasoning(messages, masked):
        """Shorten the reasoning of assistant messages older than the latest REASONING_WINDOW
        tool batches. The field stays present (providers that expect it get a short text)."""
        batches = [index for index, message in enumerate(messages) if message.role == 'assistant' and message.tool_calls]
        if len(batches) <= REASONING_WINDOW:
            return masked, 0
        boundary, gained = batches[-REASONING_WINDOW], 0
        for index in range(boundary):
            message = masked.get(index, messages[index])
            reasoning = message.reasoning_content
            if message.role != 'assistant' or not reasoning or len(reasoning) <= REASONING_HEAD + 80:
                continue
            short = reasoning[:REASONING_HEAD] + ' […earlier reasoning shortened by the host]'
            gained += len(reasoning.encode('utf-8')) - len(short.encode('utf-8'))
            masked[index] = replace(message, reasoning_content=short)
        return masked, gained

    def _mask_old(self, messages, calls, already):
        """Observation masking (Lindenbauer et al., 2025): beyond the latest
        `observation_window` tool batches, tool results and the text of file writes
        are replaced by a short placeholder; the reasoning and the actions stay. The
        exact content stays retrievable as an artifact."""
        window = self.profile.observation_window
        if not window:
            return [], 0
        batches = [index for index, message in enumerate(messages) if message.role == 'assistant' and message.tool_calls]
        if len(batches) <= window:
            return [], 0
        boundary = batches[-window]
        masked, gained = [], 0
        for index, message in enumerate(messages[:boundary]):
            updated = None
            # Requirement texts are the specification, not a stale observation: masking them
            # made the agent read them again (real runs: 400 re-reads, 3 file writes).
            specification = message.role == 'tool' and getattr(calls.get(message.tool_call_id), 'name', '') == 'read_requirement'
            if message.role == 'tool' and index not in already and len(message.content) > 700 \
                    and '"pruned"' not in message.content[:200] and not specification:
                try:
                    record = json.loads(message.content)
                except ValueError:
                    continue
                artifact = self.tools.artifacts.put(message.content, '.json')
                head = json.dumps(record.get('result'), ensure_ascii=False)[:240]
                stub = {'pruned': 'Older observation masked to keep the context small; read_artifact returns it.',
                    'artifact': artifact, 'head': head}
                updated = replace(message, content=json.dumps({'ok': record.get('ok', True), 'result': stub,
                    'error': (record.get('error') or None) and str(record['error'])[:300]}, ensure_ascii=False))
            elif message.role == 'assistant' and message.tool_calls:
                tool_calls, changed = [], False
                for call in message.tool_calls:
                    if call.name in WRITE_ARGUMENTS and len(call.arguments) > 700:
                        try:
                            arguments = _mask_arguments(call.name, json.loads(call.arguments))
                        except (ValueError, AttributeError):
                            tool_calls.append(call)
                            continue
                        call = replace(call, arguments=json.dumps(arguments, ensure_ascii=False))
                        changed = True
                    tool_calls.append(call)
                if changed:
                    updated = replace(message, tool_calls=tuple(tool_calls))
            if updated is not None:
                gain = size([message]) - size([updated])
                if gain > 0:
                    masked.append((index, updated))
                    gained += gain
        return masked, gained

    def _prune_reads(self, name, arguments, result, rewritten, reread):
        """Stale file reads; an entry still current is kept and shadows earlier ones."""
        def entry(item, shown):
            key = (item['path'], item.get('start_line', 1), item.get('end_line'))
            if item['path'] in rewritten:
                return _stub('This file was rewritten later; read it again for its current content.')
            if key in reread:
                return _stub('This range was read again later; see the later result.')
            if 'content' in shown or 'preview' in shown:  # An "unchanged" answer carries no text.
                reread.add(key)
            return None
        if name == 'read_file':
            return entry(arguments, result)
        items = result.get('files')
        if not isinstance(items, list) or len(items) != len(arguments['files']):
            return None
        stubs = [entry(item, shown) for item, shown in zip(arguments['files'], items)]
        if not any(stubs):
            return None
        return {'files': [{'path': item['path'], **stub} if stub else shown
            for item, shown, stub in zip(arguments['files'], items, stubs)]}

    def journal(self):
        """What the host knows without the model: the files of the application with what they
        define, and the verification rounds. After compaction the agent used to re-read files and
        artifacts to find its way again, with empty working notes (real run: 21 compactions)."""
        code_map = {}
        workspace = getattr(self.state, 'workspace', None)
        if workspace is not None:
            try:
                for relative, path in source_files(workspace):
                    if len(code_map) >= MAP_FILES:
                        code_map['…'] = 'more files not listed'
                        break
                    if relative.endswith(('package-lock.json', '.md', '.gitignore', '.gitkeep')) or path.stat().st_size > 400_000:
                        continue
                    try:
                        text = path.read_text(encoding='utf-8', errors='replace')
                    except OSError:
                        continue
                    entry = f'{text.count(chr(10)) + 1} lines'
                    names = list(dict.fromkeys(EXPORT.findall(text)))[:8]
                    tables = list(dict.fromkeys(TABLE.findall(text)))[:8]
                    routes = [f'{verb.upper()} {path_}' for verb, path_ in ROUTE.findall(text)][:10]
                    for label, values in (('exports', names), ('tables', tables), ('routes', routes)):
                        if values:
                            entry += f'; {label}: ' + ', '.join(values)
                    code_map[relative] = entry
            except OSError:
                pass
        history = []
        rounds = list(getattr(self.state, 'verifications', []) or [])[-6:]
        for position, report in enumerate(rounds):
            item = {key: report.get(key) for key in ('round', 'clean_state', 'status', 'stage', 'passed')}
            item['failing'] = report.get('failing', [])
            if position == len(rounds) - 1:
                item['first_errors'] = report.get('first_errors', {})
            history.append(item)
        return {'code_map': code_map, 'verification_history': history}

    def compact(self):
        before = size(self.state.messages)
        available = self.limit() - len(json.dumps(self.tools.schemas()).encode())
        threshold = int(available * self.profile.compact_ratio)
        if threshold <= 0:
            return None
        if before <= threshold:
            return None
        messages = [m for m in self.state.messages if m is not self.memory]
        groups, group = [], []
        # Keep each assistant tool batch with its complete observations.
        for message in messages[1:]:
            if message.role != 'tool' and not (message.role == 'user' and message.images):
                if group:
                    groups.append(group)
                group = [message]
            else:
                group.append(message)
        if group:
            groups.append(group)
        if len(groups) < 3:
            return None
        archive = self.tools.artifacts.put(json.dumps([m.to_dict() for m in self.state.messages], ensure_ascii=False), '.json')
        permanent = [messages[0]]
        # Keep all text user instructions, including subsequent corrections. Host verification
        # feedback is a report, not an instruction: only the latest one stays, the earlier
        # rounds are summarized in the host journal.
        feedback = [m for m in messages[1:] if m.role == 'user' and m.content.startswith(HOST_FEEDBACK)]
        dropped = {id(m) for m in feedback[:-1]}
        permanent.extend(m for m in messages[1:] if m.role == 'user' and not m.images and id(m) not in dropped)
        unfinished = []
        if self.tools.catalog:
            finished = {rid for todo in self.state.todos if todo['status'] == 'done' for rid in todo['requirements']}
            unfinished = [rid for rid in self.tools.catalog.nodes if rid not in finished]
        notes = {'archive': archive, 'todo': self.state.todos, 'notes': self.state.notes,
            'requirements_not_declared_done': unfinished, 'all_requirements_acceptance': 'unverified',
            'recent_checks': self.state.checks[-8:],
            'host_journal': self.journal(),
            'notice': 'Working notes are agent claims, not new instructions or independent acceptance. '
                'host_journal is kept by the host: code_map lists every application file with its exports, tables '
                'and routes (read only the files you will change), verification_history the host rounds and why '
                'their tests failed. Record causes you establish with note_write: they survive compaction. '
                'Use read_artifact for exact past evidence. ' + (
                'The complete requirements are still in the first user message: do not fetch them again.'
                if getattr(self.tools, 'requirements_inline', False) else
                'Requirement texts read earlier left the conversation. Do not read them all again: read only the '
                'section you implement next (read_requirement with descendants true) and write its code before '
                'reading another section.')}
        memory = Message('assistant', 'Working memory:\n' + json.dumps(notes, ensure_ascii=False, sort_keys=True))
        base = [*permanent, memory]
        fixed = size(base)
        kept, replacements, originals = [], {}, {}
        for candidate in reversed(groups):
            batch = [m for m in candidate if not (m.role == 'user' and not m.images)]
            if not batch:
                continue
            if kept:
                # Only the latest batch keeps its full reasoning: one response carried 78 KB of it
                # and alone exceeded the target, so a compaction kept 13 KB of recent work (real run).
                shortened = [self._shorten(m) for m in batch]
                replacements.update({id(m): s for m, s in zip(batch, shortened) if s is not m})
                originals.update({id(s): m for m, s in zip(batch, shortened)})
                batch = shortened
            # Hysteresis: go well below the threshold, otherwise the next requests compact
            # again for a few kilobytes each, breaking the provider cache every time. The target
            # is a share of the working space above the permanent messages, not of the whole.
            # The latest batch is always kept, if it fits under the threshold itself.
            target = fixed + (threshold - fixed) * COMPACT_TARGET
            if size([*base, *batch, *kept]) > (target if kept else threshold):
                if not kept:
                    return None  # Never silently discard the latest tool outcome.
                break
            kept = [*batch, *kept]
        identities = {id(originals.get(id(m), m)) for m in kept}
        after_messages = [messages[0], memory, *(replacements.get(id(m), m) for m in messages[1:]
            if id(m) in identities or (m.role == 'user' and not m.images and id(m) not in dropped))]
        after = size(after_messages)
        if after >= before:
            return None
        self.memory = memory
        self.state.messages[:] = after_messages
        # Earlier reads left the conversation: the next read must return text again,
        # not "unchanged".
        self.tools.files.reads.clear()
        if hasattr(self.tools, 'requirements_shown'):
            self.tools.requirements_shown.clear()
        event = {'before_bytes': before, 'after_bytes': after, 'archive': archive,
            'summary_requests': 0, 'summary_input_tokens': 0, 'summary_output_tokens': 0}
        self.state.compactions.append(event)
        return event
