import html
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from conversation_rules import (
    CHANNEL_CONTENT_TRIGGERS,
    CORRECTION_TRIGGERS,
    GREETING_TRIGGERS,
    MEMORY_CONTEXT_TRIGGERS,
    MEMORY_INSTRUCTION_TRIGGERS,
    NEW_RIDDLE_THREAD_TRIGGERS,
    NO_REPLY_SIGNALS,
    PASSIVE_CLOSING_TRIGGERS,
    PROMPT_INJECTION_PATTERNS,
    RIDDLE_CLOSE_TRIGGERS,
    RIDDLE_FINAL_MARKERS,
    RIDDLE_REFUSAL_PATTERNS,
    RIDDLE_TRIGGERS,
    SHORT_ACKNOWLEDGMENT_TRIGGERS,
    SUSPICIOUS_OUTPUT_PATTERNS,
    contains_any_pattern,
)
from decision_tree import classify_social_intent, get_social_reply_template

BOT_USERNAME = "anneaunimouss"
BOT_TRIGGER = "@anneaunimouss"

MAX_INPUT_CHARS = 350
MAX_OUTPUT_CHARS = 500
GLOBAL_COOLDOWN_SECONDS = 2
USER_COOLDOWN_SECONDS = 8

HISTORY_FILE = "channel_history.json"
MAX_HISTORY_SESSIONS = 60
CHAT_MEMORY_FILE = "chat_memory.json"
MAX_GLOBAL_CHAT_TURNS = 12
MAX_VIEWER_CHAT_TURNS = 6
MAX_GLOBAL_CONTEXT_LINES = 20
CHAT_MEMORY_TTL_HOURS = 10
SOCIAL_REDUNDANCY_WINDOW_MINUTES = 5


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_ts() -> float:
    return time.monotonic()


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sanitize_user_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\r", " ").replace("\n", " ")
    return normalize_spaces(text)


def smart_truncate(text: str, max_chars: int) -> str:
    suffix = "[...]"
    text = normalize_spaces(text)
    if len(text) <= max_chars:
        return text

    if max_chars <= len(suffix):
        return suffix[:max_chars]

    limit = max_chars - len(suffix)
    clipped = text[:limit + 1].strip()

    sentence_breaks = [". ", "! ", "? ", "… ", ".", "!", "?", "…"]
    best_sentence_cut = -1
    for marker in sentence_breaks:
        idx = clipped.rfind(marker)
        if idx > best_sentence_cut:
            best_sentence_cut = idx + (0 if marker in {".", "!", "?", "…"} else 1)

    if best_sentence_cut >= int(max_chars * 0.6):
        return clipped[:best_sentence_cut].strip() + suffix

    word_cut = clipped.rfind(" ")
    if word_cut >= int(max_chars * 0.6):
        return clipped[:word_cut].strip() + suffix

    return text[:limit].rstrip() + suffix


def strip_trigger(text: str) -> str:
    text = re.sub(r"@anneaunimouss\b", "", text, flags=re.IGNORECASE)
    return normalize_spaces(text)


def looks_like_prompt_injection(text: str) -> bool:
    return contains_any_pattern(text.lower(), PROMPT_INJECTION_PATTERNS)


def output_is_suspicious(text: str) -> bool:
    return contains_any_pattern(text.lower(), SUSPICIOUS_OUTPUT_PATTERNS)


def is_no_reply_signal(text: str) -> bool:
    normalized = normalize_spaces((text or "").lower())
    normalized = re.sub(r"[.!?…]+$", "", normalized).strip()
    return normalized in NO_REPLY_SIGNALS


def normalize_web_sourced_reply(text: str, web_context: str = "") -> str:
    cleaned = (text or "").strip()
    if not cleaned or not web_context or web_context == "aucun":
        return cleaned

    replacements = (
        (r"^d['’]apres ce que tu m['’]as dit[, ]*", "Selon les sources web, "),
        (r"^d['’]après ce que tu m['’]as dit[, ]*", "Selon les sources web, "),
        (r"^d['’]apres le contexte[, ]*", "Selon les sources web, "),
        (r"^d['’]après le contexte[, ]*", "Selon les sources web, "),
        (r"^dans le contexte[, ]*", "Selon les sources web, "),
    )
    normalized = cleaned
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^Selon les sources web,\s*dans le contexte[, ]*", "Selon les sources web, ", normalized, flags=re.IGNORECASE)
    return normalized


