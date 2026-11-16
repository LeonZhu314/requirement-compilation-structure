"""Events consumed by callers; a final event is a proposal, not application acceptance."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    session_id: str
    data: dict = field(default_factory=dict)
