"""Keep the confirmed baseline while reducing transport overhead and null-query retries."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.text import JSON_OUTPUT_RULE, TextModel, reasoning_arguments


ROOT = Path(__file__).resolve().parents[1]


def site_payloads():
    for domain, controls, action in (
            ('inventory', ['Product', 'Product code', 'Quantity'], 'Persist the edited product and refresh'),
            ('booking', ['Destination', 'Departure date', 'Seat class'], 'Reject unavailable seats without writes'),
            ('checkout', ['Courriel', 'Confirmer le courriel', 'Quantité'], 'Submit once and preserve order identity')):
        yield {'task': {'requirement': {'id': domain, 'description': action,
                    'steps': [{'Given': 'An existing record', 'When': 'Submit', 'Then': action}]},
                'controls': [{'id': str(i), 'label': label, 'type': 'input',
                    'data': [{'var': 'field.' + str(i), 'dtype': 'string', 'constraints': []}]}
                    for i, label in enumerate(controls)]},
            'files': {'frontend/src/Page.tsx': {'content':
                'const message = "Keep  two spaces, a tab:\t, quotes: \\" and Unicode: é";\n'
                'export const Page = () => <form aria-label="Order">{message}</form>;\n', 'writable': True}},
            'feedback': [{'returncode': 1, 'failures': ['Required record must remain unchanged']}],
            'context_kinds': ['schema', 'page'], 'tools': [{'tool': 'read_file', 'parameters': {'type': 'object'}}]}


def captured_request(payload):
    model = TextModel.__new__(TextModel)
    model.name, model.reasoning, model.json_mode, model.max_output_tokens = 'deepseek-flash', 'low', True, 320000
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
        message=SimpleNamespace(content='{"tool_calls":[]}', refusal=None))])
    model._request = Mock(return_value=response)
    result = model.generate_json('Original instructions\n', payload)
    return result, model._request.call_args.kwargs


class ConfirmedBaseline(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'tests/fixtures/fast_review_baseline.json').read_text())

    def test_all_business_prompts_tools_templates_and_checks_match_the_5of5_baseline(self):
        for relative, digest in self.manifest['unchanged_runtime'].items():
            with self.subTest(path=relative):
                self.assertEqual(sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
        for relative, digest in self.manifest.get('new_runtime', {}).items():
            with self.subTest(path=relative):
                self.assertEqual(sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
        actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'infrastructure').rglob('*')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}}
        self.assertEqual(actual, set(self.manifest['infrastructure_inventory']))

    def test_only_documented_service_recovery_transport_and_null_query_changes_differ(self):
        for relative, changes in self.manifest['documented_runtime_edits'].items():
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text(encoding='utf-8')
                for change in reversed(changes):
                    self.assertTrue(change['candidate'])
                    self.assertEqual(text.count(change['candidate']), 1)
                    text = text.replace(change['candidate'], change['baseline'], 1)
                self.assertEqual(sha256(text.encode('utf-8')).hexdigest(),
                    self.manifest['allowed_changes_baseline_normalized'][relative])


class LeanRequests(unittest.TestCase):
    def test_compact_requests_preserve_every_value_source_character_and_provider_setting(self):
        for payload in site_payloads():
            with self.subTest(site=payload['task']['requirement']['id']):
                before = deepcopy(payload)
                result, request = captured_request(payload)
                content = request['messages'][1]['content']
                self.assertEqual(json.loads(content), before)
                self.assertEqual(payload, before)
                self.assertEqual(result, {'tool_calls': []})
                self.assertEqual(request['messages'][0]['content'], 'Original instructions\n' + JSON_OUTPUT_RULE)
                self.assertEqual(request['response_format'], {'type': 'json_object'})
                self.assertEqual(request['model'], 'deepseek-flash')
                for key, value in reasoning_arguments('deepseek-flash', 'low').items():
                    self.assertEqual(request[key], value)
                self.assertLess(len(content.encode('utf-8')),
                    len(json.dumps(before, ensure_ascii=False).encode('utf-8')))
                source = before['files']['frontend/src/Page.tsx']['content']
                self.assertEqual(json.loads(content)['files']['frontend/src/Page.tsx']['content'], source)

    def test_null_context_request_does_not_discard_valid_file_edits(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = 'frontend/src/fix.ts'
            model = Mock(generate_json=Mock(return_value={'context_request': None, 'tool_calls': [
                {'tool': 'edit_file', 'path': path, 'operation': 'create', 'new_content': 'export const fixed = true;'}]}))
            gate = Mock(return_value={'real_checks': 'GREEN'})
            result = run_file_agent(model, '', {}, FileTools(root, [path]), gate, None, Mock(), 'Fix')
            self.assertEqual(model.generate_json.call_count, 1)
            gate.assert_called_once()
            self.assertEqual(result['checks'], {'real_checks': 'GREEN'})
            self.assertTrue((root / path).is_file())

    def test_null_context_request_keeps_a_complete_design_proposal(self):
        model = Mock(generate_json=Mock(return_value={'context_request': None, 'entities': {}}))
        result, _ = propose_json(model, '', {}, lambda response: response['entities'], Mock(), 'Schema',
            context_index=ContextIndex({'schema': {}}))
        self.assertEqual(result, {})
        self.assertEqual(model.generate_json.call_count, 1)

    def test_real_context_queries_still_run_before_the_design_is_accepted(self):
        model = Mock(generate_json=Mock(side_effect=[{'context_request': {'kind': 'schema', 'ids': ['Order']}},
            {'entities': {'Order': {'fields': {}}}}]))
        result, _ = propose_json(model, '', {}, lambda response: response['entities'], Mock(), 'Schema',
            context_index=ContextIndex({'schema': {'Order': {'fields': {}}}}))
        self.assertIn('Order', result)
        self.assertEqual(model.generate_json.call_count, 2)
        request = model.generate_json.call_args.args[1]
        self.assertIn('Order', request['context_records']['schema'])
