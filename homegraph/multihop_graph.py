from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homegraph.graph import KIND_COLORS, STABLE_LINK_KINDS, STABLE_NODE_KINDS, compact_slug


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


def _viewer_node_id(viewer_id: str) -> str:
    return f"viewer:{viewer_id}"


def _build_node(node_id: str, label: str, kind: str, *, detail: str = "") -> dict[str, Any]:
    payload = {
        "id": node_id,
        "label": label,
        "kind": kind,
    }
    color = KIND_COLORS.get(kind)
    if color:
        payload["color"] = color
    if detail:
        payload["detail"] = detail
    return payload


def _build_edge(
    source: str,
    target: str,
    kind: str,
    *,
    weight: float | None = None,
    detail: str = "",
    target_kind: str | None = None,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "target": target,
        "kind": kind,
    }
    if kind:
        payload["label"] = kind
    color = KIND_COLORS.get(target_kind or "")
    if color:
        payload["color"] = color
    if weight is not None:
        payload["weight"] = round(float(weight), 3)
    if detail:
        payload["detail"] = detail
    return payload


def _sort_edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -float(edge.get("weight") or 0.0),
        str(edge.get("kind") or ""),
        str(edge.get("source") or ""),
        str(edge.get("target") or ""),
    )


def _empty_payload(
    center: str,
    *,
    source: str,
    max_depth: int | None,
    include_uncertain: bool,
    min_weight: float | None,
    max_nodes: int | None,
    max_links: int | None,
    mode: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "viewer_id": center.removeprefix("viewer:") if center.startswith("viewer:") else None,
        "generated_at": utc_now_iso(),
        "source": source,
        "meta": {
            "root_node_id": center,
            "center_node_id": center,
            "filtered_by_viewer": False,
            "max_depth": max_depth,
            "truncated": False,
            "filters_applied": {
                "mode": mode,
                "include_uncertain": include_uncertain,
                "min_weight": min_weight,
                "max_nodes": max_nodes,
                "max_links": max_links,
            },
            "stable_node_kinds": STABLE_NODE_KINDS,
            "stable_link_kinds": STABLE_LINK_KINDS,
        },
        "stats": {
            "node_count": 0,
            "link_count": 0,
            "node_kinds": {},
            "link_kinds": {},
        },
        "nodes": [],
        "links": [],
    }


