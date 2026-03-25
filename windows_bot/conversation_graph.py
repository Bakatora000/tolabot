from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from bot_logic import CHAT_MEMORY_TTL_HOURS, normalize_spaces, parse_utc_iso, sanitize_user_text, utc_now, utc_now_iso


CONVERSATION_GRAPH_FILE = "conversation_graph.json"
DEFAULT_GRAPH = {"channels": {}}
MAX_GRAPH_TURNS_PER_CHANNEL = 80
MAX_GRAPH_CONTEXT_LINES = 16
MAX_RELEVANT_GRAPH_TURNS = 10


def _default_channel() -> dict:
    return {"turns": []}


def load_conversation_graph(graph_file: str = CONVERSATION_GRAPH_FILE) -> dict:
    path = Path(graph_file)
    if not path.exists():
        return {"channels": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"channels": {}}

    channels = data.get("channels", {})
    if not isinstance(channels, dict):
        return {"channels": {}}
    return {"channels": channels}


def save_conversation_graph(graph: dict, graph_file: str = CONVERSATION_GRAPH_FILE) -> None:
    Path(graph_file).write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def prune_conversation_graph(graph: dict, ttl_hours: int = CHAT_MEMORY_TTL_HOURS) -> dict:
    cutoff = utc_now()
    cutoff_ts = cutoff.timestamp() - (ttl_hours * 3600)
    pruned_channels: dict[str, dict] = {}

    for channel_name, channel_data in graph.get("channels", {}).items():
        turns = []
        for turn in channel_data.get("turns", []):
            parsed = parse_utc_iso(turn.get("timestamp", ""))
            if parsed and parsed.timestamp() >= cutoff_ts:
                turns.append(turn)
        if turns:
            pruned_channels[channel_name] = {"turns": turns[-MAX_GRAPH_TURNS_PER_CHANNEL:]}

    graph["channels"] = pruned_channels
    return graph


def detect_target_viewers(text: str) -> list[str]:
    import re

    mentions = re.findall(r"@([a-zA-Z0-9_]+)", text or "")
    viewers: list[str] = []
    seen: set[str] = set()
    for mention in mentions:
        normalized = normalize_spaces(mention).lower().lstrip("@")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        viewers.append(normalized)
    return viewers


def append_conversation_turn(
    graph: dict,
    channel_name: str,
    speaker: str,
    message_text: str,
    bot_reply: str = "",
    event_type: str = "message",
    reply_to_turn_id: str = "",
    corrects_turn_id: str = "",
    target_viewers: list[str] | None = None,
    graph_file: str = CONVERSATION_GRAPH_FILE,
    ttl_hours: int = CHAT_MEMORY_TTL_HOURS,
) -> str:
    normalized_channel = normalize_spaces(channel_name).lower()
    normalized_speaker = normalize_spaces(speaker).lower()
    clean_message = sanitize_user_text(message_text)
    clean_reply = sanitize_user_text(bot_reply) if bot_reply else ""
    if not normalized_channel or not normalized_speaker or not clean_message:
        return ""

    turn_id = f"turn_{uuid4().hex[:12]}"
    turn = {
        "turn_id": turn_id,
        "timestamp": utc_now_iso(),
        "speaker": normalized_speaker,
        "message_text": clean_message,
        "bot_reply": clean_reply,
        "event_type": normalize_spaces(event_type.lower()),
        "reply_to_turn_id": normalize_spaces(reply_to_turn_id),
        "corrects_turn_id": normalize_spaces(corrects_turn_id),
        "target_viewers": [normalize_spaces(item).lower() for item in (target_viewers or []) if normalize_spaces(item)],
    }

    channel_data = graph.setdefault("channels", {}).setdefault(normalized_channel, _default_channel())
    channel_data.setdefault("turns", []).append(turn)
    channel_data["turns"] = channel_data["turns"][-MAX_GRAPH_TURNS_PER_CHANNEL:]
    save_conversation_graph(prune_conversation_graph(graph, ttl_hours=ttl_hours), graph_file=graph_file)
    return turn_id


def find_related_conversation_turn(
    graph: dict,
    channel_name: str,
    author_name: str,
    message_text: str,
) -> dict | None:
    normalized_channel = normalize_spaces(channel_name).lower()
    normalized_author = normalize_spaces(author_name).lower()
    lowered_message = sanitize_user_text(message_text).lower()
    targets = set(detect_target_viewers(message_text))
    turns = list(graph.get("channels", {}).get(normalized_channel, {}).get("turns", []))[-MAX_GRAPH_TURNS_PER_CHANNEL:]

    for turn in reversed(turns):
        speaker = normalize_spaces(turn.get("speaker", "")).lower()
        if not speaker or speaker == normalized_author:
            continue

        message_value = sanitize_user_text(turn.get("message_text", "")).lower()
        reply_value = sanitize_user_text(turn.get("bot_reply", "")).lower()
        turn_targets = {normalize_spaces(item).lower() for item in turn.get("target_viewers", [])}

        if targets and (speaker in targets or turn_targets & targets):
            return turn

        if targets and any(target in message_value or target in reply_value for target in targets):
            return turn

        reply_tokens = [token for token in reply_value.split() if len(token) >= 4]
        if reply_tokens and any(token in lowered_message for token in reply_tokens):
            return turn

    return None


