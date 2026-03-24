from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from homegraph.schema import DEFAULT_DB_PATH, init_db
except ModuleNotFoundError:
    from schema import DEFAULT_DB_PATH, init_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge a GPT extraction JSON into the homegraph SQLite database."
    )
    parser.add_argument("input_path", help="Path to the GPT extraction JSON file.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Optional model name to record in graph_jobs.",
    )
    parser.add_argument(
        "--source-ref",
        default=None,
        help="Optional source reference to record in graph_jobs.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_source_memory_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def stable_id(prefix: str, *parts: str) -> str:
    joined = "||".join(part.strip() for part in parts if part is not None)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def merge_source_memory_ids(existing_json: str | None, new_ids: list[str]) -> str:
    existing = normalize_source_memory_ids(json.loads(existing_json or "[]"))
    merged = list(existing)
    for item in new_ids:
        if item not in merged:
            merged.append(item)
    return compact_json(merged)


def upsert_viewer_profile(conn: sqlite3.Connection, payload: dict[str, Any], now: str) -> None:
    viewer_id = str(payload["viewer_id"]).strip()
    channel = str(payload.get("channel") or "").strip() or None
    viewer_login = str(payload.get("viewer_login") or "").strip() or None
    display_name = str(payload.get("display_name") or "").strip() or None
    summary_short = str(payload.get("summary_short") or "").strip() or None
    summary_long = str(payload.get("summary_long") or "").strip() or None

    conn.execute(
        """
        INSERT INTO viewer_profiles (
            viewer_id, channel, viewer_login, display_name,
            summary_short, summary_long, last_updated_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(viewer_id) DO UPDATE SET
            channel=excluded.channel,
            viewer_login=excluded.viewer_login,
            display_name=COALESCE(excluded.display_name, viewer_profiles.display_name),
            summary_short=COALESCE(excluded.summary_short, viewer_profiles.summary_short),
            summary_long=COALESCE(excluded.summary_long, viewer_profiles.summary_long),
            last_updated_at=excluded.last_updated_at,
            updated_at=excluded.updated_at
        """,
        (
            viewer_id,
            channel,
            viewer_login,
            display_name,
            summary_short,
            summary_long,
            now,
            now,
        ),
    )


def upsert_fact(
    conn: sqlite3.Connection,
    viewer_id: str,
    fact: dict[str, Any],
    now: str,
) -> str:
    kind = str(fact.get("kind") or "").strip()
    value = str(fact.get("value") or "").strip()
    if not kind or not value:
        raise ValueError("Each fact requires non-empty 'kind' and 'value'.")

    fact_id = str(fact.get("fact_id") or "").strip() or stable_id("fact", viewer_id, kind, value)
    confidence = fact.get("confidence")
    status = str(fact.get("status") or "active").strip() or "active"
    valid_from = str(fact.get("valid_from") or "").strip() or None
    valid_to = str(fact.get("valid_to") or "").strip() or None
    source_memory_ids = normalize_source_memory_ids(fact.get("source_memory_ids"))
    source_excerpt = str(fact.get("source_excerpt") or "").strip() or None
    last_reviewed_at = str(fact.get("last_reviewed_at") or "").strip() or None
    review_state = str(fact.get("review_state") or "auto").strip() or "auto"

    existing = conn.execute(
        "SELECT source_memory_ids_json FROM viewer_facts WHERE fact_id = ?",
        (fact_id,),
    ).fetchone()
    merged_source_ids = merge_source_memory_ids(existing[0] if existing else None, source_memory_ids)

    conn.execute(
        """
        INSERT INTO viewer_facts (
            fact_id, viewer_id, kind, value, confidence, status,
            valid_from, valid_to, source_memory_ids_json, source_excerpt,
            last_reviewed_at, review_state, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fact_id) DO UPDATE SET
            viewer_id=excluded.viewer_id,
            kind=excluded.kind,
            value=excluded.value,
            confidence=excluded.confidence,
            status=excluded.status,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            source_memory_ids_json=excluded.source_memory_ids_json,
            source_excerpt=COALESCE(excluded.source_excerpt, viewer_facts.source_excerpt),
            last_reviewed_at=COALESCE(excluded.last_reviewed_at, viewer_facts.last_reviewed_at),
            review_state=excluded.review_state,
            updated_at=excluded.updated_at
        """,
        (
            fact_id,
            viewer_id,
            kind,
            value,
            confidence,
            status,
            valid_from,
            valid_to,
            merged_source_ids,
            source_excerpt,
            last_reviewed_at,
            review_state,
            now,
        ),
    )
    return fact_id


def upsert_relation(
    conn: sqlite3.Connection,
    viewer_id: str,
    relation: dict[str, Any],
    now: str,
) -> str:
    target_type = str(relation.get("target_type") or "").strip()
    target_id_or_value = str(relation.get("target_id_or_value") or "").strip()
    relation_type = str(relation.get("relation_type") or "").strip()
    if not target_type or not target_id_or_value or not relation_type:
        raise ValueError(
            "Each relation requires non-empty 'target_type', 'target_id_or_value', and 'relation_type'."
        )

    relation_id = str(relation.get("relation_id") or "").strip() or stable_id(
        "rel", viewer_id, target_type, target_id_or_value, relation_type
    )
    confidence = relation.get("confidence")
    valid_from = str(relation.get("valid_from") or "").strip() or None
    valid_to = str(relation.get("valid_to") or "").strip() or None
    source_memory_ids = normalize_source_memory_ids(relation.get("source_memory_ids"))

    existing = conn.execute(
        "SELECT source_memory_ids_json FROM viewer_relations WHERE relation_id = ?",
        (relation_id,),
    ).fetchone()
    merged_source_ids = merge_source_memory_ids(existing[0] if existing else None, source_memory_ids)

    conn.execute(
        """
        INSERT INTO viewer_relations (
            relation_id, viewer_id, target_type, target_id_or_value,
            relation_type, confidence, valid_from, valid_to,
            source_memory_ids_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(relation_id) DO UPDATE SET
            viewer_id=excluded.viewer_id,
            target_type=excluded.target_type,
            target_id_or_value=excluded.target_id_or_value,
            relation_type=excluded.relation_type,
            confidence=excluded.confidence,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            source_memory_ids_json=excluded.source_memory_ids_json,
            updated_at=excluded.updated_at
        """,
        (
            relation_id,
            viewer_id,
            target_type,
            target_id_or_value,
            relation_type,
            confidence,
            valid_from,
            valid_to,
            merged_source_ids,
            now,
        ),
    )
    return relation_id


def create_job(
    conn: sqlite3.Connection,
    viewer_id: str,
    source_ref: str | None,
    model_name: str | None,
    now: str,
) -> str:
    job_id = f"job_{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO graph_jobs (
            job_id, viewer_id, source_type, source_ref, model_name,
            status, started_at
        )
        VALUES (?, ?, 'gpt_extraction', ?, ?, 'running', ?)
        """,
        (job_id, viewer_id, source_ref, model_name, now),
    )
    return job_id


def close_job(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    completed_at: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE graph_jobs
        SET status = ?, completed_at = ?, error_message = ?
        WHERE job_id = ?
        """,
        (status, completed_at, error_message, job_id),
    )


