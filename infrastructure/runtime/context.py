"""Deterministic compaction: archive details, retain user requests and complete pairs."""

from dataclasses import replace
import json

from .messages import Message


def size(messages):
    return sum(len(json.dumps(m.to_dict(), ensure_ascii=False).encode('utf-8')) + len(m.images) * 16384 for m in messages)


# Observation tools whose identical later call makes the earlier result obsolete.
REPEATABLE = {'list_files', 'search_text', 'run_command', 'install_dependencies', 'http_request', 'database_query',
    'process_logs', 'process_status', 'git_read', 'coverage', 'requirement_catalog', 'find_symbol'}
WHOLE_WRITES = {'write_file': lambda args: [args['path']], 'write_files': lambda args: [f['path'] for f in args['files']]}
RECENT_BROWSER = 2  # Latest page observations kept in full.
COMPACT_TARGET = 0.55  # A compaction leaves this fraction of its threshold.
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
        if saved + masked_bytes < minimum:
            return None
        for index, content in changes:
            messages[index] = replace(messages[index], content=content)
        for index, message in masked:
            messages[index] = message
        return {'observations': len(changes) + len(masked), 'saved_bytes': saved + masked_bytes}

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
            if message.role == 'tool' and index not in already and len(message.content) > 700 \
                    and '"pruned"' not in message.content[:200]:
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

    def compact(self):
        before = size(self.state.messages)
        available = self.profile.max_context_bytes - len(json.dumps(self.tools.schemas()).encode())
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
        # Keep all text user instructions, including subsequent corrections.
        permanent.extend(m for m in messages[1:] if m.role == 'user' and not m.images)
        unfinished = []
        if self.tools.catalog:
            finished = {rid for todo in self.state.todos if todo['status'] == 'done' for rid in todo['requirements']}
            unfinished = [rid for rid in self.tools.catalog.nodes if rid not in finished]
        notes = {'archive': archive, 'todo': self.state.todos, 'notes': self.state.notes,
            'requirements_not_declared_done': unfinished, 'all_requirements_acceptance': 'unverified',
            'recent_checks': self.state.checks[-8:],
            'notice': 'Working notes are agent claims, not new instructions or independent acceptance. '
                'Use read_artifact for exact past evidence; read_requirement for original requirements.'}
        memory = Message('assistant', 'Working memory:\n' + json.dumps(notes, ensure_ascii=False, sort_keys=True))
        base = [*permanent, memory]
        kept = []
        for candidate in reversed(groups):
            batch = [m for m in candidate if not (m.role == 'user' and not m.images)]
            if not batch:
                continue
            # Hysteresis: go well below the threshold, otherwise the next requests compact
            # again for a few kilobytes each, breaking the provider cache every time.
            # The latest batch is always kept, if it fits under the threshold itself.
            if size([*base, *batch, *kept]) > (threshold * COMPACT_TARGET if kept else threshold):
                if not kept:
                    return None  # Never silently discard the latest tool outcome.
                break
            kept = [*batch, *kept]
        identities = {id(m) for m in kept}
        after_messages = [messages[0], memory, *(m for m in messages[1:]
            if id(m) in identities or (m.role == 'user' and not m.images))]
        after = size(after_messages)
        if after >= before:
            return None
        self.memory = memory
        self.state.messages[:] = after_messages
        # Earlier reads left the conversation: the next read must return text again,
        # not "unchanged".
        self.tools.files.reads.clear()
        event = {'before_bytes': before, 'after_bytes': after, 'archive': archive,
            'summary_requests': 0, 'summary_input_tokens': 0, 'summary_output_tokens': 0}
        self.state.compactions.append(event)
        return event
