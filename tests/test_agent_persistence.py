"""Delivery D, step 19: persisted sessions, controlled resume, checkpoints, isolation."""

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.artifacts import ArtifactStore
from infrastructure.runtime.config import load_profile
from infrastructure.runtime.execution import ExecutionSettings, ProcessManager, Sandbox
from infrastructure.runtime.messages import ModelResponse
from infrastructure.runtime.model import ScriptedModel
from infrastructure.runtime.persistence import ResumeError, RunStore, mask
from tests.verification_support import call, make_agent, profile, simulate_runtime, tools, write_input, FakeTooling


def write(content, identity='w'):
    return tools(call('write_file', identity, path='behaviors.txt', content=content))


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def resumed(self, session, model, **changes):
        agent = ApplicationAgent(self.root / 'app', input_dir=self.root / 'input', model=model,
            profile=profile(**changes), resume=session)
        return agent, FakeTooling(self.root / 'tooling', self.root / 'app'), simulate_runtime(agent)

    async def test_interrupted_run_resumes_the_same_conversation_budget_and_tests(self):
        def interrupted(messages, schemas):
            raise KeyboardInterrupt
        agent, tooling, _ = make_agent(self.root, ScriptedModel([
            tools(call('todo_write', 't', items=[{'id': 'a', 'task': 'register', 'status': 'in_progress', 'requirements': ['REQ-A']}])),
            write('SCN-A-1'), interrupted]), generate=False)
        self.assertEqual((await agent.generate(tooling=tooling)).status, 'interrupted')
        session, requests = agent.state.id, agent.state.requests
        tool_calls = agent.loop.budget.tool_calls
        await agent.aclose()
        saved = json.loads((agent.state.state_directory / 'session.json').read_text())
        self.assertEqual((saved['format_version'], saved['requests'], saved['budget']['tool_calls']), (1, requests, 2))
        self.assertEqual(saved['todos'][0]['id'], 'a')

        model = ScriptedModel([write('SCN-A-1 SCN-A-2', 'fix'), ModelResponse('Done.')])
        agent, tooling, log = self.resumed(session, model, generate=False)
        try:
            self.assertEqual((agent.state.id, agent.state.requests, agent.loop.budget.tool_calls), (session, requests, tool_calls))
            self.assertEqual(agent.state.todos[0]['task'], 'register')
            outcome = await agent.generate(tooling=tooling)
            self.assertEqual(outcome.status, 'accepted')
            self.assertEqual(agent.state.requests, requests + 2)            # Counters continue; nothing is reset.
            history = model.requests[0][0]
            self.assertEqual(sum('Original task context:' in m.content for m in history), 1)
            self.assertIn('resumed from its saved state', history[-1].content)
            self.assertIn('No service is running', history[-1].content)
            self.assertIn('todo_write', [c.name for m in history for c in m.tool_calls])
            summary = json.loads((agent.state.state_directory / 'run-summary.json').read_text())
            self.assertEqual((summary['outcome']['status'], summary['session_id']), ('accepted', session))
            self.assertEqual(summary['fingerprints'], agent.fingerprints)
            kinds = [event['kind'] for event in agent.store.events()]
            self.assertIn('resumed', kinds)
            self.assertIn('tool_finished', kinds)
        finally:
            await agent.aclose()

    async def test_changed_inputs_or_instructions_are_refused_and_file_changes_are_announced(self):
        agent, tooling, _ = make_agent(self.root, ScriptedModel([write('SCN-A-1'), ModelResponse('Done.')]), generate=False)
        await agent.run()
        session = agent.state.id
        await agent.aclose()
        with self.assertRaisesRegex(ResumeError, 'No saved session'):
            self.resumed('0' * 32, ScriptedModel([]))
        with self.assertRaisesRegex(ResumeError, 'profile instructions or policy changed'):
            self.resumed(session, ScriptedModel([]), generate=False, role='Different role.')
        # Raising a limit is not a change of instructions.
        agent, _, _ = self.resumed(session, ScriptedModel([ModelResponse('Continuing.')]), generate=False, max_requests=999)
        try:
            (self.root / 'app/behaviors.txt').write_text('edited outside the session')
            agent._restore()                                                 # Re-read with the changed workspace.
            await agent.run('Carry on.')
            prompt = agent.loop.model.requests[0][0][-1].content
            self.assertIn('workspace files differ', prompt)
            self.assertEqual((self.root / 'app/behaviors.txt').read_text(), 'edited outside the session')  # Never restored.
        finally:
            await agent.aclose()
        (self.root / 'input/requirements.yaml').write_text('id: ROOT\nname: Changed\n')
        with self.assertRaisesRegex(ResumeError, 'input requirements, references or tests changed'):
            self.resumed(session, ScriptedModel([]), generate=False)

    async def test_interrupted_writes_are_recovered_and_secrets_never_reach_disk(self):
        with patch.dict(os.environ, {}, clear=False):
            base = profile(generate=False)
            secret = replace(base, llm=replace(base.llm, api_key='sk-live-PRIVATE-KEY-123456'))
        source = write_input(self.root)
        agent = ApplicationAgent(self.root / 'app', input_dir=source, profile=secret, model=ScriptedModel([
            tools(call('note_write', 'n', contracts=['Authorization: Bearer abcdefghijklmnop1234'],
                established_causes=['key sk-live-PRIVATE-KEY-123456 leaked in a log'], next_checks=[])),
            ModelResponse('Noted.'), ModelResponse('Second turn.')]))
        simulate_runtime(agent)
        try:
            await agent.run()
            await agent.run('Again.')
            directory = agent.state.state_directory
            for name in ('session.json', 'session.json.bak', 'events.jsonl'):
                text = (directory / name).read_text(encoding='utf-8')
                self.assertNotIn('PRIVATE-KEY', text)
                self.assertNotIn('abcdefghijklmnop1234', text)
            good = json.loads((directory / 'session.json').read_text())
            (directory / 'session.json').write_text('{"format_version": 1, "messages": [tru')   # Cut mid-write.
            recovered = agent.store.read_json('session.json')
            self.assertEqual(recovered['session_id'], good['session_id'])
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write('{"kind": "tool_fin')
            self.assertTrue(all('kind' in event for event in agent.store.events()))
        finally:
            await agent.aclose()
        self.assertEqual(mask('token: "abcdefgh12345678" and sk-abcdefghijklmnop'), 'token: "***" and ***')
        store = RunStore(self.root / 'other')
        store.write_json('session.json', {'format_version': 99, 'messages': []})
        with self.assertRaisesRegex(ResumeError, 'No readable'):
            RunStore(self.root / 'missing').read_json('session.json')

    @unittest.skipUnless(shutil.which('git'), 'Git is required for workspace checkpoints')
    async def test_checkpoints_record_the_files_each_verification_ran_on(self):
        agent, tooling, _ = make_agent(self.root, ScriptedModel([write('SCN-A-1'), ModelResponse('Done.'),
            write('SCN-A-1 SCN-A-2', 'fix'), ModelResponse('Fixed.')]), generate=False)
        try:
            outcome = await agent.generate(tooling=tooling)
            self.assertEqual(outcome.status, 'accepted')
            labels = [entry['label'] for entry in agent.checkpoints]
            self.assertEqual(labels, ['verification round 1: failed', 'verification round 3: passed'])
            first, last = (entry['commit'] for entry in agent.checkpoints)
            self.assertTrue(first and last and first != last)
            shown = agent.checkpointer._run('show', first + ':behaviors.txt').stdout
            self.assertEqual(shown, 'SCN-A-1')                               # The failing state can be restored.
            self.assertFalse(agent.checkpointer._run('ls-files', 'node_modules').stdout)
        finally:
            await agent.aclose()

    async def test_two_cases_start_fresh_and_share_no_working_state(self):
        first, _, _ = make_agent(self.root / 'one', ScriptedModel([
            tools(call('note_write', 'n', contracts=['case one contract'], established_causes=[], next_checks=[])),
            ModelResponse('One.')]), generate=False)
        second, _, _ = make_agent(self.root / 'two', ScriptedModel([ModelResponse('Two.')]), generate=False)
        try:
            await first.run()
            await second.run()
            self.assertNotEqual(first.state.id, second.state.id)
            self.assertNotEqual(first.state.state_directory, second.state.state_directory)
            self.assertEqual(second.state.notes['contracts'], [])
            self.assertNotIn('case one contract', json.dumps([m.to_dict() for m in second.state.messages]))
            self.assertEqual(second.state.requests, 1)
            self.assertFalse(second.tools.processes.processes)
            with self.assertRaisesRegex(ValueError, 'inside the input'):
                ApplicationAgent(self.root / 'three/app', input_dir=self.root / 'one/input',
                    state_root=self.root / 'one/input/state', model=ScriptedModel([]))
        finally:
            await first.aclose()
            await second.aclose()


class HostBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_mode_is_explicit_runs_in_the_mirror_and_inherits_no_credentials(self):
        self.assertNotEqual(Sandbox(None, ExecutionSettings(), Path('.')).backend, 'host')   # Never chosen by "auto".
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'private-key'}):
            root = Path(tmp)
            (root / 'app').mkdir()
            (root / 'app/source.txt').write_text('source')
            state = root / 'state'
            manager = ProcessManager(root / 'app', state, ExecutionSettings(backend='host'), ArtifactStore(state))
            try:
                code = ("import os, pathlib; print(os.getenv('OPENAI_API_KEY', 'no-key'), os.getenv('DATABASE_URL'), "
                    "pathlib.Path('source.txt').read_text()); pathlib.Path('made.txt').write_text('made')")
                command = [Path(sys.executable).name, '-c', code]
                with patch('infrastructure.runtime.execution.shutil.which', return_value=sys.executable):
                    result = await manager.run(command, timeout=30, env={'DATABASE_URL': '/workspace/data/app.db'})
                self.assertEqual(result['status'], 'completed', result)
                key, database, source = result['content'].split()
                self.assertEqual((key, source), ('no-key', 'source'))
                self.assertEqual(Path(database), manager.mirror.root.resolve() / 'data/app.db')
                self.assertEqual((root / 'app/made.txt').read_text(), 'made')        # Synchronized like any backend.
                self.assertEqual((await manager.sandbox.check())['isolation'], 'none')
            finally:
                await manager.aclose()
        base = load_profile(environment={})
        self.assertEqual(base.execution.backend, 'host')


if __name__ == '__main__':
    unittest.main()
