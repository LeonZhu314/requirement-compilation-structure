"""Native Chat Completions transport and a deterministic offline client."""

from collections import deque
from copy import deepcopy
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

from .messages import Message, ModelResponse, ToolCall, Usage


class ProviderError(RuntimeError):
    """Terminal transport or provider protocol error; never a file-repair observation."""


class ModelClient(Protocol):
    async def respond(self, messages: list[Message], tools: list[dict]) -> ModelResponse: ...
    async def aclose(self) -> None: ...


class ScriptedModel:
    """Scripted responses or callables, with captured requests for offline checks."""
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []
        self.closed = False

    async def respond(self, messages, tools):
        if self.closed:
            raise RuntimeError('Model is closed')
        self.requests.append(deepcopy((messages, tools)))
        if not self.responses:
            raise ProviderError('Script exhausted')
        response = self.responses.popleft()
        return response(messages, tools) if callable(response) else response

    async def aclose(self):
        self.closed = True


class OpenAIModel:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        if client is None and not settings.api_key:
            raise ValueError('OPENAI_API_KEY is required to contact the provider')
        self.client = client or AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
            timeout=settings.timeout_seconds, max_retries=settings.max_retries)

    async def respond(self, messages, tools):
        cfg = self.settings
        arguments = {'model': cfg.model, 'messages': [m.to_wire() for m in messages],
            'stream': False, 'max_completion_tokens': cfg.max_output_tokens}
        if cfg.prompt_cache_key:
            arguments['prompt_cache_key'] = cfg.prompt_cache_key
        if tools:
            arguments.update(tools=tools, tool_choice='auto')
        reasoning = 'low' if cfg.reasoning == 'auto' else cfg.reasoning
        if reasoning != 'provider':
            if cfg.model.lower().startswith('deepseek'):
                arguments['extra_body'] = {'thinking': {'type': 'disabled' if reasoning == 'none' else 'enabled'}}
                if reasoning != 'none':
                    arguments['reasoning_effort'] = reasoning
            else:
                arguments['reasoning_effort'] = reasoning
        try:
            raw_response = await self.client.chat.completions.with_raw_response.create(**arguments)
            response = raw_response.parse()
            retries = getattr(raw_response, 'retries_taken', 0) or 0
        except OpenAIError as error:
            # SDK exception text can contain credentials, URLs or response bodies.
            status = getattr(error, 'status_code', None)
            raise ProviderError(f'{type(error).__name__} (status={status}); check endpoint, credentials and native-tool support') from None
        try:
            choice = response.choices[0]
            message = choice.message
            calls = tuple(ToolCall(c.id, c.function.name, c.function.arguments) for c in message.tool_calls or ())
            raw = response.usage
            usage = Usage(raw.prompt_tokens, raw.completion_tokens,
                getattr(getattr(raw, 'prompt_tokens_details', None), 'cached_tokens', None),
                getattr(getattr(raw, 'completion_tokens_details', None), 'reasoning_tokens', None),
                retries) if raw else Usage(retries=retries)
            result = ModelResponse(message.content or '', calls,
                'refusal' if getattr(message, 'refusal', None) else choice.finish_reason,
                usage, getattr(message, 'reasoning_content', None))
            result.message()  # Validate identifiers before any tool can execute.
            return result
        except (AttributeError, IndexError, TypeError, ValueError):
            raise ProviderError('Invalid provider response: expected content or native function calls with unique ids') from None

    async def aclose(self):
        await self.client.close()
