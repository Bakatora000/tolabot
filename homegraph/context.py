from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MAX_SUMMARY_LEN = 160
MAX_FACTS = 4
MAX_RECENT = 2
MAX_UNCERTAIN = 2
MAX_SOCIAL_LINK_NAMES = 2
TEXT_BLOCK_HARD_LIMIT = 900
TEXT_BLOCK_MIN_LEN = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def trim(value: str | None, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip() + "…"


def fetch_profile(conn: sqlite3.Connection, viewer_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT viewer_id, summary_short, last_updated_at
        FROM viewer_profiles
        WHERE viewer_id = ?
        """,
        (viewer_id,),
    ).fetchone()


def fetch_facts(conn: sqlite3.Connection, viewer_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT kind, value, confidence, status, updated_at
        FROM viewer_facts
        WHERE viewer_id = ?
        ORDER BY
            CASE kind
                WHEN 'plays_game' THEN 1
                WHEN 'likes_game' THEN 2
                WHEN 'build_style' THEN 3
                WHEN 'personality_trait' THEN 4
                WHEN 'recurring_topic' THEN 5
                ELSE 99
            END,
            COALESCE(confidence, 0) DESC,
            COALESCE(updated_at, '') DESC
        """,
        (viewer_id,),
    ).fetchall()
    return list(rows)


def fetch_relations(conn: sqlite3.Connection, viewer_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT target_type, target_id_or_value, relation_type, confidence, updated_at
        FROM viewer_relations
        WHERE viewer_id = ?
        ORDER BY
            COALESCE(confidence, 0) DESC,
            COALESCE(updated_at, '') DESC
        """,
        (viewer_id,),
    ).fetchall()
    return list(rows)


def fetch_links(conn: sqlite3.Connection, viewer_id: str) -> list[sqlite3.Row]:
    try:
        rows = conn.execute(
            """
            SELECT
                l.target_fallback_value,
                l.relation_type,
                l.strength,
                l.confidence,
                l.status,
                l.polarity,
                l.updated_at,
                e.entity_type,
                e.canonical_name
            FROM viewer_links l
            LEFT JOIN graph_entities e ON e.entity_id = l.target_entity_id
            WHERE l.viewer_id = ?
            ORDER BY
                COALESCE(l.strength, 0) DESC,
                COALESCE(l.confidence, 0) DESC,
                COALESCE(l.updated_at, '') DESC
            """,
            (viewer_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    return list(rows)


def normalize_phrase(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    return value[0].lower() + value[1:] if len(value) > 1 else value.lower()


def fact_to_phrase(kind: str, value: str) -> str:
    normalized = normalize_phrase(value)
    if not normalized:
        return ""
    if kind == "recurring_topic":
        if normalized.startswith("revient ") or normalized.startswith("parle "):
            return normalized
        return f"parle souvent de {value}"
    mappings = {
        "plays_game": f"joue souvent a {value}",
        "likes_game": f"apprecie {value}",
        "dislikes_game": f"n'apprecie pas {value}",
        "plays_role": f"joue plutot en tant que {normalized}",
        "build_style": normalized,
        "personality_trait": normalized,
        "social_relation": normalized,
        "stream_context": normalized,
    }
    return mappings.get(kind, normalized)


def relation_to_phrase(target_type: str, relation_type: str, target_value: str) -> str:
    value = target_value.strip()
    if not value:
        return ""
    if target_type == "game" and relation_type == "plays":
        return f"joue souvent a {value}"
    if target_type == "game" and relation_type == "likes":
        return f"apprecie {value}"
    if target_type == "game" and relation_type == "dislikes":
        return f"n'apprecie pas {value}"
    if target_type == "topic" and relation_type == "likes":
        return f"s'interesse a {normalize_phrase(value)}"
    if target_type == "viewer" and relation_type == "knows":
        return f"semble connaitre {value}"
    return normalize_phrase(value)


def link_to_phrase(entity_type: str, relation_type: str, canonical_name: str, target_value: str) -> str:
    value = canonical_name.strip() or target_value.strip()
    if not value:
        return ""
    if entity_type == "game" and relation_type == "plays":
        return f"joue souvent a {value}"
    if entity_type == "game" and relation_type == "likes":
        return f"apprecie {value}"
    if entity_type == "game" and relation_type == "dislikes":
        return f"n'apprecie pas {value}"
    if entity_type == "topic" and relation_type in {"returns_to", "talks_about"}:
        return f"revient souvent sur {value}" if relation_type == "returns_to" else f"parle souvent de {value}"
    if entity_type == "topic" and relation_type == "likes":
        return f"s'interesse a {normalize_phrase(value)}"
    if entity_type == "running_gag" and relation_type in {"jokes_about", "returns_to"}:
        return f"revient souvent sur {value}"
    if entity_type == "viewer" and relation_type == "knows":
        return f"semble connaitre {value}"
    if entity_type == "viewer" and relation_type == "compliments":
        return f"complimente parfois {value}"
    if entity_type == "stream_mode" and relation_type in {"likes", "plays_in_mode"}:
        return f"s'interesse aux runs {normalize_phrase(value)}"
    if entity_type == "object" and relation_type == "owns":
        return f"a {normalize_phrase(value)}"
    return relation_to_phrase(entity_type, relation_type, value)


def summarize_social_links(links: list[sqlite3.Row]) -> str:
    names: list[str] = []
    for row in links:
        entity_type = str(row["entity_type"] or "").strip()
        relation_type = str(row["relation_type"] or "").strip()
        status = str(row["status"] or "").strip()
        confidence = float(row["confidence"] or 0.0)
        if entity_type != "viewer" or relation_type != "knows":
            continue
        if status not in {"active", "uncertain"} or confidence < 0.55:
            continue
        name = str(row["canonical_name"] or row["target_fallback_value"] or "").strip()
        if name and name not in names:
            names.append(name)

    if not names:
        return ""

    display_names = names[:MAX_SOCIAL_LINK_NAMES]
    if len(display_names) == 1:
        return f"semble connaitre {display_names[0]}"
    if len(names) > MAX_SOCIAL_LINK_NAMES:
        return f"semble connaitre {display_names[0]} et {display_names[1]}, entre autres"
    return f"semble connaitre {display_names[0]} et {display_names[1]}"


def build_text_block(
    summary_short: str,
    facts_high_confidence: list[str],
    recent_relevant: list[str],
    uncertain_points: list[str],
) -> str:
    content_lines: list[str] = []
    if summary_short and summary_short != "aucun":
        content_lines.append(f"- {summary_short}")
    for item in facts_high_confidence:
        content_lines.append(f"- {item}")
    for item in recent_relevant:
        content_lines.append(f"- {item}")
    for item in uncertain_points:
        content_lines.append(f"- incertain : {item}")

    if not content_lines:
        return ""

    text = "\n".join(["Contexte viewer:", *content_lines])
    if len(text) <= TEXT_BLOCK_HARD_LIMIT:
        return text

    recent_copy = recent_relevant.copy()
    uncertain_copy = uncertain_points.copy()
    facts_copy = facts_high_confidence.copy()

    while recent_copy and len(text) > TEXT_BLOCK_HARD_LIMIT:
        recent_copy.pop()
        text = build_text_block(summary_short, facts_copy, recent_copy, uncertain_copy)
    while uncertain_copy and len(text) > TEXT_BLOCK_HARD_LIMIT:
        uncertain_copy.pop()
        text = build_text_block(summary_short, facts_copy, recent_copy, uncertain_copy)
    while len(facts_copy) > 2 and len(text) > TEXT_BLOCK_HARD_LIMIT:
        facts_copy.pop()
        text = build_text_block(summary_short, facts_copy, recent_copy, uncertain_copy)
    return text[:TEXT_BLOCK_HARD_LIMIT]


def build_viewer_context_payload(viewer_id: str, db_path: Path | str) -> dict[str, Any]:
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        profile = fetch_profile(conn, viewer_id)
        facts = fetch_facts(conn, viewer_id)
        relations = fetch_relations(conn, viewer_id)
        links = fetch_links(conn, viewer_id)
    finally:
        conn.close()

    profile_last_updated_at = profile["last_updated_at"] if profile else None
    profile_dt = parse_ts(profile_last_updated_at)
    is_stale = profile_dt is None or profile_dt < (utc_now() - timedelta(days=7))

    summary_short = trim(profile["summary_short"] if profile else "", MAX_SUMMARY_LEN) or "aucun"

    facts_high_confidence: list[str] = []
    recent_relevant: list[str] = []
    uncertain_points: list[str] = []
    concrete_items = 0

    for row in facts:
        phrase = fact_to_phrase(str(row["kind"] or "").strip(), str(row["value"] or "").strip())
        if not phrase:
            continue
        confidence = float(row["confidence"] or 0.0)
        status = str(row["status"] or "").strip()

        if status == "active" and confidence >= 0.75 and len(facts_high_confidence) < MAX_FACTS:
            if phrase not in facts_high_confidence:
                facts_high_confidence.append(phrase)
                concrete_items += 1
            continue

        if (status == "uncertain" or confidence < 0.75) and len(uncertain_points) < MAX_UNCERTAIN:
            if phrase not in uncertain_points:
                uncertain_points.append(phrase)
            continue

        if status == "active" and len(recent_relevant) < MAX_RECENT:
            if phrase not in facts_high_confidence and phrase not in recent_relevant:
                recent_relevant.append(phrase)
                concrete_items += 1

    for row in relations:
        phrase = relation_to_phrase(
            str(row["target_type"] or "").strip(),
            str(row["relation_type"] or "").strip(),
            str(row["target_id_or_value"] or "").strip(),
        )
        if not phrase:
            continue
        confidence = float(row["confidence"] or 0.0)
        if confidence < 0.75:
            continue
        if phrase in facts_high_confidence or phrase in recent_relevant:
            continue
        if len(facts_high_confidence) < MAX_FACTS:
            facts_high_confidence.append(phrase)
            concrete_items += 1
        elif len(recent_relevant) < MAX_RECENT:
            recent_relevant.append(phrase)
            concrete_items += 1

    for row in links:
        phrase = link_to_phrase(
            str(row["entity_type"] or "").strip(),
            str(row["relation_type"] or "").strip(),
            str(row["canonical_name"] or "").strip(),
            str(row["target_fallback_value"] or "").strip(),
        )
        if not phrase:
            continue
        confidence = float(row["confidence"] or 0.0)
        strength = float(row["strength"] or 0.0)
        status = str(row["status"] or "").strip()
        if phrase in facts_high_confidence or phrase in recent_relevant or phrase in uncertain_points:
            continue
        if status == "active" and confidence >= 0.75 and strength >= 0.7:
            if len(facts_high_confidence) < MAX_FACTS:
                facts_high_confidence.append(phrase)
                concrete_items += 1
            elif len(recent_relevant) < MAX_RECENT:
                recent_relevant.append(phrase)
                concrete_items += 1
            continue
        if (status == "uncertain" or confidence < 0.75 or strength < 0.7) and len(uncertain_points) < MAX_UNCERTAIN:
            uncertain_points.append(phrase)

    social_summary = summarize_social_links(links)
    if social_summary and social_summary not in facts_high_confidence and social_summary not in recent_relevant:
        if len(recent_relevant) < MAX_RECENT:
            recent_relevant.append(social_summary)
            concrete_items += 1
        elif social_summary not in uncertain_points:
            if len(uncertain_points) >= MAX_UNCERTAIN:
                uncertain_points.pop()
            uncertain_points.append(social_summary)

    text_block = build_text_block(
        summary_short=summary_short,
        facts_high_confidence=facts_high_confidence,
        recent_relevant=recent_relevant,
        uncertain_points=uncertain_points,
    )
    if concrete_items < 1 or len(text_block.strip()) < TEXT_BLOCK_MIN_LEN:
        text_block = ""

    return {
        "ok": True,
        "viewer_id": viewer_id,
        "generated_at": utc_now().isoformat(),
        "source": "homegraph_v1",
        "staleness": {
            "profile_last_updated_at": profile_last_updated_at,
            "is_stale": is_stale,
        },
        "context": {
            "summary_short": summary_short,
            "facts_high_confidence": facts_high_confidence,
            "recent_relevant": recent_relevant,
            "uncertain_points": uncertain_points,
        },
        "text_block": text_block,
    }


def payload_as_json(viewer_id: str, db_path: Path | str) -> str:
    return json.dumps(build_viewer_context_payload(viewer_id, db_path), ensure_ascii=False, indent=2)
