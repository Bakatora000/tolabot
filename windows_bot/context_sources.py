from __future__ import annotations

from runtime_types import ContextSourceResult


def _normalize_context_text(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else "aucun"


def build_context_source_results(
    viewer_context: str = "",
    conversation_context: str = "",
    web_context: str = "",
    context_label: str = "",
) -> list[ContextSourceResult]:
    sources: list[ContextSourceResult] = []

    if viewer_context and viewer_context != "aucun":
        sources.append(
            ContextSourceResult(
                source_id="viewer_context",
                available=True,
                priority=100,
                confidence=0.85,
                stale=False,
                text_block=_normalize_context_text(viewer_context),
                meta={"context_label": context_label},
            )
        )

    if conversation_context and conversation_context != "aucun":
        sources.append(
            ContextSourceResult(
                source_id="conversation_context",
                available=True,
                priority=90,
                confidence=0.8,
                stale=False,
                text_block=_normalize_context_text(conversation_context),
                meta={"context_label": context_label},
            )
        )

    if web_context and web_context != "aucun":
        sources.append(
            ContextSourceResult(
                source_id="web_context",
                available=True,
                priority=95,
                confidence=0.7,
                stale=False,
                text_block=_normalize_context_text(web_context),
                meta={"context_label": "web"},
            )
        )

    return sources