def asks_about_channel_content(text: str) -> bool:
    lowered = strip_trigger(text).lower()
    return contains_any_pattern(lowered, CHANNEL_CONTENT_TRIGGERS)


def looks_like_memory_instruction(text: str) -> bool:
    lowered = strip_trigger(text).lower()
    return contains_any_pattern(lowered, MEMORY_INSTRUCTION_TRIGGERS)


def build_no_reply_fallback(text: str, riddle_related: bool = False) -> str:
    if riddle_related:
        return "J'ai lu ton message, mais il me manque encore un peu de contexte pour répondre correctement."
    if looks_like_passive_closing(text) or looks_like_greeting(text):
        return ""
    lowered = strip_trigger(text).lower()
    if "pourquoi" in lowered:
        return "J'ai lu ton message. Reformule ou précise un peu si tu veux une réponse plus nette."
    if "?" in lowered:
        return "J'ai lu ton message. Si tu veux, reformule un peu et je te répondrai plus clairement."
    return "J'ai lu ton message. Si tu veux une réponse utile, reformule un peu ou précise ta demande."


def looks_like_riddle_message(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, RIDDLE_TRIGGERS)


def likely_needs_memory_context(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, MEMORY_CONTEXT_TRIGGERS)


def looks_like_correction_message(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, CORRECTION_TRIGGERS)


def looks_like_short_acknowledgment(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    lowered = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœæ]+", " ", lowered)
    lowered = normalize_spaces(lowered)
    if not lowered:
        return False
    return classify_social_intent(lowered) == "short_ack"


def looks_like_passive_closing(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    lowered = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœæ]+", " ", lowered)
    lowered = normalize_spaces(lowered)
    if not lowered:
        return False
    return classify_social_intent(lowered) == "closing"


def looks_like_greeting(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    lowered = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœæ]+", " ", lowered)
    lowered = normalize_spaces(lowered)
    if not lowered:
        return False
    return classify_social_intent(lowered) == "greeting"


def build_social_reply(text: str, repeated: bool = False) -> str:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    lowered = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœæ]+", " ", lowered)
    lowered = normalize_spaces(lowered)
    intent = classify_social_intent(lowered)
    if intent == "greeting":
        return get_social_reply_template("greeting", repeated=repeated)
    if intent == "closing":
        return get_social_reply_template("closing", repeated=repeated)
    return ""


def normalize_name_token(text: str) -> str:
    cleaned = normalize_spaces(text).strip().lstrip("@")
    cleaned = re.sub(r"^[^a-zA-Z0-9_]+|[^a-zA-Z0-9_]+$", "", cleaned)
    return cleaned


def extract_name_candidates(text: str) -> list[str]:
    cleaned = sanitize_user_text(strip_trigger(text or ""))
    if not cleaned:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    stop_words = {
        "anneaunimouss", "viewer", "bot", "bonjour", "salut", "hello", "bonsoir",
        "quelle", "quel", "quelles", "quels", "relation", "groupe", "trio", "nom",
        "partie", "communautaire", "concernant", "toujours", "souvenir", "rappelles",
        "rappelle", "sais", "sait", "dire", "fait", "faites", "faire", "avec",
        "quand", "parle", "parlais", "parlait", "parler", "elle", "elles", "lui",
        "eux", "son", "sa", "ses", "ce", "cet", "cette", "gaby", "dame",
    }

    def _push(candidate: str) -> None:
        normalized = normalize_name_token(candidate)
        lowered = normalized.lower()
        if not normalized or lowered in stop_words or lowered in seen:
            return
        if len(normalized) < 3:
            return
        seen.add(lowered)
        candidates.append(normalized)

    for mention in extract_mentions(cleaned):
        _push(mention)

    for token in re.findall(r"\b[a-zA-Z0-9]*_[a-zA-Z0-9_]+\b", cleaned):
        _push(token)

    for token in re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,}\b", cleaned):
        _push(token)

    return candidates