def find_reply_target_turn(
    graph: dict,
    channel_name: str,
    author_name: str,
) -> dict | None:
    normalized_channel = normalize_spaces(channel_name).lower()
    normalized_author = normalize_spaces(author_name).lower()
    turns = list(graph.get("channels", {}).get(normalized_channel, {}).get("turns", []))[-MAX_GRAPH_TURNS_PER_CHANNEL:]

    for turn in reversed(turns):
        speaker = normalize_spaces(turn.get("speaker", "")).lower()
        if speaker == normalized_author:
            return turn
    return None


def _channel_turns(graph: dict, channel_name: str) -> list[dict]:
    normalized_channel = normalize_spaces(channel_name).lower()
    return list(graph.get("channels", {}).get(normalized_channel, {}).get("turns", []))[-MAX_GRAPH_TURNS_PER_CHANNEL:]


def _turn_map(turns: list[dict]) -> dict[str, dict]:
    mapped: dict[str, dict] = {}
    for turn in turns:
        turn_id = normalize_spaces(turn.get("turn_id", ""))
        if turn_id:
            mapped[turn_id] = turn
    return mapped


def select_relevant_conversation_turns(
    graph: dict,
    channel_name: str,
    viewer_name: str,
    current_message: str = "",
    max_turns: int = MAX_RELEVANT_GRAPH_TURNS,
) -> list[dict]:
    turns = _channel_turns(graph, channel_name)
    if not turns:
        return []

    normalized_viewer = normalize_spaces(viewer_name).lower()
    lowered_message = sanitize_user_text(current_message).lower()
    targets = set(detect_target_viewers(current_message))
    turn_by_id = _turn_map(turns)

    seeds: list[dict] = []

    related_turn = find_related_conversation_turn(graph, channel_name, normalized_viewer, current_message) if current_message else None
    if related_turn is not None:
        seeds.append(related_turn)

    reply_turn = find_reply_target_turn(graph, channel_name, normalized_viewer)
    if reply_turn is not None:
        seeds.append(reply_turn)

    has_strong_seed = bool(seeds)

    for turn in reversed(turns):
        speaker = normalize_spaces(turn.get("speaker", "")).lower()
        turn_targets = {normalize_spaces(item).lower() for item in turn.get("target_viewers", [])}
        if speaker == normalized_viewer and not has_strong_seed:
            seeds.append(turn)
            continue
        if targets and (speaker in targets or turn_targets & targets):
            seeds.append(turn)
            continue
        if lowered_message and not has_strong_seed:
            message_value = sanitize_user_text(turn.get("message_text", "")).lower()
            bot_reply = sanitize_user_text(turn.get("bot_reply", "")).lower()
            if any(token in lowered_message for token in (message_value.split() + bot_reply.split()) if len(token) >= 5):
                seeds.append(turn)

    selected_ids: set[str] = set()
    queue: list[dict] = []
    for turn in seeds:
        turn_id = normalize_spaces(turn.get("turn_id", ""))
        if turn_id and turn_id not in selected_ids:
            selected_ids.add(turn_id)
            queue.append(turn)

    while queue and len(selected_ids) < max_turns:
        turn = queue.pop(0)
        linked_ids = [
            normalize_spaces(turn.get("reply_to_turn_id", "")),
            normalize_spaces(turn.get("corrects_turn_id", "")),
        ]
        for linked_id in linked_ids:
            if not linked_id or linked_id in selected_ids:
                continue
            linked_turn = turn_by_id.get(linked_id)
            if linked_turn is None:
                continue
            selected_ids.add(linked_id)
            queue.append(linked_turn)
            if len(selected_ids) >= max_turns:
                break

    if not selected_ids:
        return turns[-min(max_turns, len(turns)):]

    selected_turns = [turn for turn in turns if normalize_spaces(turn.get("turn_id", "")) in selected_ids]
    return selected_turns[-max_turns:]


def build_conversation_graph_context(
    graph: dict,
    channel_name: str,
    viewer_name: str,
    current_message: str = "",
    max_lines: int = MAX_GRAPH_CONTEXT_LINES,
) -> str:
    normalized_viewer = normalize_spaces(viewer_name).lower()
    turns = select_relevant_conversation_turns(
        graph,
        channel_name=channel_name,
        viewer_name=viewer_name,
        current_message=current_message,
    )
    if not turns:
        return "aucun"

    lines: list[str] = []
    for turn in turns:
        event_type = normalize_spaces(turn.get("event_type", ""))
        speaker = normalize_spaces(turn.get("speaker", "viewer"))
        message_text = sanitize_user_text(turn.get("message_text", ""))
        bot_reply = sanitize_user_text(turn.get("bot_reply", ""))
        target_viewers = [normalize_spaces(item) for item in turn.get("target_viewers", [])]
        reply_to_turn_id = normalize_spaces(turn.get("reply_to_turn_id", ""))
        corrects_turn_id = normalize_spaces(turn.get("corrects_turn_id", ""))
        if event_type in {"correction", "owner_correction"}:
            if target_viewers:
                lines.append(f"correction vers {', '.join(target_viewers)}: {message_text}")
            else:
                lines.append(f"correction: {message_text}")
        elif reply_to_turn_id:
            lines.append(f"suite de {speaker}: {message_text}")
        elif speaker != normalized_viewer:
            lines.append(f"{speaker}: {message_text}")
        if bot_reply:
            lines.append(f"bot: {bot_reply}")
        if corrects_turn_id:
            lines.append(f"lien correction: {corrects_turn_id}")

    return "\n".join(lines[-max(1, max_lines):]) if lines else "aucun"
