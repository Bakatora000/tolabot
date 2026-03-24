from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from homegraph.schema import DEFAULT_DB_PATH
except ModuleNotFoundError:
    from schema import DEFAULT_DB_PATH


MAX_SUMMARY_LEN = 160
MAX_FACTS = 4
MAX_RECENT = 2
MAX_UNCERTAIN = 2
TEXT_BLOCK_HARD_LIMIT = 900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a compact viewer context from homegraph SQLite.")
    parser.add_argument("--viewer-id", required=True, help="Viewer user_id.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    return parser.parse_args()


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


def build_text_block(
    summary_short: str,
    facts_high_confidence: list[str],
    recent_relevant: list[str],
    uncertain_points: list[str],
) -> str:
    lines = ["Contexte viewer:"]
    if summary_short and summary_short != "aucun":
        lines.append(f"- {summary_short}")
    for item in facts_high_confidence:
        lines.append(f"- {item}")
    for item in recent_relevant:
        lines.append(f"- {item}")
    for item in uncertain_points:
        lines.append(f"- incertain : {item}")

    text = "\n".join(lines)
    if len(text) <= TEXT_BLOCK_HARD_LIMIT:
        return text

    while recent_relevant and len(text) > TEXT_BLOCK_HARD_LIMIT:
        recent_relevant.pop()
        text = build_text_block(summary_short, facts_high_confidence, recent_relevant, uncertain_points)
    while uncertain_points and len(text) > TEXT_BLOCK_HARD_LIMIT:
        uncertain_points.pop()
        text = build_text_block(summary_short, facts_high_confidence, recent_relevant, uncertain_points)
    while len(facts_high_confidence) > 2 and len(text) > TEXT_BLOCK_HARD_LIMIT:
        facts_high_confidence.pop()
        text = build_text_block(summary_short, facts_high_confidence, recent_relevant, uncertain_points)
    return text[:TEXT_BLOCK_HARD_LIMIT]


def main() -> None:
    args = parse_args()
    conn = sqlite3.connect(Path(args.db))
    conn.row_factory = sqlite3.Row
    try:
        profile = fetch_profile(conn, args.viewer_id)
        facts = fetch_facts(conn, args.viewer_id)
    finally:
        conn.close()

    profile_last_updated_at = profile["last_updated_at"] if profile else None
    profile_dt = parse_ts(profile_last_updated_at)
    is_stale = profile_dt is None or profile_dt < (utc_now() - timedelta(days=7))

    summary_short = trim(profile["summary_short"] if profile else "", MAX_SUMMARY_LEN) or "aucun"

    facts_high_confidence: list[str] = []
    recent_relevant: list[str] = []
    uncertain_points: list[str] = []

    for row in facts:
        value = str(row["value"] or "").strip()
        if not value:
            continue
        confidence = float(row["confidence"] or 0.0)
        status = str(row["status"] or "").strip()

        if status == "active" and confidence >= 0.75 and len(facts_high_confidence) < MAX_FACTS:
            if value not in facts_high_confidence:
                facts_high_confidence.append(value)
            continue

        if (status == "uncertain" or confidence < 0.75) and len(uncertain_points) < MAX_UNCERTAIN:
            if value not in uncertain_points:
                uncertain_points.append(value)
            continue

        if status == "active" and len(recent_relevant) < MAX_RECENT:
            if value not in facts_high_confidence and value not in recent_relevant:
                recent_relevant.append(value)

    text_block = build_text_block(
        summary_short=summary_short,
        facts_high_confidence=facts_high_confidence.copy(),
        recent_relevant=recent_relevant.copy(),
        uncertain_points=uncertain_points.copy(),
    )

    payload = {
        "ok": True,
        "viewer_id": args.viewer_id,
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
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
