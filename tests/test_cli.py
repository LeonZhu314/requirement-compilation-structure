"""Delivery D, steps 20-21: the public CLI runs the agent, never the removed pipeline."""

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

import main as cli
from infrastructure.application_agent import ApplicationAgent
from infrastructure.runtime.execution import EnvironmentUnavailable, Sandbox
from infrastructure.runtime.messages import ToolCall
from infrastructure.runtime.model import ScriptedModel
from infrastructure.verification.driver import Outcome
from tests.verification_support import write_input

ROOT = Path(__file__).resolve().parents[1]
KEY = 'sk-test-PRIVATE-cli-key-0001'


def run(arguments, environment=None):
    out, err = StringIO(), StringIO()
    variables = {'OPENAI_API_KEY': KEY, 'MODEL': 'scripted-model', **(environment or {})}
    with patch.dict(os.environ, variables), patch.object(cli, 'ROOT', Path(os.devnull).parent / 'no-env-here'), \
            redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(arguments)
            code = 0
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = write_input(self.root)
        self.output = self.root / 'generated'

    def test_invalid_invocations_stop_before_any_work(self):
        self.assertEqual(run([str(self.root / 'missing'), '-o', str(self.output)])[0], 2)
        self.assertEqual(run([str(self.input), '-o', str(self.input / 'app')])[0], 2)
        self.assertEqual(run([str(self.input), '-o', str(self.output), '--port', '0'])[0], 2)
        self.assertEqual(run([str(self.input)])[0], 2)
        code, _, err = run([str(self.input), '-o', str(self.output)], {'OPENAI_API_KEY': ''})
        self.assertEqual(code, 2)
        self.assertIn('OPENAI_API_KEY is not set', err)
        code, _, err = run([str(self.input), '-o', str(self.output), '--resume', 'f' * 32])
        self.assertEqual(code, 2)
        self.assertIn('No saved session', err)
        code, _, err = run([str(self.input), '-o', str(self.output), '--max-seconds', '60'])
        self.assertEqual(code, 2)
        self.assertIn('verification reserve', err)
        self.assertFalse((self.output / '.arc').exists())

    def test_check_config_is_offline_and_reports_overrides_without_the_key(self):
        code, out, _ = run(['--check-config', '--max-requests', '7', '--sandbox', 'host'])
        report = json.loads(out)
        self.assertEqual((code, report['max_requests'], report['execution_backend'], report['api_key']), (0, 7, 'host', 'set'))
        self.assertEqual(report['model'], 'scripted-model')
        self.assertNotIn(KEY, out)

    def test_run_reports_the_host_outcome_and_loads_no_pipeline(self):
        seen = {}

        async def generate(agent, task=None, *, tooling=None):
            seen.update(workspace=agent.state.workspace, input=agent.input_dir, port=agent.port,
                requests=agent.profile.max_requests, key=agent.profile.llm.api_key)
            outcome = Outcome('failed', 'verification rounds exhausted', 'proposed', 'Done.',
                {'round': 2, 'clean_state': False, 'status': 'failed', 'stage': 'acceptance', 'stages': []}, 2,
                agent.loop.budget.report(), {'functional': {'failed': 1}, 'visual': {}, 'omissions': ['SCN-A-2']})
            agent.record_outcome(outcome)
            return outcome

        async def available(sandbox):
            return {'backend': 'test'}
        with patch.object(ApplicationAgent, 'generate', generate), patch.object(Sandbox, 'check', available):
            code, out, err = run([str(self.input), '--output-dir', str(self.output), '--port', '3456', '--max-requests', '9'])
        self.assertEqual(code, 1)                                        # A functional failure is a failure.
        self.assertEqual((seen['workspace'], seen['input'], seen['port'], seen['requests'], seen['key']),
            (self.output.resolve(), self.input.resolve(), 3456, 9, KEY))
        report = json.loads(out)
        saved = json.loads((self.output / '.arc/run.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], report['status'])
        self.assertEqual((report['status'], report['cause'], report['accepted']), ('failed', 'verification rounds exhausted', False))
        self.assertEqual(report['resume'], '--resume ' + report['session_id'])
        self.assertIn('Application status: failed', err)
        self.assertNotIn('stage 0', (out + err).lower())
        self.assertNotIn(KEY, out + err + (self.output / '.arc/run.json').read_text(encoding='utf-8'))
        # No numbered pass, compiler or IR: only the application template and the report.
        self.assertFalse([name for name in sys.modules if name[:2].isdigit() or name.startswith(
            ('infrastructure.stages', 'infrastructure.compiler', 'infrastructure.shared.agent', 'lingcore'))])
        self.assertFalse([path.name for path in self.output.rglob('*.json') if path.name in
            {'db_schema.json', 'backend_apis.json', 'ui_design.json', 'frontend_triggers.json', 'compilation.json'}])
        self.assertTrue((self.output / 'deploy.sh').is_file())
        state = Path(report['state_directory'])
        self.assertEqual(state.parent, self.root / '.agent-state')        # Outside the application sources.
        self.assertTrue((state / 'run-summary.json').is_file())

    def test_unavailable_execution_backend_is_reported_before_any_model_request(self):
        async def unavailable(sandbox):
            raise EnvironmentUnavailable('docker is unavailable; install the configured sandbox. No host fallback.')
        with patch.object(Sandbox, 'check', unavailable):
            code, out, err = run([str(self.input), '-o', str(self.output)])
        report = json.loads(out)
        self.assertEqual((code, report['status']), (1, 'environment_error'))
        self.assertIn('docker is unavailable', report['cause'])
        self.assertEqual(report['budget']['requests']['total'], 0)

    def test_exit_codes_distinguish_acceptance_and_interruption(self):
        for status, expected in (('accepted', 0), ('interrupted', 130), ('budget_exceeded', 1), ('verification_missing', 1)):
            async def generate(agent, task=None, *, tooling=None, status=status):
                return Outcome(status)

            async def available(sandbox):
                return {'backend': 'test'}
            with patch.object(ApplicationAgent, 'generate', generate), patch.object(Sandbox, 'check', available):
                code, out, _ = run([str(self.input), '-o', str(self.root / status)])
            self.assertEqual(code, expected, status)
            self.assertEqual(json.loads(out)['resume'] is None, status == 'accepted')

    def test_runner_settings_select_the_backend_and_deliver_unaccepted_work(self):
        code, out, _ = run(['--check-config'], {'AGENT_SANDBOX': 'host'})
        self.assertEqual((code, json.loads(out)['execution_backend']), (0, 'host'))
        self.assertEqual(run(['--check-config'], {'AGENT_SANDBOX': 'none'})[0], 2)
        # Exit 0 only when the agent actually worked; the report keeps the real status.
        for status, calls, expected in (('failed', 12, 0), ('environment_error', 12, 0), ('budget_exceeded', 3, 0),
                ('environment_error', 0, 1), ('provider_error', 0, 1), ('interrupted', 12, 130)):
            async def generate(agent, task=None, *, tooling=None, status=status, calls=calls):
                return Outcome(status, budget={'tool_calls': {'total': calls}})

            async def available(sandbox):
                return {'backend': 'test'}
            with patch.object(ApplicationAgent, 'generate', generate), patch.object(Sandbox, 'check', available):
                code, out, _ = run([str(self.input), '-o', str(self.root / f'{status}{calls}')], {'AGENT_DELIVERY_EXIT': '0'})
            self.assertEqual((code, json.loads(out)['status']), (expected, status))


class RetainedGuaranteeTests(unittest.IsolatedAsyncioTestCase):
    """Guarantees of removed pipeline tests that still matter, on the new tool contract."""

    async def test_crlf_edits_do_not_multiply_newlines_and_large_images_are_reduced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            (root / 'input/requirements.yaml').write_text('id: R\ndescription:\n  image:\n    - id: BIG\n      reference: big.png\n')
            Image.new('RGB', (4000, 3000), 'white').save(root / 'input/big.png')
            from dataclasses import replace
            from infrastructure.runtime.config import load_profile
            agent = ApplicationAgent(root / 'app', input_dir=root / 'input', model=ScriptedModel([]),
                profile=replace(load_profile(environment={}), image_mode='native'))
            try:
                async def tool(name, **arguments):
                    return await agent.tools.execute(ToolCall('c', name, json.dumps(arguments)))
                self.assertIsNone((await tool('write_file', path='notes.txt', content='one\r\ntwo\r\n')).error)
                await tool('edit_file', path='notes.txt', operation='replace', old_content='two', new_content='2\r\n3')
                self.assertEqual((root / 'app/notes.txt').read_bytes(), b'one\n2\n3\n')
                viewed = await tool('view_image', identity='BIG')
                self.assertIsNone(viewed.error)
                with Image.open(BytesIO(agent.tools.artifacts.path(viewed.value['artifact']).read_bytes())) as reduced:
                    self.assertLessEqual(max(reduced.size), 2048)
            finally:
                await agent.aclose()


if __name__ == '__main__':
    unittest.main()
