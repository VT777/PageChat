from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments_delta: str = ""


@dataclass(slots=True)
class ModelTextDelta:
    delta: str


@dataclass(slots=True)
class ModelReasoningDelta:
    delta: str


@dataclass(slots=True)
class ModelTurn:
    content: str = ""
    tool_calls: list[ModelToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_final_text(self) -> bool:
        return bool(self.content.strip()) and not self.tool_calls
