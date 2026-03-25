from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedEvent:
    event_id: str
    type: str
    channel: str
    author: str
    timestamp: str
    text: str
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DecisionResult:
    decision: str
    rule_id: str
    reason: str
    needs_short_memory: bool = False
    needs_long_memory: bool = False
    needs_web: bool = False
    allow_spontaneous: bool = False
    query: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        if key == "enabled":
            return self.needs_web
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["enabled"] = self.needs_web
        return payload


@dataclass(slots=True)
class ContextSourceResult:
    source_id: str
    available: bool
    priority: int
    confidence: float
    stale: bool
    text_block: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromptPlan:
    system_block: str
    viewer_block: str
    conversation_block: str
    web_block: str
    style_block: str
    source_trace: list[str] = field(default_factory=list)

