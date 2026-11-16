"""Parallel sub-agents for independent parts of the application.

The model's output speed bounds the run (a real run spent 75 % of its time waiting for
about 32 output tokens per second). Independent parts written by concurrent sessions
multiply that throughput. Following Co-Coder (2026), parallelism pays off only with
cohesive partitions: the lead agent first writes the shared contract, then gives each
sub-agent a group of related files it alone may write. Sub-agents only read and write
files; the lead integrates and verifies.
"""

import asyncio
from dataclasses import replace
from hashlib import sha256
import json

from .files import WorkspaceFiles, protected, source_files
from .messages import Message
from .state import SessionState

SUB_TOOLS = ('read_file', 'read_files', 'list_files', 'search_text', 'read_artifact', 'write_file', 'write_files',
    'edit_file', 'apply_patch', 'requirement_catalog', 'read_requirement', 'view_image', 'find_symbol', 'read_skill')
MAX_TASKS = 4
SUB_MAX_REQUESTS = 60  # Per sub-agent and per task; more tasks can always be delegated.

INSTRUCTIONS = '''You are one of several developers writing the same application in parallel.
You own only these paths: {paths}. The others write the rest at the same time: never create or change a file
outside your paths (such writes are refused). Do not run commands, servers or checks; you have no command tool.
The lead developer integrates every part, then builds and verifies the application.

Shared contract decided by the lead (follow it exactly, it is what the other parts rely on):
{contract}

Read the existing files you depend on (contract files, building blocks), all in one read_files call. Then write all
your files, preferably in one write_files call. Use the workspace building blocks instead of rewriting them. Keep the
exact labels, texts and routes the requirements state. Finish with a short reply and no tool call: the files you
wrote, what they export (components, functions, routes) and anything the lead must still connect.'''


def scopes_valid(tasks):
    """Every task writes its own disjoint, writable paths."""
    seen = []
    for task in tasks:
        paths = task['write_paths']
        if not paths:
            raise ValueError(f'Task {task["id"]} needs at least one write path')
        for path in paths:
            clean = path.strip().strip('/')
            if not clean or '..' in clean.split('/') or protected(clean):
                raise ValueError(f'Task {task["id"]}: {path!r} is not a writable application path')
            for other_task, other in seen:
                if clean == other or clean.startswith(other + '/') or other.startswith(clean + '/'):
                    raise ValueError(f'Tasks {other_task} and {task["id"]} would both write {clean}: give each task '
                        'its own files or directories')
            seen.append((task['id'], clean))
    if len({task['id'] for task in tasks}) != len(tasks):
        raise ValueError('Task ids must be unique')


class ScopedFiles(WorkspaceFiles):
    """Workspace files a sub-agent may read anywhere but write only inside its paths."""

    def __init__(self, root, artifacts, prefixes, scope):
        super().__init__(root, artifacts, prefixes)
        self.scope = tuple(path.strip().strip('/') for path in scope)

    def path(self, relative, write=False):
        target = super().path(relative, write)
        if write:
            clean = relative.strip().lstrip('./').strip('/')
            if not any(clean == scope or clean.startswith(scope + '/') for scope in self.scope):
                raise ValueError(f'WRITE_OUTSIDE_SCOPE: you own only {", ".join(self.scope)}; another developer '
                    f'owns {relative}. Mention what it needs in your final reply instead.')
        return target


def snapshot(workspace, scopes):
    return {relative: sha256(path.read_bytes()).hexdigest() for relative, path in source_files(workspace)
        if any(relative == scope or relative.startswith(scope + '/') for scope in scopes)}


