from __future__ import annotations

from bot_logic import (
    build_social_reply,
    is_final_riddle_message,
    is_partial_riddle_message,
    likely_needs_memory_context,
    looks_like_greeting,
    looks_like_memory_instruction,
    looks_like_passive_closing,
    looks_like_short_acknowledgment,
)
from runtime_types import DecisionResult, NormalizedEvent


def build_normalized_event(
    *,
    event_id: str,
    channel: str,
    author: str,
    timestamp: str,
    text: str,
    metadata: dict | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        type="chat_message",
        channel=channel,
        author=author,
        timestamp=timestamp,
        text=text,
        metadata=metadata or {},
    )


def arbitrate_chat_message(
    *,
    event: NormalizedEvent,
    clean_viewer_message: str,
    author_is_owner: bool,
    riddle_related: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    asks_channel_content: bool,
    repeated_social_count: int = 0,
) -> DecisionResult:
    if asks_channel_content:
        return DecisionResult(
            decision="channel_summary",
            rule_id="channel_content_question",
            reason="viewer asked about channel content",
        )

    if looks_like_memory_instruction(event.text) and not author_is_owner:
        return DecisionResult(
            decision="refuse_memory_instruction",
            rule_id="memory_instruction_non_owner",
            reason="only owner can issue durable memory instructions",
            meta={"reply": "Je ne prends ce type de note mémoire que d'Expevay."},
        )

    if riddle_related and is_partial_riddle_message(event.text):
        return DecisionResult(
            decision="store_only",
            rule_id="riddle_partial_no_reply",
            reason="partial riddle clue should be stored without reply",
            needs_short_memory=True,
        )

    if looks_like_greeting(event.text) or looks_like_passive_closing(event.text):
        return DecisionResult(
            decision="social_reply",
            rule_id="social_greeting_or_closing",
            reason="simple social interaction handled locally",
            meta={"reply": build_social_reply(clean_viewer_message, repeated=repeated_social_count >= 1)},
        )

    if looks_like_short_acknowledgment(event.text):
        return DecisionResult(
            decision="skip_reply",
            rule_id="short_ack_no_reply",
            reason="brief acknowledgment does not require model reply",
            needs_short_memory=True,
        )

    conversation_mode = "riddle_final" if riddle_related and is_final_riddle_message(event.text) else ""
    prefer_active_thread = riddle_related or riddle_thread_reset or riddle_thread_close or likely_needs_memory_context(event.text)

    return DecisionResult(
        decision="model_reply",
        rule_id="model_reply_with_context" if prefer_active_thread else "model_reply_basic",
        reason="viewer addressed bot with a reply-worthy message",
        needs_short_memory=True,
        needs_long_memory=not riddle_related,
        meta={
            "prefer_active_thread": prefer_active_thread,
            "conversation_mode": conversation_mode,
            "specialized_local_thread": riddle_related or riddle_thread_reset or riddle_thread_close,
        },
    )

