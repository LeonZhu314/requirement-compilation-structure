"""One conversation per application; persistence.py saves and restores it per run."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from .messages import Message, Usage


@dataclass
class SessionState:
    workspace: Path
    id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    requests: int = 0
    usage: list[Usage] = field(default_factory=list)
    status: str = 'ready'
    todos: list[dict] = field(default_factory=list)
    notes: dict = field(default_factory=lambda: {'contracts': [], 'established_causes': [], 'next_checks': []})
    checks: list[dict] = field(default_factory=list)
    compactions: list[dict] = field(default_factory=list)
    auxiliary_requests: int = 0
    # Interfaces the agent observed in its application (routes, reference pages):
    # they help the host locate things and never define expected behavior.
    interfaces: dict = field(default_factory=lambda: {'pages': []})
    verifications: list[dict] = field(default_factory=list)
    state_root: Path | None = None

    @property
    def state_directory(self) -> Path:
        # Host-owned location, separate from the application sources.
        return (self.state_root or self.workspace.parent / '.agent-state') / self.id
