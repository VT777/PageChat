from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentRunState:
    question: str
    conversation_id: str
    run_id: str
    message_id: str
    scope: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    provider_capabilities: dict[str, Any] = field(default_factory=dict)