def add_job_item(
    conn: sqlite3.Connection,
    job_id: str,
    item_type: str,
    source_ref: str,
    payload: dict[str, Any],
    status: str = "merged",
) -> None:
    item_id = f"item_{uuid.uuid4().hex}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO graph_job_items (
            item_id, job_id, item_type, source_ref, payload_json,
            status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, job_id, item_type, source_ref, compact_json(payload), status, now, now),
    )


def validate_payload(payload: dict[str, Any]) -> str:
    viewer_id = str(payload.get("viewer_id") or "").strip()
    if not viewer_id:
        raise ValueError("Payload requires non-empty 'viewer_id'.")
    if payload.get("facts") is not None and not isinstance(payload.get("facts"), list):
        raise ValueError("'facts' must be a list when present.")
    if payload.get("relations") is not None and not isinstance(payload.get("relations"), list):
        raise ValueError("'relations' must be a list when present.")
    return viewer_id


def merge_payload(
    payload: dict[str, Any],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    source_ref: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    viewer_id = validate_payload(payload)
    db_path = init_db(Path(db_path))
    now = utc_now()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        job_id = create_job(
            conn,
            viewer_id=viewer_id,
            source_ref=source_ref,
            model_name=model_name,
            now=now,
        )
        try:
            upsert_viewer_profile(conn, payload, now)

            merged_facts = 0
            for fact in payload.get("facts", []):
                fact_id = upsert_fact(conn, viewer_id, fact, now)
                add_job_item(conn, job_id, "fact", fact_id, fact)
                merged_facts += 1

            merged_relations = 0
            for relation in payload.get("relations", []):
                relation_id = upsert_relation(conn, viewer_id, relation, now)
                add_job_item(conn, job_id, "relation", relation_id, relation)
                merged_relations += 1

            close_job(conn, job_id, status="completed", completed_at=utc_now())
            conn.commit()
        except Exception as exc:
            close_job(conn, job_id, status="failed", completed_at=utc_now(), error_message=str(exc))
            conn.commit()
            raise
    finally:
        conn.close()

    return {
        "viewer_id": viewer_id,
        "facts": len(payload.get("facts", [])),
        "relations": len(payload.get("relations", [])),
        "db_path": str(db_path),
    }


def merge_file(
    input_path: Path | str,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    source_ref: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    resolved_input = Path(input_path)
    payload = json.loads(resolved_input.read_text(encoding="utf-8"))
    return merge_payload(
        payload,
        db_path=db_path,
        source_ref=source_ref or str(resolved_input),
        model_name=model_name,
    )


def main() -> None:
    args = parse_args()
    result = merge_file(
        args.input_path,
        db_path=args.db,
        source_ref=args.source_ref or str(Path(args.input_path)),
        model_name=args.model_name,
    )
    print(
        f"homegraph_merge_ok viewer_id={result['viewer_id']} facts={result['facts']} "
        f"relations={result['relations']} db={result['db_path']}"
    )


if __name__ == "__main__":
    main()
