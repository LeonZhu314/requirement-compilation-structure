"""Recover the logged 503 at the HTTP layer without losing a schema requirement."""

from contextlib import nullcontext, redirect_stderr, redirect_stdout
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

from infrastructure.compiler import Compiler
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tasks import StageIncomplete, TaskFailures
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.errors import ModelServiceError
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.files import save_json


def unavailable():
    return httpx.Response(503, headers={'x-request-id': 'provider-test-id'},
        json={'error': {'message': 'Model accounting or configuration is unavailable',
            'type': 'model_proxy_error', 'request_id': None}})


def completion(value):
    return httpx.Response(200, json={'id': 'test-response', 'object': 'chat.completion',
        'model': 'deepseek-flash', 'created': 0,
        'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(value)}}]})


def field(*, primary=False, references=None):
    return {'description': 'Record identity', 'type': 'integer', 'nullable': False,
        'primary_key': primary, 'unique': primary, 'references': references, 'constraints': []}


def requirements():
    return {'id': 'ROOT', 'children': [
        {'id': 'REQ-1', 'name': 'Read current session', 'description': 'Read account and current session.'},
        {'id': 'REQ-2', 'name': 'Register account', 'description': 'Create an account.'}]}


class ModelServiceRecovery(unittest.TestCase):
    def model(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('infrastructure.shared.models.text.load_dotenv'), \
                patch('infrastructure.shared.models.text.http_client', return_value=client), \
                patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only-key',
                    'OPENAI_BASE_URL': 'https://provider.invalid/v1', 'MODEL': 'deepseek-flash',
                    'MODEL_REASONING': 'low', 'MAX_OUTPUT_TOKENS': '320000'}):
            model = TextModel()
        self.addCleanup(model.client.close)
        return model

    def test_sdk_recovers_a_503_beyond_its_previous_retry_budget_with_identical_payload(self):
        requests = []
        def handler(request):
            requests.append(request.content)
            return unavailable() if len(requests) <= 3 else completion({'accepted': True})
        model = self.model(handler)
        with patch('openai._base_client.time.sleep') as sleep, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = model.generate_json('Preserve the original requirement', {'requirement': 'REQ-1'})
        self.assertEqual(result, {'accepted': True})
        self.assertEqual(len(requests), 4)
        self.assertEqual(len(set(requests)), 1)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(sleep.call_args.args, (5,))

    def test_schema_and_obligations_both_keep_every_requirement_after_the_logged_outage(self):
        received = []
        def handler(request):
            envelope = json.loads(request.content)
            payload = json.loads(envelope['messages'][1]['content'])
            rid = payload['requirement']['id']
            received.append((rid, request.content))
            if len(received) <= 3:
                return unavailable()
            if 'related_schema' in payload:
                return completion({'requirement': {'read': ['Account.id'], 'write': []}, 'steps': {}})
            if rid == 'REQ-1':
                return completion({'entities': {
                    'Account': {'description': 'Account', 'fields': {'id': field(primary=True)}},
                    'Session': {'description': 'Session', 'fields': {'id': field(primary=True),
                        'account_id': field(references='Account.id')}}},
                    'related_fields': ['Account.id', 'Session.account_id']})
            return completion({'entities': {}, 'related_fields': ['Account.id']})
        model = self.model(handler)
        schema_stage, obligations_stage = import_module('02_build_db_schema'), import_module('03_infer_db_obligations')
        with TemporaryDirectory() as directory, patch('openai._base_client.time.sleep'), \
                patch.object(schema_stage, 'TextModel', return_value=model), \
                patch.object(obligations_stage, 'TextModel', return_value=model), \
                patch.object(schema_stage, 'DemoConsole', return_value=Mock()), \
                patch.object(obligations_stage, 'DemoConsole', return_value=Mock()), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            arc = Path(directory) / '.arc'
            save_json(arc / 'requirements.json', requirements())
            schema = schema_stage.build_db_schema(arc)
            obligations = obligations_stage.infer_db_obligations(arc)
            self.assertEqual(set(schema['requirements']), {'REQ-1', 'REQ-2'})
            self.assertTrue({'REQ-1', 'REQ-2'} <= set(obligations['requirements']))
            self.assertIn('Account.id', obligations['requirements']['REQ-1']['read'])
            self.assertIn('Account.id', obligations['requirements']['REQ-2']['read'])
        self.assertEqual([rid for rid, _ in received], ['REQ-1'] * 4 + ['REQ-2', 'REQ-1', 'REQ-2'])
        self.assertEqual(len({body for _, body in received[:4]}), 1)

    def test_persistent_503_stops_at_schema_and_does_not_generate_an_unusable_ui(self):
        requests, passes = [], []
        def handler(request):
            requests.append(request.content)
            return unavailable()
        model = self.model(handler)
        schema_stage = import_module('02_build_db_schema')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = Compiler(root / 'input', root / 'output')
            def load(module):
                passes.append(module)
                if module == '00_project_initialization':
                    return SimpleNamespace(project_initialization=lambda *a, **k: [])
                if module == '01_explore_requirement':
                    def publish(source, arc):
                        save_json(arc / 'requirements.json', requirements())
                        return requirements()
                    return SimpleNamespace(explore_requirement=publish)
                if module == '02_build_db_schema':
                    return schema_stage
                self.fail('A provider outage must not start downstream pass ' + module)
            with patch('openai._base_client.time.sleep'), patch.object(schema_stage, 'TextModel', return_value=model), \
                    patch.object(schema_stage, 'DemoConsole', return_value=Mock()), \
                    patch('infrastructure.compiler.import_module', side_effect=load), \
                    patch('infrastructure.compiler.console_log', return_value=nullcontext()), \
                    patch('infrastructure.compiler.checkpoint'), redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
                    self.assertRaises(ModelServiceError) as failure:
                compiler.compile()
            self.assertEqual(len(requests), 4)
            self.assertEqual(len(set(requests)), 1)
            self.assertEqual(passes, ['00_project_initialization', '01_explore_requirement', '02_build_db_schema'])
            self.assertEqual(compiler.report['status'], 'FAILED')
            report = json.loads((compiler.arc_dir / 'compilation.json').read_text())
            provider = report['stages']['02_build_db_schema']['provider']
            self.assertEqual(provider['status_code'], 503)
            self.assertEqual(provider['provider_request_id'], 'provider-test-id')
            self.assertEqual(provider['task'], 'REQ-1')
            self.assertIsInstance(failure.exception.__cause__, Exception)
            self.assertNotIn('frontend_e2e', compiler.artifacts)
            self.assertFalse((compiler.arc_dir / 'ui_design.json').exists())

    def test_authentication_error_is_not_retried_as_a_business_proposal(self):
        requests = []
        def handler(request):
            requests.append(request.content)
            return httpx.Response(401, json={'error': {'message': 'Invalid credentials', 'type': 'authentication_error'}})
        model = self.model(handler)
        with patch('openai._base_client.time.sleep') as sleep, redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
                self.assertRaises(ModelServiceError) as failed:
            model.generate_json('Original instructions', {'task': 'REQ'})
        self.assertEqual(len(requests), 1)
        self.assertEqual(failed.exception.feedback['status_code'], 401)
        sleep.assert_not_called()

    def test_business_validation_failure_still_attempts_neighboring_tasks(self):
        failures = TaskFailures(Path('.'), 'schema', Mock())
        with failures.task('BAD'):
            raise ValueError('Malformed schema proposal')
        with failures.task('GOOD'):
            pass
        with self.assertRaises(StageIncomplete):
            failures.finish()
        self.assertEqual(failures.report['tasks']['GOOD']['status'], 'GREEN')

    def test_timeouts_keep_the_original_sdk_retry_policy(self):
        requests = []
        def handler(request):
            requests.append(request.content)
            raise httpx.ReadTimeout('Simulated timeout', request=request)
        model = self.model(handler)
        with patch('openai._base_client.time.sleep') as sleep, redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
                self.assertRaises(ModelServiceError):
            model.generate_json('Original instructions', {'task': 'REQ'})
        self.assertEqual(len(requests), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_provider_no_retry_header_does_not_trigger_a_recovery_probe(self):
        requests = []
        def handler(request):
            requests.append(request.content)
            response = unavailable()
            response.headers['x-should-retry'] = 'false'
            return response
        model = self.model(handler)
        with patch('openai._base_client.time.sleep') as sleep, redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
                self.assertRaises(ModelServiceError):
            model.generate_json('Original instructions', {'task': 'REQ'})
        self.assertEqual(len(requests), 1)
        sleep.assert_not_called()

    def test_provider_failure_inside_acceptance_does_not_trigger_another_application_edit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = 'frontend/src/page.ts'
            model = Mock(generate_json=Mock(return_value={'tool_calls': [{'tool': 'edit_file',
                'path': path, 'operation': 'create', 'new_content': 'export {};'}]}))
            gate = Mock(side_effect=ModelServiceError('Test-review provider unavailable', status_code=503))
            with patch('infrastructure.shared.agent.loop.checkpoint'), self.assertRaises(ModelServiceError):
                run_file_agent(model, '', {}, FileTools(root, [path]), gate, None, Mock(), 'Implementation')
            self.assertEqual(model.generate_json.call_count, 1)
            gate.assert_called_once()