async def delegate(lead, contract, tasks):
    """Run each task in its own session, all at once; return their reports in task order."""
    from .loop import AgentLoop
    from .tools import ToolContext, ToolRegistry
    if not 1 <= len(tasks) <= MAX_TASKS:
        raise ValueError(f'Delegate between 1 and {MAX_TASKS} tasks at once')
    scopes_valid(tasks)
    profile, state = lead.profile, lead.state
    optional = {'view_image', 'find_symbol', 'read_skill'}  # Only when the lead has them too.
    allowed = tuple(name for name in SUB_TOOLS if name not in optional or name in profile.tools)
    remaining = max(0, profile.max_requests - state.requests) // len(tasks) if profile.max_requests else 0
    if profile.max_requests and remaining < 3:
        raise ValueError('Not enough model requests remain for sub-agents')
    sub_profile = replace(profile, tools=allowed, max_requests=min(SUB_MAX_REQUESTS, remaining or SUB_MAX_REQUESTS))
    guide = lead.context.workspace / 'BUILDING_BLOCKS.md'
    blocks = guide.read_text(encoding='utf-8')[:8000] if guide.is_file() else ''

    async def run(task):
        scopes = [path.strip().strip('/') for path in task['write_paths']]
        before = snapshot(lead.context.workspace, scopes)
        sub_state = SessionState(lead.context.workspace, id=f'{task["id"]}', state_root=state.state_directory / 'subagents')
        registry = ToolRegistry(ToolContext(lead.context.workspace, sub_state.id, allowed), sub_state, sub_profile,
            lead.catalog)
        # Shared with the lead: artifacts, the execution mirror (file edits stay in sync)
        # and nothing that can start or stop a process.
        registry.artifacts, registry.processes = lead.artifacts, lead.processes
        registry.files = ScopedFiles(lead.context.workspace, lead.artifacts, lead.context.protected, scopes)
        registry.vision_factory = lead.vision_factory

        async def nothing():
            return None
        registry.cancel_actions = nothing
        model = lead.model_factory()
        loop = AgentLoop(sub_state, model, registry, sub_profile)
        loop.budget.clock = lead.budget.clock if lead.budget else loop.budget.clock
        if lead.event_sink:
            loop.on_event = lambda kind, data: lead.event_sink('subagent', {'task': task['id'], 'kind': kind,
                **({key: data[key] for key in ('name', 'code') if key in data})})
        system = '\n\n'.join((profile.role, INSTRUCTIONS.format(paths=', '.join(scopes), contract=contract.strip()[:12000])))
        sub_state.messages.append(Message('system', system))
        requirements = {}
        for identity in task.get('requirements', [])[:20]:
            try:
                requirements[identity] = lead.catalog.read(identity, record=False)['requirement'] if lead.catalog else None
            except ValueError:
                requirements[identity] = 'unknown requirement id'
        prompt = (f'Your task ({task["id"]}): {task["task"]}\n\nRequirements for this part:\n'
            + json.dumps(requirements, ensure_ascii=False)[:30000]
            + (f'\n\nWorkspace building blocks (BUILDING_BLOCKS.md):\n{blocks}' if blocks else ''))
        try:
            result = await loop.run(prompt)
            status, reply = result.status, result.content
        except Exception as error:  # One failed part never discards the others.
            status, reply = 'failed', f'{type(error).__name__}: {str(error)[:300]}'
        finally:
            await model.aclose()
        after = snapshot(lead.context.workspace, scopes)
        changed = sorted(path for path in after.keys() | before.keys() if after.get(path) != before.get(path))
        return task, status, reply, changed, sub_state, loop.budget

    results = await asyncio.gather(*(run(task) for task in tasks))
    reports = []
    for task, status, reply, changed, sub_state, budget in results:
        # The sub-sessions' cost belongs to the run: the lead's loop records the usage.
        state.usage.extend(sub_state.usage)
        state.requests += sub_state.requests
        state.auxiliary_requests += sub_state.requests
        if lead.budget:
            lead.budget.requests['subagent'] = lead.budget.requests.get('subagent', 0) + sub_state.requests
            lead.budget.tool_calls += budget.tool_calls
        reports.append({'id': task['id'], 'status': status, 'files_changed': changed, 'requests': sub_state.requests,
            'reply': (reply or '')[:4000]})
    return {'tasks': reports, 'accepted': False,
        'notice': 'Parts were written in parallel and are not verified. Integrate them (routes, navigation, shared '
            'imports), then run verify_application (kind all).'}

