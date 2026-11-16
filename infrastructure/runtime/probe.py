"""Explicit provider probe, never run during import or normal configuration loading."""

import json
from .messages import Message, ToolResult
from .model import OpenAIModel, ProviderError


async def probe(profile, *, model=None):
    client = model or OpenAIModel(profile.llm)
    schema = {'type': 'function', 'function': {'name': 'probe_echo',
        'description': 'Echo the provided value. This diagnostic has no side effects.',
        'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}},
            'required': ['value'], 'additionalProperties': False}}}
    messages = [Message('user', 'Call probe_echo once with value arc-probe, then report its result.')]
    try:
        response = await client.respond(messages, [schema])
        if response.finish_reason not in {'stop', 'tool_calls'} or len(response.tool_calls) != 1:
            raise ProviderError('Native tools unverified: probe did not produce one complete call')
        call = response.tool_calls[0]
        if call.name != 'probe_echo' or json.loads(call.arguments) != {'value': 'arc-probe'}:
            raise ProviderError('Native tools unverified: incorrect probe call')
        messages.extend([response.message(), ToolResult(call.id, call.name, 'arc-probe').message()])
        final = await client.respond(messages, [schema])
        if final.finish_reason != 'stop' or final.tool_calls or not final.content:
            raise ProviderError('Native tools unverified: tool-result replay failed')
        return {'native_tools': 'verified', 'tool_result_replay': 'verified',
            'usage': 'reported' if all(r.usage.input_tokens is not None for r in (response, final)) else 'missing',
            'streaming': 'unverified', 'images': 'unverified', 'prompt_cache': 'unverified'}
    finally:
        await client.aclose()
