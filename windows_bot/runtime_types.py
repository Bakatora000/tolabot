from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


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


@dataclass(slots=True)
class RuntimeContextBundle:
    viewer_context: str
    global_context: str
    web_context: str
    context_source: str
    sources: list[ContextSourceResult] = field(default_factory=list)
    conversation_mode: str = ""


@dataclass(slots=True)
class MessagePreparation:
    resolved_text: str
    alias_context: str
    focus_context: str
    facts_context: str
    author_is_owner: bool
    event_type: str
    related_viewer: str
    related_message: str
    related_turn_id: str
    reply_to_turn_id: str
    riddle_related: bool
    riddle_thread_reset: bool
    riddle_thread_close: bool
    specialized_local_thread: bool


@dataclass(slots=True)
class RuntimePipelineDeps:
    persist_local_turn_fn: Callable[..., None]
    persist_local_and_remote_turn_fn: Callable[..., None]
    remember_remote_turn_fn: Callable[..., bool]
    build_runtime_context_bundle_fn: Callable[..., RuntimeContextBundle]