def extract_alias_pairs(text: str) -> list[tuple[str, str]]:
    cleaned = sanitize_user_text(strip_trigger(text))
    if not cleaned:
        return []

    pairs: list[tuple[str, str]] = []

    simple_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+aussi\s+\b([@a-zA-Z0-9_]+)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if simple_match:
        canonical = normalize_name_token(simple_match.group(1))
        alias = normalize_name_token(simple_match.group(2))
        if canonical and alias and canonical.lower() != alias.lower():
            pairs.append((canonical, alias))

    same_person_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+la\s+m[êe]me\s+personne\s+(?:que|de)\s+\b([@a-zA-Z0-9_]+)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if same_person_match:
        canonical = normalize_name_token(same_person_match.group(1))
        alias = normalize_name_token(same_person_match.group(2))
        if canonical and alias and canonical.lower() != alias.lower():
            pairs.append((canonical, alias))

    reported_alias_match = re.search(
        r"quand\s+on\s+te\s+parle\s+de\s+[\"“]?([^\"”]+)[\"”]?\s+il\s+s['’]agit\s+de\s+([@a-zA-Z0-9_ ]+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if reported_alias_match:
        alias = normalize_name_token(reported_alias_match.group(1))
        canonical = normalize_name_token(reported_alias_match.group(2))
        if canonical and alias and canonical.lower() != alias.lower():
            pairs.append((canonical, alias))

    called_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+le\s+plus\s+souvent\s+appel\w+\s+(.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if called_match:
        canonical = normalize_name_token(called_match.group(1))
        aliases_part = called_match.group(2)
        alias_candidates = re.split(r"\b(?:ou|et)\b|,", aliases_part, flags=re.IGNORECASE)
        for candidate in alias_candidates:
            alias = normalize_name_token(candidate)
            if canonical and alias and canonical.lower() != alias.lower():
                pairs.append((canonical, alias))

    deduped: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for canonical, alias in pairs:
        key = (canonical.lower(), alias.lower())
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped.append((canonical, alias))
    return deduped


def build_channel_alias_index(chat_memory: dict, channel_name: str) -> dict[str, str]:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    alias_index: dict[str, str] = {}

    for turn in channel_data.get("global_turns", []):
        for canonical, alias in extract_alias_pairs(turn.get("viewer_message", "")):
            alias_index.setdefault(canonical.lower(), canonical)
            alias_index[alias.lower()] = canonical

    return alias_index


def infer_recent_focus(chat_memory: dict, channel_name: str, viewer_name: str) -> dict[str, str]:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_viewer = normalize_spaces((viewer_name or "").lower())
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    viewer_turns = list(channel_data.get("viewer_turns", {}).get(normalized_viewer, []))[-MAX_VIEWER_CHAT_TURNS:]

    subject = ""
    group_name = ""

    for turn in reversed(viewer_turns):
        if not subject:
            for source_text in (turn.get("viewer_message", ""), turn.get("bot_reply", "")):
                candidates = extract_name_candidates(source_text)
                if candidates:
                    subject = candidates[0]
                    break
        if not group_name:
            for source_text in (turn.get("viewer_message", ""), turn.get("bot_reply", "")):
                match = re.search(r"\b(les\s+[A-Z][a-zA-Z0-9_]+)\b", source_text or "")
                if match:
                    group_name = sanitize_user_text(match.group(1))
                    break
        if subject and group_name:
            break

    return {
        "subject": subject,
        "group_name": group_name,
    }


def resolve_recent_reference_subjects(text: str, focus: dict[str, str] | None = None) -> tuple[str, list[str]]:
    cleaned = sanitize_user_text(text)
    if not cleaned:
        return cleaned, []

    focus = focus or {}
    subject = normalize_name_token(focus.get("subject", ""))
    group_name = sanitize_user_text(focus.get("group_name", ""))
    notes: list[str] = []
    rewritten = cleaned
    lowered = cleaned.lower()

    if subject and any(fragment in lowered for fragment in (" elle ", " lui ", " concernant elle", " a propos d'elle")):
        rewritten = re.sub(r"\belle\b", subject, rewritten, flags=re.IGNORECASE)
        rewritten = re.sub(r"\blui\b", subject, rewritten, flags=re.IGNORECASE)
        if rewritten != cleaned:
            notes.append(f"sujet recent: {subject}")
            lowered = rewritten.lower()

    if subject and any(fragment in lowered for fragment in ("quel groupe", "ce groupe", "son groupe", "leur groupe")):
        if subject.lower() not in lowered:
            rewritten = f"{rewritten.rstrip(' ?.!')} de {subject} ?"
            notes.append(f"question rattachee a: {subject}")
            lowered = rewritten.lower()

    if group_name and "ce groupe" in lowered:
        rewritten = re.sub(r"\bce groupe\b", group_name, rewritten, flags=re.IGNORECASE)
        if f"groupe recent: {group_name}" not in notes:
            notes.append(f"groupe recent: {group_name}")

    deduped_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        lowered_note = note.lower()
        if lowered_note in seen_notes:
            continue
        seen_notes.add(lowered_note)
        deduped_notes.append(note)
    return rewritten, deduped_notes


def resolve_known_aliases(text: str, alias_index: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    cleaned = sanitize_user_text(text)
    if not cleaned or not alias_index:
        return cleaned, []

    replacements: list[tuple[str, str]] = []
    resolved = cleaned
    alias_keys = sorted(alias_index.keys(), key=len, reverse=True)

    for alias_key in alias_keys:
        canonical = alias_index.get(alias_key, "")
        if not canonical or alias_key == canonical.lower():
            continue
        pattern = re.compile(rf"\b{re.escape(alias_key)}\b", flags=re.IGNORECASE)
        if not pattern.search(resolved):
            continue
        resolved = pattern.sub(canonical, resolved)
        replacements.append((alias_key, canonical))

    deduped_replacements: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for alias_key, canonical in replacements:
        key = (alias_key.lower(), canonical.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped_replacements.append((alias_key, canonical))
    return resolved, deduped_replacements


def extract_mentions(text: str) -> list[str]:
    mentions = re.findall(r"@([a-zA-Z0-9_]+)", text or "")
    normalized = []
    seen = set()
    for mention in mentions:
        clean = normalize_spaces(mention).lower().lstrip("@")
        if not clean or clean == BOT_USERNAME or clean in seen:
            continue
        seen.add(clean)
        normalized.append(clean)
    return normalized


def detect_referenced_viewers(text: str) -> list[str]:
    cleaned = sanitize_user_text(strip_trigger(text)).lower()
    viewers = extract_mentions(cleaned)
    if viewers:
        return viewers

    fallback_names = re.findall(r"\b([a-z][a-z0-9_]{2,})\b", cleaned)
    candidates = []
    seen = set()
    stop_words = {
        "que", "pense", "penses", "parlait", "parlait", "pas", "bot",
        "dame", "gaby", "streamer", "viewer", "de", "et", "il", "elle",
        "je", "tu", "as", "confondu", "voulait", "voulais", "dire",
    }
    for item in fallback_names:
        if item in stop_words or item in seen:
            continue
        seen.add(item)
        candidates.append(item)
    return candidates[:3]


def classify_conversation_event(text: str, author_is_owner: bool = False) -> str:
    if looks_like_correction_message(text):
        return "owner_correction" if author_is_owner else "correction"
    if looks_like_memory_instruction(text):
        return "memory_instruction"
    if looks_like_riddle_message(text):
        return "riddle"
    return "message"


def find_related_global_turn(
    chat_memory: dict,
    channel_name: str,
    message_text: str,
    author_name: str = "",
) -> dict | None:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_author = normalize_spaces((author_name or "").lower())
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    global_turns = list(channel_data.get("global_turns", []))[-MAX_GLOBAL_CHAT_TURNS:]
    referenced_viewers = set(detect_referenced_viewers(message_text))
    lowered_message = sanitize_user_text(strip_trigger(message_text)).lower()

    for turn in reversed(global_turns):
        turn_viewer = normalize_spaces(turn.get("viewer", "").lower())
        if not turn_viewer or turn_viewer == normalized_author:
            continue

        if referenced_viewers and turn_viewer in referenced_viewers:
            return turn

        turn_message = sanitize_user_text(turn.get("viewer_message", "")).lower()
        turn_reply = sanitize_user_text(turn.get("bot_reply", "")).lower()

        if any(reference in turn_message or reference in turn_reply for reference in referenced_viewers):
            return turn

        if turn_reply and any(token in lowered_message for token in turn_reply.split() if len(token) >= 4):
            return turn

    return None


def starts_new_riddle_thread(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, NEW_RIDDLE_THREAD_TRIGGERS)


def closes_riddle_thread(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, RIDDLE_CLOSE_TRIGGERS)


def is_partial_riddle_message(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    has_partial_clue = any(
        marker in lowered
        for marker in ("mon premier", "mon second", "mon troisième", "mon troisieme")
    )
    asks_final_solution = any(
        marker in lowered
        for marker in ("mon tout", "qui suis-je", "qui suis je", "solution", "reponse", "réponse")
    )
    return has_partial_clue and not asks_final_solution


def is_final_riddle_message(text: str) -> bool:
    lowered = sanitize_user_text(strip_trigger(text)).lower()
    return contains_any_pattern(lowered, RIDDLE_FINAL_MARKERS)


def is_riddle_refusal_reply(text: str) -> bool:
    lowered = normalize_spaces((text or "").lower())
    return contains_any_pattern(lowered, RIDDLE_REFUSAL_PATTERNS)


def load_history(history_file: str = HISTORY_FILE) -> dict:
    if not os.path.exists(history_file):
        return {"sessions": [], "current_session": None}

    try:
        with open(history_file, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        data.setdefault("sessions", [])
        data.setdefault("current_session", None)
        return data
    except Exception:
        return {"sessions": [], "current_session": None}


def load_chat_memory(chat_memory_file: str = CHAT_MEMORY_FILE) -> dict:
    if not os.path.exists(chat_memory_file):
        return {"channels": {}, "meta": {"memory_helpful_replies": 0, "riddle_messages_seen": 0}}

    try:
        with open(chat_memory_file, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        if "channels" in data:
            data.setdefault("channels", {})
            data.setdefault("meta", {})
            data["meta"]["memory_helpful_replies"] = int(data["meta"].get("memory_helpful_replies", 0) or 0)
            data["meta"]["riddle_messages_seen"] = int(data["meta"].get("riddle_messages_seen", 0) or 0)
            return data
        if "global_turns" in data or "viewer_turns" in data:
            return {
                "channels": {
                    "default": {
                        "global_turns": data.get("global_turns", []),
                        "viewer_turns": data.get("viewer_turns", {}),
                    }
                },
                "meta": {"memory_helpful_replies": 0, "riddle_messages_seen": 0},
            }
        return {"channels": {}, "meta": {"memory_helpful_replies": 0, "riddle_messages_seen": 0}}
    except Exception:
        return {"channels": {}, "meta": {"memory_helpful_replies": 0, "riddle_messages_seen": 0}}


def parse_utc_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def prune_chat_memory(chat_memory: dict, ttl_hours: int = CHAT_MEMORY_TTL_HOURS) -> dict:
    cutoff = utc_now() - timedelta(hours=ttl_hours)
    pruned_channels = {}

    for channel_name, channel_data in chat_memory.get("channels", {}).items():
        global_turns = []
        for turn in channel_data.get("global_turns", []):
            timestamp = parse_utc_iso(turn.get("timestamp", ""))
            if timestamp and timestamp >= cutoff:
                global_turns.append(turn)

        global_turns = global_turns[-MAX_GLOBAL_CHAT_TURNS:]

        viewer_turns = {}
        for viewer_name, turns in channel_data.get("viewer_turns", {}).items():
            recent_turns = []
            for turn in turns:
                timestamp = parse_utc_iso(turn.get("timestamp", ""))
                if timestamp and timestamp >= cutoff:
                    recent_turns.append(turn)
            if recent_turns:
                viewer_turns[viewer_name] = recent_turns[-MAX_VIEWER_CHAT_TURNS:]

        if global_turns or viewer_turns:
            pruned_channels[channel_name] = {
                "global_turns": global_turns,
                "viewer_turns": viewer_turns,
            }

    chat_memory["channels"] = pruned_channels
    return chat_memory


def save_chat_memory(chat_memory: dict, chat_memory_file: str = CHAT_MEMORY_FILE) -> None:
    chat_memory = prune_chat_memory(chat_memory)
    normalized_channels = {}
    meta = chat_memory.get("meta", {})

    for channel_name, channel_data in chat_memory.get("channels", {}).items():
        normalized_channel = normalize_spaces(str(channel_name).lower())
        if not normalized_channel:
            continue

        global_turns = channel_data.get("global_turns", [])[-MAX_GLOBAL_CHAT_TURNS:]
        viewer_turns = {}
        for viewer_name, turns in channel_data.get("viewer_turns", {}).items():
            normalized_viewer = normalize_spaces(str(viewer_name).lower())
            if not normalized_viewer:
                continue
            viewer_turns[normalized_viewer] = turns[-MAX_VIEWER_CHAT_TURNS:]

        normalized_channels[normalized_channel] = {
            "global_turns": global_turns,
            "viewer_turns": viewer_turns,
        }

    chat_memory["channels"] = normalized_channels
    chat_memory["meta"] = {
        "memory_helpful_replies": int(meta.get("memory_helpful_replies", 0) or 0),
        "riddle_messages_seen": int(meta.get("riddle_messages_seen", 0) or 0),
    }

    with open(chat_memory_file, "w", encoding="utf-8") as file_obj:
        json.dump(chat_memory, file_obj, ensure_ascii=False, indent=2)


def append_chat_turn(
    chat_memory: dict,
    channel_name: str,
    viewer_name: str,
    viewer_message: str,
    bot_reply: str = "",
    chat_memory_file: str = CHAT_MEMORY_FILE,
    ttl_hours: int = CHAT_MEMORY_TTL_HOURS,
    thread_boundary: str = "",
    event_type: str = "",
    related_viewer: str = "",
    related_message: str = "",
) -> None:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_viewer = normalize_spaces((viewer_name or "").lower())
    clean_viewer_message = sanitize_user_text(viewer_message)[:MAX_INPUT_CHARS]
    clean_bot_reply = sanitize_user_text(bot_reply)[:MAX_OUTPUT_CHARS] if bot_reply else ""

    if not normalized_channel or not normalized_viewer or not clean_viewer_message:
        return

    turn = {
        "timestamp": utc_now_iso(),
        "channel": normalized_channel,
        "viewer": normalized_viewer,
        "viewer_message": clean_viewer_message,
        "bot_reply": clean_bot_reply,
        "thread_boundary": normalize_spaces(thread_boundary.lower()),
        "event_type": normalize_spaces(event_type.lower()),
        "related_viewer": normalize_spaces(related_viewer.lower()),
        "related_message": sanitize_user_text(related_message)[:MAX_INPUT_CHARS] if related_message else "",
    }

    channels = chat_memory.setdefault("channels", {})
    channel_data = channels.setdefault(normalized_channel, {"global_turns": [], "viewer_turns": {}})
    channel_data.setdefault("global_turns", []).append(turn)
    viewer_turns = channel_data.setdefault("viewer_turns", {})
    viewer_turns.setdefault(normalized_viewer, []).append(turn)
    save_chat_memory(prune_chat_memory(chat_memory, ttl_hours=ttl_hours), chat_memory_file=chat_memory_file)


def format_chat_turns(turns: list[dict]) -> str:
    lines = []
    for turn in turns:
        viewer = normalize_spaces(turn.get("viewer", "viewer"))
        viewer_message = sanitize_user_text(turn.get("viewer_message", ""))
        bot_reply = sanitize_user_text(turn.get("bot_reply", ""))
        event_type = normalize_spaces(turn.get("event_type", ""))
        related_viewer = normalize_spaces(turn.get("related_viewer", ""))
        related_message = sanitize_user_text(turn.get("related_message", ""))
        if not viewer_message:
            continue
        if event_type in {"correction", "owner_correction"}:
            correction_prefix = "correction"
            if related_viewer:
                correction_prefix += f" pour {related_viewer}"
            if related_message:
                lines.append(f"{correction_prefix}: {related_message}")
        lines.append(f"{viewer}: {viewer_message}")
        if bot_reply:
            lines.append(f"bot: {bot_reply}")
    return "\n".join(lines) if lines else "aucun"


def turn_to_context_lines(turn: dict) -> list[str]:
    viewer = normalize_spaces(turn.get("viewer", "viewer"))
    viewer_message = sanitize_user_text(turn.get("viewer_message", ""))
    bot_reply = sanitize_user_text(turn.get("bot_reply", ""))
    event_type = normalize_spaces(turn.get("event_type", ""))
    related_viewer = normalize_spaces(turn.get("related_viewer", ""))
    related_message = sanitize_user_text(turn.get("related_message", ""))
    lines: list[str] = []
    if event_type in {"correction", "owner_correction"}:
        label = "correction"
        if related_viewer:
            label += f" pour {related_viewer}"
        if related_message:
            lines.append(f"{label}: {related_message}")
    if viewer_message:
        lines.append(f"{viewer}: {viewer_message}")
    if bot_reply:
        lines.append(f"bot: {bot_reply}")
    return lines


def format_context_lines(turns: list[dict], max_lines: int) -> str:
    lines: list[str] = []
    for turn in turns:
        lines.extend(turn_to_context_lines(turn))
    if not lines:
        return "aucun"
    return "\n".join(lines[-max(1, max_lines):])


def extract_active_viewer_thread(turns: list[dict]) -> list[dict]:
    last_bot_reply_index = -1
    for index, turn in enumerate(turns):
        if turn.get("bot_reply", ""):
            last_bot_reply_index = index

    active_turns = turns[last_bot_reply_index + 1:]
    if not active_turns:
        return active_turns

    if active_turns[-1].get("thread_boundary", "") == "end":
        return []

    trimmed_reversed = []
    for turn in reversed(active_turns):
        boundary = turn.get("thread_boundary", "")
        if boundary == "end":
            break

        trimmed_reversed.append(turn)
        if boundary == "start":
            break

    return list(reversed(trimmed_reversed))


def build_chat_context(
    chat_memory: dict,
    channel_name: str,
    viewer_name: str,
    prefer_active_thread: bool = False,
) -> dict:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_viewer = normalize_spaces((viewer_name or "").lower())
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    global_turns = channel_data.get("global_turns", [])[-MAX_GLOBAL_CHAT_TURNS:]
    viewer_turns = channel_data.get("viewer_turns", {}).get(normalized_viewer, [])[-MAX_VIEWER_CHAT_TURNS:]

    if prefer_active_thread:
        active_viewer_turns = extract_active_viewer_thread(viewer_turns)
        viewer_turns = active_viewer_turns
        global_turns = [
            turn for turn in global_turns
            if turn.get("viewer", "") == normalized_viewer and turn in active_viewer_turns
        ]

    global_context_turns = []
    for turn in global_turns:
        if turn.get("viewer", "") != normalized_viewer:
            global_context_turns.append(turn)

    return {
        "viewer_context": format_chat_turns(viewer_turns),
        "global_context": format_context_lines(global_context_turns, max_lines=MAX_GLOBAL_CONTEXT_LINES),
    }


def viewer_recent_social_redundancy(
    chat_memory: dict,
    channel_name: str,
    viewer_name: str,
    text: str,
    window_minutes: int = SOCIAL_REDUNDANCY_WINDOW_MINUTES,
) -> int:
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_viewer = normalize_spaces((viewer_name or "").lower())
    channel_data = chat_memory.get("channels", {}).get(normalized_channel, {})
    viewer_turns = list(channel_data.get("viewer_turns", {}).get(normalized_viewer, []))[-MAX_VIEWER_CHAT_TURNS:]
    cutoff = utc_now() - timedelta(minutes=window_minutes)

    match_count = 0
    for turn in viewer_turns:
        timestamp = parse_utc_iso(turn.get("timestamp", ""))
        if not timestamp or timestamp < cutoff:
            continue
        viewer_message = turn.get("viewer_message", "")
        if looks_like_greeting(text) and looks_like_greeting(viewer_message):
            match_count += 1
        if looks_like_passive_closing(text) and looks_like_passive_closing(viewer_message):
            match_count += 1
    return match_count


def clear_chat_memory(chat_memory_file: str = CHAT_MEMORY_FILE) -> None:
    with open(chat_memory_file, "w", encoding="utf-8") as file_obj:
        json.dump(
            {"channels": {}, "meta": {"memory_helpful_replies": 0, "riddle_messages_seen": 0}},
            file_obj,
            ensure_ascii=False,
            indent=2,
        )


def increment_chat_memory_counter(
    chat_memory: dict,
    counter_name: str,
    chat_memory_file: str = CHAT_MEMORY_FILE,
) -> None:
    meta = chat_memory.setdefault("meta", {})
    meta[counter_name] = int(meta.get(counter_name, 0) or 0) + 1
    save_chat_memory(chat_memory, chat_memory_file=chat_memory_file)


def clear_chat_memory_viewer(
    channel_name: str,
    viewer_name: str,
    chat_memory_file: str = CHAT_MEMORY_FILE,
    ttl_hours: int = CHAT_MEMORY_TTL_HOURS,
) -> bool:
    chat_memory = prune_chat_memory(load_chat_memory(chat_memory_file), ttl_hours=ttl_hours)
    normalized_channel = normalize_spaces((channel_name or "").lower())
    normalized_viewer = normalize_spaces((viewer_name or "").lower())

    channel_data = chat_memory.get("channels", {}).get(normalized_channel)
    if not channel_data or normalized_viewer not in channel_data.get("viewer_turns", {}):
        return False

    channel_data["viewer_turns"].pop(normalized_viewer, None)
    channel_data["global_turns"] = [
        turn for turn in channel_data.get("global_turns", [])
        if turn.get("viewer", "") != normalized_viewer
    ]

    if not channel_data["global_turns"] and not channel_data["viewer_turns"]:
        chat_memory.get("channels", {}).pop(normalized_channel, None)

    save_chat_memory(chat_memory, chat_memory_file=chat_memory_file)
    return True


def get_chat_memory_stats(
    chat_memory_file: str = CHAT_MEMORY_FILE,
    ttl_hours: int = CHAT_MEMORY_TTL_HOURS,
) -> dict:
    chat_memory = prune_chat_memory(load_chat_memory(chat_memory_file), ttl_hours=ttl_hours)
    channels = chat_memory.get("channels", {})
    channel_stats = []

    for channel_name in sorted(channels):
        channel_data = channels[channel_name]
        viewer_turns = channel_data.get("viewer_turns", {})
        per_viewer_counts = {
            viewer_name: len(turns)
            for viewer_name, turns in viewer_turns.items()
            if turns
        }
        channel_stats.append(
            {
                "channel": channel_name,
                "global_turns": len(channel_data.get("global_turns", [])),
                "viewer_count": len(per_viewer_counts),
                "per_viewer_counts": dict(sorted(per_viewer_counts.items())),
            }
        )

    return {
        "ttl_hours": ttl_hours,
        "channel_count": len(channel_stats),
        "total_turns": sum(channel["global_turns"] for channel in channel_stats),
        "memory_helpful_replies": int(chat_memory.get("meta", {}).get("memory_helpful_replies", 0) or 0),
        "riddle_messages_seen": int(chat_memory.get("meta", {}).get("riddle_messages_seen", 0) or 0),
        "channels": channel_stats,
    }


def save_history(history: dict, history_file: str = HISTORY_FILE) -> None:
    sessions = history.get("sessions", [])
    history["sessions"] = sessions[-MAX_HISTORY_SESSIONS:]

    with open(history_file, "w", encoding="utf-8") as file_obj:
        json.dump(history, file_obj, ensure_ascii=False, indent=2)


def ensure_current_session(history: dict) -> dict:
    if history.get("current_session") is None:
        history["current_session"] = {
            "started_at": utc_now_iso(),
            "ended_at": None,
            "updates": [],
        }
    return history["current_session"]


def append_channel_update(history: dict, title: str | None, category_name: str | None, history_file: str = HISTORY_FILE) -> None:
    session = ensure_current_session(history)
    updates = session.setdefault("updates", [])

    updates.append(
        {
            "timestamp": utc_now_iso(),
            "title": (title or "").strip(),
            "category_name": (category_name or "").strip(),
        }
    )

    if len(updates) >= 2:
        previous = updates[-2]
        current = updates[-1]
        if previous.get("title") == current.get("title") and previous.get("category_name") == current.get("category_name"):
            updates.pop()

    save_history(history, history_file=history_file)


def start_stream_session(history: dict, history_file: str = HISTORY_FILE) -> None:
    if history.get("current_session") is None:
        history["current_session"] = {
            "started_at": utc_now_iso(),
            "ended_at": None,
            "updates": [],
        }
        save_history(history, history_file=history_file)


def end_stream_session(history: dict, history_file: str = HISTORY_FILE) -> None:
    session = history.get("current_session")
    if session is None:
        return

    session["ended_at"] = utc_now_iso()
    history.setdefault("sessions", []).append(session)
    history["current_session"] = None
    save_history(history, history_file=history_file)


def extract_channel_profile(history: dict) -> dict:
    sessions = history.get("sessions", [])[-20:]
    current_session = history.get("current_session")

    if current_session:
        sessions = sessions + [current_session]

    categories = []
    titles = []

    for session in sessions:
        for update in session.get("updates", []):
            category = (update.get("category_name") or "").strip()
            title = (update.get("title") or "").strip()

            if category:
                categories.append(category)
            if title:
                titles.append(title)

    top_categories = Counter(categories).most_common(5)

    seen = set()
    unique_titles = []
    for title in reversed(titles):
        lowered = title.lower()
        if lowered not in seen:
            seen.add(lowered)
            unique_titles.append(title)
    unique_titles = list(reversed(unique_titles))[-8:]

    return {
        "top_categories": top_categories,
        "recent_titles": unique_titles,
        "has_live_history": bool(sessions),
    }


def build_messages(
    user_name: str,
    clean_message: str,
    viewer_context: str = "",
    global_context: str = "",
    web_context: str = "",
    conversation_mode: str = "",
) -> list[dict]:
    from context_sources import build_context_source_results
    from prompt_composer import build_messages_from_prompt_plan, build_prompt_plan

    sources = build_context_source_results(
        viewer_context=viewer_context,
        conversation_context=global_context,
        web_context=web_context,
    )
    plan = build_prompt_plan(sources, conversation_mode=conversation_mode)
    return build_messages_from_prompt_plan(plan, user_name=user_name, clean_message=clean_message)
