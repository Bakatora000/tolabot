from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KIND_COLORS = {
    "viewer": "#4F46E5",
    "game": "#2563EB",
    "topic": "#059669",
    "running_gag": "#D97706",
    "trait": "#7C3AED",
    "stream_mode": "#DC2626",
    "object": "#6B7280",
}

STABLE_NODE_KINDS = [
    "viewer",
    "game",
    "topic",
    "running_gag",
    "trait",
    "stream_mode",
    "object",
]

STABLE_LINK_KINDS = [
    "plays",
    "likes",
    "dislikes",
    "talks_about",
    "returns_to",
    "knows",
    "compliments",
    "jokes_about",
    "interacts_with",
    "uses_build_style",
    "plays_in_mode",
    "owns",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def compact_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "item"


def build_viewer_graph_payload(
    viewer_id: str,
    db_path: Path | str,
    *,
    include_uncertain: bool = True,
    min_weight: float | None = None,
    max_links: int | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        profile = conn.execute(
            """
            SELECT viewer_id, display_name, viewer_login, summary_short, last_updated_at
            FROM viewer_profiles
            WHERE viewer_id = ?
            """,
            (viewer_id,),
        ).fetchone()

        relation_rows = conn.execute(
            """
            SELECT target_type, target_id_or_value, relation_type, confidence, updated_at
            FROM viewer_relations
            WHERE viewer_id = ?
            ORDER BY COALESCE(confidence, 0) DESC, COALESCE(updated_at, '') DESC
            """,
            (viewer_id,),
        ).fetchall()

        try:
            link_rows = conn.execute(
                """
                SELECT
                    l.link_id,
                    l.target_fallback_value,
                    l.relation_type,
                    l.strength,
                    l.confidence,
                    l.status,
                    l.polarity,
                    l.source_memory_ids_json,
                    l.source_excerpt,
                    e.entity_id,
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
                link_rows = []
            else:
                raise
    finally:
        conn.close()

    viewer_label = (
        str(profile["display_name"] or "").strip()
        or str(profile["viewer_login"] or "").strip()
        or viewer_id.split(":")[-1]
    )
    viewer_detail = str(profile["summary_short"] or "").strip() if profile else ""
    profile_last_updated_at = str(profile["last_updated_at"] or "").strip() if profile else None

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    link_ids: set[str] = set()

    def add_node(node_id: str, label: str, kind: str, *, detail: str = "", color: str | None = None) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        payload = {
            "id": node_id,
            "label": label,
            "kind": kind,
        }
        if color:
            payload["color"] = color
        if detail:
            payload["detail"] = detail
        nodes.append(payload)

    def add_link(
        source: str,
        target: str,
        kind: str,
        *,
        label: str = "",
        color: str | None = None,
        weight: float | None = None,
        detail: str = "",
    ) -> None:
        link_id = f"{source}|{kind}|{target}"
        if link_id in link_ids:
            return
        link_ids.add(link_id)
        payload = {
            "source": source,
            "target": target,
            "kind": kind,
        }
        if label:
            payload["label"] = label
        if color:
            payload["color"] = color
        if weight is not None:
            payload["weight"] = round(float(weight), 3)
        if detail:
            payload["detail"] = detail
        links.append(payload)

    def link_budget_exhausted() -> bool:
        return max_links is not None and len(links) >= max_links

    viewer_node_id = f"viewer:{viewer_id}"
    add_node(
        viewer_node_id,
        viewer_label,
        "viewer",
        detail=viewer_detail,
        color=KIND_COLORS["viewer"],
    )

    for row in link_rows:
        if link_budget_exhausted():
            break
        entity_type = str(row["entity_type"] or "").strip() or "unknown"
        canonical_name = str(row["canonical_name"] or "").strip()
        fallback_value = str(row["target_fallback_value"] or "").strip()
        label = canonical_name or fallback_value
        if not label:
            continue
        status = str(row["status"] or "").strip()
        weight = float(row["strength"] if row["strength"] is not None else (row["confidence"] or 0.0))
        if not include_uncertain and status == "uncertain":
            continue
        if min_weight is not None and weight < min_weight:
            continue
        node_id = str(row["entity_id"] or "").strip() or f"{entity_type}:{compact_slug(label)}"
        kind = entity_type if entity_type in STABLE_NODE_KINDS else entity_type or "unknown"
        color = KIND_COLORS.get(kind)
        add_node(node_id, label, kind, color=color)

        source_memory_ids = _parse_json_list(row["source_memory_ids_json"])
        detail_parts = []
        if status:
            detail_parts.append(f"status={status}")
        if row["polarity"]:
            detail_parts.append(f"polarity={row['polarity']}")
        if source_memory_ids:
            detail_parts.append(f"evidence={len(source_memory_ids)}")
        if row["source_excerpt"]:
            detail_parts.append(str(row["source_excerpt"]).strip())
        detail = " | ".join(part for part in detail_parts if part)

        add_link(
            viewer_node_id,
            node_id,
            str(row["relation_type"] or "").strip() or "related_to",
            label=str(row["relation_type"] or "").strip() or "",
            color=color,
            weight=weight,
            detail=detail,
        )

    linked_targets = {(item["target"], item["kind"]) for item in links}
    for row in relation_rows:
        if link_budget_exhausted():
            break
        target_type = str(row["target_type"] or "").strip()
        target_value = str(row["target_id_or_value"] or "").strip()
        relation_type = str(row["relation_type"] or "").strip()
        if not target_type or not target_value or not relation_type:
            continue
        confidence = float(row["confidence"] or 0.0)
        if not include_uncertain and confidence < 0.75:
            continue
        if min_weight is not None and confidence < min_weight:
            continue
        node_id = f"{target_type}:{compact_slug(target_value)}"
        if (node_id, relation_type) in linked_targets:
            continue
        kind = target_type if target_type in STABLE_NODE_KINDS else target_type or "unknown"
        color = KIND_COLORS.get(kind)
        add_node(node_id, target_value, kind, color=color)
        add_link(
            viewer_node_id,
            node_id,
            relation_type,
            label=relation_type,
            color=color,
            weight=confidence,
        )

    kind_counts: dict[str, int] = {}
    for node in nodes:
        kind_counts[node["kind"]] = kind_counts.get(node["kind"], 0) + 1

    link_kind_counts: dict[str, int] = {}
    for link in links:
        link_kind_counts[link["kind"]] = link_kind_counts.get(link["kind"], 0) + 1

    return {
        "ok": True,
        "viewer_id": viewer_id,
        "generated_at": utc_now_iso(),
        "source": "homegraph_graph_v1",
        "meta": {
            "root_node_id": viewer_node_id,
            "filtered_by_viewer": True,
            "profile_last_updated_at": profile_last_updated_at,
            "stable_node_kinds": STABLE_NODE_KINDS,
            "stable_link_kinds": STABLE_LINK_KINDS,
            "filters_applied": {
                "include_uncertain": include_uncertain,
                "min_weight": min_weight,
                "max_links": max_links,
            },
        },
        "stats": {
            "node_count": len(nodes),
            "link_count": len(links),
            "node_kinds": kind_counts,
            "link_kinds": link_kind_counts,
        },
        "nodes": nodes,
        "links": links,
    }


def payload_as_json(
    viewer_id: str,
    db_path: Path | str,
    *,
    include_uncertain: bool = True,
    min_weight: float | None = None,
    max_links: int | None = None,
) -> str:
    return json.dumps(
        build_viewer_graph_payload(
            viewer_id,
            db_path,
            include_uncertain=include_uncertain,
            min_weight=min_weight,
            max_links=max_links,
        ),
        ensure_ascii=False,
        indent=2,
    )
