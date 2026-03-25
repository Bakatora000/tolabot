from __future__ import annotations

import json
import re
from pathlib import Path

from bot_logic import (
    CHAT_MEMORY_TTL_HOURS,
    detect_referenced_viewers,
    normalize_name_token,
    normalize_spaces,
    parse_utc_iso,
    sanitize_user_text,
    utc_now,
    utc_now_iso,
)


FACTS_MEMORY_FILE = "facts_memory.json"
MAX_FACTS_PER_CHANNEL = 120


def load_facts_memory(facts_file: str = FACTS_MEMORY_FILE) -> dict:
    path = Path(facts_file)
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


def save_facts_memory(facts_memory: dict, facts_file: str = FACTS_MEMORY_FILE) -> None:
    Path(facts_file).write_text(json.dumps(facts_memory, ensure_ascii=False, indent=2), encoding="utf-8")


def prune_facts_memory(facts_memory: dict, ttl_hours: int = CHAT_MEMORY_TTL_HOURS) -> dict:
    cutoff = utc_now()
    cutoff_ts = cutoff.timestamp() - (ttl_hours * 3600)
    pruned_channels: dict[str, dict] = {}

    for channel_name, channel_data in facts_memory.get("channels", {}).items():
        facts = []
        for fact in channel_data.get("facts", []):
            parsed = parse_utc_iso(fact.get("timestamp", ""))
            if parsed and parsed.timestamp() >= cutoff_ts:
                facts.append(fact)
        if facts:
            pruned_channels[channel_name] = {"facts": facts[-MAX_FACTS_PER_CHANNEL:]}

    facts_memory["channels"] = pruned_channels
    return facts_memory


def _append_fact(
    facts: list[dict],
    *,
    subject: str,
    predicate: str,
    value: str,
    source_speaker: str,
    verification_state: str,
) -> None:
    normalized_subject = normalize_name_token(subject)
    normalized_value = sanitize_user_text(value)
    normalized_source = normalize_spaces(source_speaker).lower()
    if not normalized_subject or not normalized_value or not normalized_source:
        return
    facts.append(
        {
            "timestamp": utc_now_iso(),
            "subject": normalized_subject,
            "predicate": normalize_spaces(predicate).lower(),
            "value": normalized_value,
            "source_speaker": normalized_source,
            "verification_state": normalize_spaces(verification_state).lower(),
        }
    )


