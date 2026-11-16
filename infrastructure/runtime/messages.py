"""Provider-independent, JSON-serializable conversation records."""

from dataclasses import asdict, dataclass, field
import json
from typing import Literal
from pathlib import Path
from hashlib import sha256
import base64


@dataclass(frozen=True)
class ImageAttachment:
    path: str
    mime: str
    sha256: str

    def to_wire(self):
        data = Path(self.path).read_bytes()
        if sha256(data).hexdigest() != self.sha256:
            raise ValueError('Image observation changed since it was recorded')
        return {'type': 'image_url', 'image_url': {'url':
            f'data:{self.mime};base64,' + base64.b64encode(data).decode('ascii')}}


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # Preserve malformed JSON so the tool can return repair feedback.

    def __post_init__(self):
        if not all(isinstance(v, str) for v in (self.id, self.name, self.arguments)) or not self.id or not self.name:
            raise ValueError('Tool calls require a nonempty id/name and JSON argument text')


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    retries: int = 0  # Transport retries the SDK reported for this logical request.


@dataclass(frozen=True)
class Message:
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str = ''
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    images: tuple[ImageAttachment, ...] = ()

    def __post_init__(self):
        if self.role not in {'system', 'user', 'assistant', 'tool'} or not isinstance(self.content, str):
            raise ValueError('Invalid message role/content')
        if self.tool_calls and self.role != 'assistant':
            raise ValueError('Only assistant messages may call tools')
        if (self.role == 'tool') != bool(self.tool_call_id):
            raise ValueError('Tool messages require a call id; other roles cannot have one')
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate tool call ids')
        if self.images and self.role != 'user':
            raise ValueError('Image observations must use a user message after completed tool results')

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict):
        value = dict(value)
        value['tool_calls'] = tuple(ToolCall(**call) for call in value.get('tool_calls', ()))
        value['images'] = tuple(ImageAttachment(**item) for item in value.get('images', ()))
        return cls(**value)

    def to_wire(self) -> dict:
        result = {'role': self.role, 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [{'id': c.id, 'type': 'function',
                'function': {'name': c.name, 'arguments': c.arguments}} for c in self.tool_calls]
        if self.tool_call_id:
            result['tool_call_id'] = self.tool_call_id
        if self.reasoning_content is not None:
            result['reasoning_content'] = self.reasoning_content
        if self.images:
            result['content'] = [{'type': 'text', 'text': self.content}, *(i.to_wire() for i in self.images)]
        return result


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    value: object = None
    error: str | None = None

    def message(self) -> Message:
        return Message('tool', json.dumps({'ok': self.error is None, 'result': self.value,
            'error': self.error}, ensure_ascii=False), tool_call_id=self.call_id)


@dataclass(frozen=True)
class ModelResponse:
    content: str = ''
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = 'stop'
    usage: Usage = field(default_factory=Usage)
    reasoning_content: str | None = None

    def message(self) -> Message:
        return Message('assistant', self.content, self.tool_calls, reasoning_content=self.reasoning_content)
