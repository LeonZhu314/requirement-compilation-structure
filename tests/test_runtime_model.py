import json
import unittest

import httpx
from openai import AsyncOpenAI

from infrastructure.runtime.config import ModelSettings, load_profile
from infrastructure.runtime.messages import Message, ModelResponse, ToolCall, Usage
from infrastructure.runtime.model import OpenAIModel, ProviderError, ScriptedModel
from infrastructure.runtime.probe import probe


class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_native_protocol_and_reasoning_replay_with_mock_http(self):
        requests = []
        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'id': 'response', 'object': 'chat.completion', 'created': 0,
                'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                    'message': {'role': 'assistant', 'content': None, 'reasoning_content': 'retained reasoning',
                        'tool_calls': [{'id': 'call', 'type': 'function',
                            'function': {'name': 'read_file', 'arguments': '{"path":"app.ts"}'}}]}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                    'prompt_tokens_details': {'cached_tokens': 4}, 'completion_tokens_details': {'reasoning_tokens': 2}}})
        sdk = AsyncOpenAI(api_key='test-only', base_url='https://mock.invalid/v1', max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        model = OpenAIModel(ModelSettings(), client=sdk)
        try:
            schema = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}]
            result = await model.respond([Message('user', 'Inspect')], schema)
            await model.respond([result.message(), Message('tool', '{}', tool_call_id='call')], schema)
            self.assertEqual(result.usage, Usage(10, 5, 4, 2))
            self.assertEqual(requests[1]['messages'][0]['reasoning_content'], 'retained reasoning')
            self.assertEqual(requests[0]['tools'], schema)
            self.assertEqual(requests[0]['tool_choice'], 'auto')
            self.assertFalse(requests[0]['stream'])
            self.assertNotIn('response_format', requests[0])
        finally:
            await model.aclose()
        self.assertTrue(sdk.is_closed())

    async def test_provider_error_does_not_echo_response_secrets(self):
        sdk = AsyncOpenAI(api_key='secret-key', base_url='https://mock.invalid/v1', max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:
                httpx.Response(401, json={'error': {'message': 'secret-key', 'type': 'auth'}}))))
        model = OpenAIModel(ModelSettings(), client=sdk)
        try:
            with self.assertRaises(ProviderError) as caught:
                await model.respond([Message('user', 'Task')], [])
            self.assertIn('401', str(caught.exception))
            self.assertNotIn('secret-key', str(caught.exception))
        finally:
            await model.aclose()

    async def test_probe_requires_native_call_and_result_replay(self):
        model = ScriptedModel([ModelResponse(tool_calls=(ToolCall('p', 'probe_echo',
            '{"value":"arc-probe"}'),), finish_reason='tool_calls'), ModelResponse('arc-probe')])
        result = await probe(load_profile(environment={}), model=model)
        self.assertEqual(result['native_tools'], 'verified')
        self.assertEqual(result['usage'], 'missing')
        self.assertEqual(model.requests[1][0][-1].role, 'tool')
        self.assertTrue(model.closed)

    async def test_text_claim_is_not_a_successful_probe(self):
        model = ScriptedModel([ModelResponse('I support native tools')])
        with self.assertRaises(ProviderError):
            await probe(load_profile(environment={}), model=model)
        self.assertTrue(model.closed)