def _finalize_payload(
    center: str,
    *,
    source: str,
    mode: str,
    max_depth: int | None,
    include_uncertain: bool,
    min_weight: float | None,
    max_nodes: int | None,
    max_links: int | None,
    truncated: bool,
    selected_nodes: dict[str, dict[str, Any]],
    selected_edges: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    ordered_nodes = sorted(selected_nodes.values(), key=lambda item: (item["kind"], item["label"], item["id"]))
    ordered_links = sorted(selected_edges.values(), key=_sort_edge_key)

    node_kind_counts: dict[str, int] = {}
    for node in ordered_nodes:
        node_kind_counts[node["kind"]] = node_kind_counts.get(node["kind"], 0) + 1

    link_kind_counts: dict[str, int] = {}
    for edge in ordered_links:
        link_kind_counts[edge["kind"]] = link_kind_counts.get(edge["kind"], 0) + 1

    viewer_id = center.removeprefix("viewer:") if center.startswith("viewer:") else None
    return {
        "ok": True,
        "viewer_id": viewer_id,
        "generated_at": utc_now_iso(),
        "source": source,
        "meta": {
            "root_node_id": center,
            "center_node_id": center,
            "filtered_by_viewer": False,
            "max_depth": max_depth,
            "truncated": truncated,
            "filters_applied": {
                "mode": mode,
                "include_uncertain": include_uncertain,
                "min_weight": min_weight,
                "max_nodes": max_nodes,
                "max_links": max_links,
            },
            "stable_node_kinds": STABLE_NODE_KINDS,
            "stable_link_kinds": STABLE_LINK_KINDS,
        },
        "stats": {
            "node_count": len(ordered_nodes),
            "link_count": len(ordered_links),
            "node_kinds": node_kind_counts,
            "link_kinds": link_kind_counts,
        },
        "nodes": ordered_nodes,
        "links": ordered_links,
    }


def _load_graph_records(
    db_path: Path | str,
    *,
    include_uncertain: bool,
    min_weight: float | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        profiles = conn.execute(
            """
            SELECT viewer_id, display_name, viewer_login, summary_short
            FROM viewer_profiles
            """
        ).fetchall()

        try:
            link_rows = conn.execute(
                """
                SELECT
                    l.viewer_id,
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
                ORDER BY
                    COALESCE(l.strength, 0) DESC,
                    COALESCE(l.confidence, 0) DESC,
                    COALESCE(l.updated_at, '') DESC
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                link_rows = []
            else:
                raise

        relation_rows = conn.execute(
            """
            SELECT viewer_id, target_type, target_id_or_value, relation_type, confidence
            FROM viewer_relations
            ORDER BY COALESCE(confidence, 0) DESC, COALESCE(updated_at, '') DESC
            """
        ).fetchall()
    finally:
        conn.close()

    raw_nodes: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    existing_edge_ids: set[tuple[str, str, str]] = set()

    for row in profiles:
        viewer_id = str(row["viewer_id"] or "").strip()
        if not viewer_id:
            continue
        node_id = _viewer_node_id(viewer_id)
        label = (
            str(row["display_name"] or "").strip()
            or str(row["viewer_login"] or "").strip()
            or viewer_id.split(":")[-1]
        )
        detail = str(row["summary_short"] or "").strip()
        viewer_node = _build_node(node_id, label, "viewer", detail=detail)
        raw_nodes[node_id] = viewer_node
        nodes[node_id] = viewer_node

    for row in link_rows:
        viewer_id = str(row["viewer_id"] or "").strip()
        if not viewer_id:
            continue
        source = _viewer_node_id(viewer_id)
        raw_nodes.setdefault(source, _build_node(source, viewer_id.split(":")[-1], "viewer"))

        entity_type = str(row["entity_type"] or "").strip() or "unknown"
        canonical_name = str(row["canonical_name"] or "").strip()
        fallback_value = str(row["target_fallback_value"] or "").strip()
        label = canonical_name or fallback_value
        if not label:
            continue
        target = str(row["entity_id"] or "").strip() or f"{entity_type}:{compact_slug(label)}"
        target_kind = entity_type if entity_type in STABLE_NODE_KINDS else entity_type or "unknown"
        raw_nodes.setdefault(target, _build_node(target, label, target_kind))

        status = str(row["status"] or "").strip()
        weight = float(row["strength"] if row["strength"] is not None else (row["confidence"] or 0.0))
        if not include_uncertain and status == "uncertain":
            continue
        if min_weight is not None and weight < min_weight:
            continue

        nodes.setdefault(source, _build_node(source, viewer_id.split(":")[-1], "viewer"))
        nodes.setdefault(target, _build_node(target, label, target_kind))

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

        edge = _build_edge(
            source,
            target,
            str(row["relation_type"] or "").strip() or "related_to",
            weight=weight,
            detail=detail,
            target_kind=target_kind,
        )
        edge_id = (edge["source"], edge["kind"], edge["target"])
        if edge_id not in existing_edge_ids:
            existing_edge_ids.add(edge_id)
            edges.append(edge)

    for row in relation_rows:
        viewer_id = str(row["viewer_id"] or "").strip()
        target_type = str(row["target_type"] or "").strip()
        target_value = str(row["target_id_or_value"] or "").strip()
        relation_type = str(row["relation_type"] or "").strip()
        confidence = float(row["confidence"] or 0.0)
        if not viewer_id or not target_type or not target_value or not relation_type:
            continue
        if not include_uncertain and confidence < 0.75:
            continue
        if min_weight is not None and confidence < min_weight:
            continue

        source = _viewer_node_id(viewer_id)
        target = f"{target_type}:{compact_slug(target_value)}"
        if (source, relation_type, target) in existing_edge_ids:
            continue
        target_kind = target_type if target_type in STABLE_NODE_KINDS else target_type or "unknown"
        raw_nodes.setdefault(source, _build_node(source, viewer_id.split(":")[-1], "viewer"))
        raw_nodes.setdefault(target, _build_node(target, target_value, target_kind))
        nodes.setdefault(source, _build_node(source, viewer_id.split(":")[-1], "viewer"))
        nodes.setdefault(target, _build_node(target, target_value, target_kind))
        edge = _build_edge(
            source,
            target,
            relation_type,
            weight=confidence,
            target_kind=target_kind,
        )
        existing_edge_ids.add((source, relation_type, target))
        edges.append(edge)

    return nodes, sorted(edges, key=_sort_edge_key), raw_nodes


def build_multihop_graph_payload(
    center_node_id: str,
    db_path: Path | str,
    *,
    mode: str = "multihop",
    max_depth: int = 1,
    max_nodes: int | None = None,
    max_links: int | None = None,
    include_uncertain: bool = True,
    min_weight: float | None = None,
) -> dict[str, Any]:
    center = str(center_node_id or "").strip()
    selected_mode = str(mode or "multihop").strip().lower() or "multihop"
    if selected_mode not in {"multihop", "entity_focus"}:
        selected_mode = "multihop"
    bounded_depth = max(0, int(max_depth))
    bounded_nodes = max_nodes if max_nodes is None else max(1, int(max_nodes))
    bounded_links = max_links if max_links is None else max(1, int(max_links))

    nodes_by_id, edges, raw_nodes = _load_graph_records(
        db_path,
        include_uncertain=include_uncertain,
        min_weight=min_weight,
    )

    source = "homegraph_entity_focus_graph_v1" if selected_mode == "entity_focus" else "homegraph_multihop_graph_v1"

    if center not in raw_nodes:
        return _empty_payload(
            center,
            source=source,
            max_depth=1 if selected_mode == "entity_focus" else bounded_depth,
            include_uncertain=include_uncertain,
            min_weight=min_weight,
            max_nodes=bounded_nodes,
            max_links=bounded_links,
            mode=selected_mode,
        )

    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], []).append((edge["target"], edge))
        adjacency.setdefault(edge["target"], []).append((edge["source"], edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda item: _sort_edge_key(item[1]))

    selected_nodes: dict[str, dict[str, Any]] = {center: raw_nodes[center]}
    selected_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    truncated = False

    def try_add_neighbor(neighbor_id: str, edge: dict[str, Any]) -> bool:
        nonlocal truncated
        edge_id = (edge["source"], edge["kind"], edge["target"])
        if neighbor_id not in selected_nodes:
            if bounded_nodes is not None and len(selected_nodes) >= bounded_nodes:
                truncated = True
                return False
            selected_nodes[neighbor_id] = nodes_by_id[neighbor_id]
        if edge_id not in selected_edges:
            if bounded_links is not None and len(selected_edges) >= bounded_links:
                truncated = True
                return False
            selected_edges[edge_id] = edge
        return True

    if selected_mode == "entity_focus":
        direct_viewers: list[str] = []
        for neighbor_id, edge in adjacency.get(center, []):
            if not try_add_neighbor(neighbor_id, edge):
                continue
            if nodes_by_id.get(neighbor_id, {}).get("kind") == "viewer":
                direct_viewers.append(neighbor_id)

        secondary_kinds = {"stream_mode", "topic", "running_gag"}
        for viewer_id in direct_viewers:
            for neighbor_id, edge in adjacency.get(viewer_id, []):
                if neighbor_id == center:
                    continue
                neighbor_kind = nodes_by_id.get(neighbor_id, {}).get("kind")
                if neighbor_kind not in secondary_kinds:
                    continue
                try_add_neighbor(neighbor_id, edge)

        return _finalize_payload(
            center,
            source=source,
            mode=selected_mode,
            max_depth=1,
            include_uncertain=include_uncertain,
            min_weight=min_weight,
            max_nodes=bounded_nodes,
            max_links=bounded_links,
            truncated=truncated,
            selected_nodes=selected_nodes,
            selected_edges=selected_edges,
        )

    depth_by_node: dict[str, int] = {center: 0}
    queue: deque[str] = deque([center])

    while queue:
        current = queue.popleft()
        current_depth = depth_by_node[current]
        if current_depth >= bounded_depth:
            continue

        for neighbor_id, edge in adjacency.get(current, []):
            edge_id = (edge["source"], edge["kind"], edge["target"])

            if neighbor_id not in selected_nodes:
                if bounded_nodes is not None and len(selected_nodes) >= bounded_nodes:
                    truncated = True
                    continue
                selected_nodes[neighbor_id] = nodes_by_id[neighbor_id]
                depth_by_node[neighbor_id] = current_depth + 1
                queue.append(neighbor_id)

            if edge_id not in selected_edges:
                if bounded_links is not None and len(selected_edges) >= bounded_links:
                    truncated = True
                    continue
                selected_edges[edge_id] = edge

    return _finalize_payload(
        center,
        source=source,
        mode=selected_mode,
        max_depth=bounded_depth,
        include_uncertain=include_uncertain,
        min_weight=min_weight,
        max_nodes=bounded_nodes,
        max_links=bounded_links,
        truncated=truncated,
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
    )


def payload_as_json(
    center_node_id: str,
    db_path: Path | str,
    *,
    mode: str = "multihop",
    max_depth: int = 1,
    max_nodes: int | None = None,
    max_links: int | None = None,
    include_uncertain: bool = True,
    min_weight: float | None = None,
) -> str:
    return json.dumps(
        build_multihop_graph_payload(
            center_node_id,
            db_path,
            mode=mode,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_links=max_links,
            include_uncertain=include_uncertain,
            min_weight=min_weight,
        ),
        ensure_ascii=False,
        indent=2,
    )
