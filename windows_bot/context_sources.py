from __future__ import annotations

from runtime_types import ContextSourceResult


def _normalize_context_text(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else "aucun"


def make_context_source_result(
    source_id: str,
    text_block: str,
    *,
    priority: int,
    confidence: float,
    stale: bool = False,
    meta: dict | None = None,
) -> ContextSourceResult | None:
    normalized = _normalize_context_text(text_block)
    if normalized == "aucun":
        return None
    return ContextSourceResult(
        source_id=source_id,
        available=True,
        priority=priority,
        confidence=confidence,
        stale=stale,
        text_block=normalized,
        meta=meta or {},
    )


def build_context_source_results(
    viewer_context: str = "",
    conversation_context: str = "",
    thread_context: str = "",
    web_context: str = "",
    context_label: str = "",
) -> list[ContextSourceResult]:
    sources: list[ContextSourceResult] = []

    viewer_source_id = "local_specialized" if context_label == "local-specialized" else "local_viewer_thread"
    viewer_source = make_context_source_result(
        viewer_source_id,
        viewer_context,
        priority=100,
        confidence=0.85,
        meta={"context_label": context_label},
    )
    if viewer_source:
        sources.append(viewer_source)

    conversation_source = make_context_source_result(
        "conversation_graph",
        conversation_context,
        priority=90,
        confidence=0.8,
        meta={"context_label": context_label},
    )
    if conversation_source:
        sources.append(conversation_source)

    thread_source = make_context_source_result(
        "thread_context",
        thread_context,
        priority=95,
        confidence=0.9,
        meta={"context_label": context_label},
    )
    if thread_source:
        sources.append(thread_source)

    web_source = make_context_source_result(
        "web",
        web_context,
        priority=95,
        confidence=0.7,
        meta={"context_label": "web"},
    )
    if web_source:
        sources.append(web_source)

    return sources


def merge_context_text(*parts: str) -> str:
    cleaned_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = _normalize_context_text(part)
        if cleaned == "aucun" or cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_parts.append(cleaned)
    return "\n".join(cleaned_parts) if cleaned_parts else "aucun"


def build_auxiliary_context_sources(
    *,
    alias_context: str = "",
    focus_context: str = "",
    facts_context: str = "",
) -> list[ContextSourceResult]:
    sources: list[ContextSourceResult] = []

    alias_source = make_context_source_result(
        "alias_resolution",
        alias_context,
        priority=92,
        confidence=0.9,
        meta={"context_label": "local"},
    )
    if alias_source:
        sources.append(alias_source)

    focus_source = make_context_source_result(
        "recent_focus",
        focus_context,
        priority=89,
        confidence=0.82,
        meta={"context_label": "local"},
    )
    if focus_source:
        sources.append(focus_source)

    facts_source = make_context_source_result(
        "facts_memory",
        facts_context,
        priority=91,
        confidence=0.83,
        meta={"context_label": "local"},
    )
    if facts_source:
        sources.append(facts_source)

    return sources