def extract_reported_facts(message_text: str, source_speaker: str) -> list[dict]:
    cleaned = sanitize_user_text(message_text)
    if not cleaned:
        return []
    if "?" in cleaned:
        return []

    facts: list[dict] = []
    source_clean = normalize_spaces(source_speaker).lower()

    group_match = re.search(
        r"([@a-zA-Z0-9_]+)\s+et\s+([@a-zA-Z0-9_]+)\s+o[uù]\s+nous\s+formons\s+un\s+trio\s+surnomm[ée]?\s+[\"“]?([^\"”]+)[\"”]?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if group_match:
        member_1 = normalize_name_token(source_speaker)
        member_2 = normalize_name_token(group_match.group(1))
        member_3 = normalize_name_token(group_match.group(2))
        group_name = sanitize_user_text(group_match.group(3))
        members = [item for item in [member_1, member_2, member_3] if item]
        if len(members) >= 3 and group_name:
            members_value = ", ".join(members)
            _append_fact(
                facts,
                subject=group_name,
                predicate="group_members",
                value=members_value,
                source_speaker=source_speaker,
                verification_state="self_confirmed",
            )
            for member in members:
                verification = "self_confirmed" if member.lower() == source_clean else "third_party_reported"
                _append_fact(
                    facts,
                    subject=member,
                    predicate="group_name",
                    value=group_name,
                    source_speaker=source_speaker,
                    verification_state=verification,
                )

    alias_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+aussi\s+\b([@a-zA-Z0-9_]+)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if alias_match:
        subject = normalize_name_token(alias_match.group(1))
        alias = normalize_name_token(alias_match.group(2))
        verification = "self_confirmed" if subject.lower() == source_clean else "third_party_reported"
        _append_fact(
            facts,
            subject=subject,
            predicate="alias",
            value=f"aussi appelée {alias}",
            source_speaker=source_speaker,
            verification_state=verification,
        )

    reported_alias_match = re.search(
        r"quand\s+on\s+te\s+parle\s+de\s+[\"“]?([^\"”]+)[\"”]?\s+il\s+s['’]agit\s+de\s+([@a-zA-Z0-9_ ]+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if reported_alias_match:
        alias = normalize_name_token(reported_alias_match.group(1))
        subject = normalize_name_token(reported_alias_match.group(2))
        verification = "self_confirmed" if subject.lower() == source_clean else "third_party_reported"
        _append_fact(
            facts,
            subject=subject,
            predicate="alias",
            value=f"aussi appelée {alias}",
            source_speaker=source_speaker,
            verification_state=verification,
        )

    same_person_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+la\s+m[êe]me\s+personne\s+(?:que|de)\s+\b([@a-zA-Z0-9_]+)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if same_person_match:
        subject = normalize_name_token(same_person_match.group(1))
        alias = normalize_name_token(same_person_match.group(2))
        verification = "self_confirmed" if subject.lower() == source_clean else "third_party_reported"
        _append_fact(
            facts,
            subject=subject,
            predicate="identity",
            value=f"est la même personne que {alias}",
            source_speaker=source_speaker,
            verification_state=verification,
        )

    generic_match = re.search(
        r"\b([@a-zA-Z0-9_]+)\b\s+est\s+(.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if generic_match:
        subject = normalize_name_token(generic_match.group(1))
        value = sanitize_user_text(generic_match.group(2))
        lowered_subject = subject.lower()
        blocked_subjects = {
            "quel", "quelle", "quels", "quelles", "qui", "quoi", "quand", "comment", "pourquoi", "ou",
        }
        if subject and value and len(value) >= 4 and lowered_subject not in blocked_subjects:
            verification = "self_confirmed" if subject.lower() == source_clean else "third_party_reported"
            _append_fact(
                facts,
                subject=subject,
                predicate="description",
                value=value,
                source_speaker=source_speaker,
                verification_state=verification,
            )

    deduped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for fact in facts:
        key = (
            fact["subject"].lower(),
            fact["predicate"],
            fact["value"].lower(),
            fact["verification_state"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped


def append_reported_facts(
    facts_memory: dict,
    channel_name: str,
    source_speaker: str,
    message_text: str,
    facts_file: str = FACTS_MEMORY_FILE,
    ttl_hours: int = CHAT_MEMORY_TTL_HOURS,
) -> list[dict]:
    extracted = extract_reported_facts(message_text, source_speaker)
    if not extracted:
        return []

    normalized_channel = normalize_spaces(channel_name).lower()
    channel_data = facts_memory.setdefault("channels", {}).setdefault(normalized_channel, {"facts": []})
    channel_data.setdefault("facts", []).extend(extracted)
    channel_data["facts"] = channel_data["facts"][-MAX_FACTS_PER_CHANNEL:]
    save_facts_memory(prune_facts_memory(facts_memory, ttl_hours=ttl_hours), facts_file=facts_file)
    return extracted


def build_facts_context(
    facts_memory: dict,
    channel_name: str,
    current_author: str,
    current_message: str,
) -> str:
    normalized_channel = normalize_spaces(channel_name).lower()
    normalized_author = normalize_spaces(current_author).lower()
    channel_data = facts_memory.get("channels", {}).get(normalized_channel, {})
    facts = list(channel_data.get("facts", []))
    if not facts:
        return "aucun"

    relevant_lines: list[str] = []
    lowered_message = sanitize_user_text(current_message).lower()
    group_question = any(fragment in lowered_message for fragment in ("groupe", "trio", "nom"))
    explicit_targets = {item.lower() for item in detect_referenced_viewers(current_message)}
    targets = set(explicit_targets)
    if normalized_author and not group_question:
        targets.add(normalized_author)
    for fact in reversed(facts):
        subject = normalize_name_token(fact.get("subject", ""))
        if not subject:
            continue

        verification = normalize_spaces(fact.get("verification_state", "")).lower()
        source_speaker = normalize_spaces(fact.get("source_speaker", "")).lower()
        predicate = normalize_spaces(fact.get("predicate", "")).lower()
        value = sanitize_user_text(fact.get("value", ""))
        if not value:
            continue

        if predicate == "group_members" and group_question:
            normalized_members = {normalize_spaces(item).lower() for item in value.split(",")}
            overlap_count = sum(
                1
                for member in normalized_members
                if member in lowered_message or any(token and token in lowered_message for token in member.split("_"))
            )
            target_overlap_count = sum(
                1
                for target in explicit_targets
                if target in normalized_members or any(target in member or member in target for member in normalized_members)
            )
            if overlap_count >= 2 or (explicit_targets and target_overlap_count >= max(2, min(len(explicit_targets), 3))):
                relevant_lines.append(f"fait confirme sur {subject}: groupe compose de {value}")
            continue

        if predicate == "group_name" and group_question and targets and subject.lower() in targets:
            if verification == "self_confirmed":
                relevant_lines.append(f"fait confirme sur {subject}: fait partie du groupe {value}")
            elif source_speaker == normalized_author:
                relevant_lines.append(f"fait rapporte par toi sur {subject} (incertain): fait partie du groupe {value}")
            elif subject.lower() == normalized_author:
                relevant_lines.append(
                    f"fait incertain rapporte par {source_speaker} sur toi: fait partie du groupe {value}. "
                    f"Si c'est utile, demande confirmation au lieu de l'affirmer."
                )
            else:
                relevant_lines.append(f"fait rapporte par {source_speaker} sur {subject} (incertain): fait partie du groupe {value}")
            continue

        if targets and subject.lower() not in targets:
            continue

        if verification == "self_confirmed":
            relevant_lines.append(f"fait confirme sur {subject}: {value}")
            continue

        if source_speaker == normalized_author:
            relevant_lines.append(f"fait rapporte par toi sur {subject} (incertain): {value}")
            continue

        if subject.lower() == normalized_author:
            relevant_lines.append(
                f"fait incertain rapporte par {source_speaker} sur toi: {value}. "
                f"Si c'est utile, demande confirmation au lieu de l'affirmer."
            )
            continue

        relevant_lines.append(f"fait rapporte par {source_speaker} sur {subject} (incertain): {value}")

    if not relevant_lines:
        return "aucun"
    return "\n".join(relevant_lines[:8])
