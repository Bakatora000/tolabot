from __future__ import annotations

import re
from collections import Counter

from bot_logic import normalize_spaces, sanitize_user_text
from context_sources import make_context_source_result
from conversation_graph import select_relevant_conversation_turns
from runtime_types import ContextSourceResult, NormalizedEvent

_STOPWORDS = {
    "alors",
    "avec",
    "avoir",
    "aussi",
    "bot",
    "cette",
    "chat",
    "comme",
    "comment",
    "dans",
    "des",
    "donc",
    "elle",
    "elles",
    "encore",
    "est",
    "et",
    "etre",
    "fait",
    "faire",
    "leur",
    "mais",
    "meme",
    "merci",
    "nous",
    "parce",
    "pas",
    "plus",
    "pour",
    "pourquoi",
    "quand",
    "que",
    "quel",
    "quelle",
    "quelles",
    "quels",
    "qui",
    "quoi",
    "sur",
    "toi",
    "ton",
    "tout",
    "tous",
    "une",
    "vous",
}


def _normalize_name(value: str) -> str:
    return normalize_spaces(value).lower().lstrip("@")


def _extract_keywords(texts: list[str], max_keywords: int = 3) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        cleaned = sanitize_user_text(text).lower()
        cleaned = re.sub(r"@([a-zA-Z0-9_]+)", r" \1 ", cleaned)
        for token in re.findall(r"[a-zA-Z0-9_][a-zA-Z0-9_\-']*", cleaned):
            normalized = token.strip("-'_")
            if len(normalized) < 4 or normalized in _STOPWORDS:
                continue
            counter[normalized] += 1
    return [token for token, _ in counter.most_common(max_keywords)]


def _format_graph_turn(turn: dict) -> str:
    speaker = normalize_spaces(turn.get("speaker", "viewer"))
    message_text = sanitize_user_text(turn.get("message_text", ""))
    if not message_text:
        return ""
    return f"{speaker}: {message_text}"


def _format_chat_turn(turn: dict) -> str:
    viewer = normalize_spaces(turn.get("viewer", "viewer"))
    message_text = sanitize_user_text(turn.get("viewer_message", ""))
    if not message_text:
        return ""
    return f"{viewer}: {message_text}"


def _collect_recent_lines(
    *,
    chat_memory: dict,
    conversation_graph: dict,
    channel_name: str,
    current_event: NormalizedEvent,
    max_turns: int,
) -> list[str]:
    normalized_channel = _normalize_name(channel_name)
    normalized_author = _normalize_name(current_event.author)
    channel_turns = list(conversation_graph.get("channels", {}).get(normalized_channel, {}).get("turns", []))[-max_turns:]
    graph_turns = select_relevant_conversation_turns(
        conversation_graph,
        channel_name=normalized_channel,
        viewer_name=normalized_author,
        current_message=current_event.text,
        max_turns=max_turns,
    )
    graph_lines = [_format_graph_turn(turn) for turn in graph_turns]
    graph_lines.extend(_format_graph_turn(turn) for turn in channel_turns)
    deduped_graph_lines: list[str] = []
    seen_lines: set[str] = set()
    for line in graph_lines:
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)
        deduped_graph_lines.append(line)
    graph_lines = deduped_graph_lines
    if graph_lines:
        return graph_lines[-max_turns:]

    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    global_turns = list(channel_data.get("global_turns", []))[-max_turns:]
    chat_lines = [_format_chat_turn(turn) for turn in global_turns]
    return [line for line in chat_lines if line][-max_turns:]


def build_thread_context(
    chat_memory: dict,
    conversation_graph: dict,
    channel_name: str,
    current_event: NormalizedEvent,
    *,
    max_turns: int = 8,
) -> ContextSourceResult | None:
    recent_lines = _collect_recent_lines(
        chat_memory=chat_memory,
        conversation_graph=conversation_graph,
        channel_name=channel_name,
        current_event=current_event,
        max_turns=max_turns,
    )
    if not recent_lines:
        return None

    participants: list[str] = []
    seen_participants: set[str] = set()
    all_texts: list[str] = [current_event.text]
    normalized_channel = _normalize_name(channel_name)
    turns = list(conversation_graph.get("channels", {}).get(normalized_channel, {}).get("turns", []))[-max_turns:]
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    global_turns = list(channel_data.get("global_turns", []))[-max_turns:]

    for turn in turns:
        normalized_speaker = _normalize_name(turn.get("speaker", ""))
        if normalized_speaker and normalized_speaker not in seen_participants:
            seen_participants.add(normalized_speaker)
            participants.append(normalized_speaker)
        message_text = sanitize_user_text(turn.get("message_text", ""))
        if message_text:
            all_texts.append(message_text)

    for turn in global_turns:
        normalized_viewer = _normalize_name(turn.get("viewer", ""))
        if normalized_viewer and normalized_viewer not in seen_participants:
            seen_participants.add(normalized_viewer)
            participants.append(normalized_viewer)
        viewer_message = sanitize_user_text(turn.get("viewer_message", ""))
        if viewer_message:
            all_texts.append(viewer_message)

    for line in recent_lines:
        speaker, _, message = line.partition(":")
        normalized_speaker = _normalize_name(speaker)
        if normalized_speaker and normalized_speaker not in seen_participants:
            seen_participants.add(normalized_speaker)
            participants.append(normalized_speaker)
        all_texts.append(message)

    last_question = ""
    for line in reversed(recent_lines + [f"{current_event.author}: {current_event.text}"]):
        if "?" in line:
            last_question = line
            break

    disagreement = ""
    for turn in reversed(turns):
        if normalize_spaces(turn.get("event_type", "")) in {"correction", "owner_correction"}:
            disagreement = _format_graph_turn(turn)
            if disagreement:
                break

    topic_keywords = _extract_keywords(all_texts)
    summary_lines = [
        f"participants: {', '.join(participants) if participants else _normalize_name(current_event.author) or 'aucun'}",
        f"sujet recent probable: {', '.join(topic_keywords) if topic_keywords else 'aucun'}",
        f"derniere question pertinente: {last_question or 'aucun'}",
        f"dernier tour adresse au bot: {normalize_spaces(current_event.author)}: {sanitize_user_text(current_event.text)}",
    ]
    if disagreement:
        summary_lines.append(f"correction ou desaccord recent: {disagreement}")
    summary_lines.append("tours recents:")
    summary_lines.extend(recent_lines[-max_turns:])

    return make_context_source_result(
        "thread_context",
        "\n".join(summary_lines),
        priority=95,
        confidence=0.9,
        meta={
            "participants": participants,
            "turn_count": max(len(recent_lines), len(turns), len(global_turns)),
        },
    )
