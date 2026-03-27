from __future__ import annotations

import json
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from admin_client import (
    AdminApiError,
    admin_healthcheck,
    delete_user_memories,
    export_user_memories,
    forget_user_memory,
    get_homegraph_multihop_graph,
    get_homegraph_user_graph,
    get_recent_memories,
    list_admin_users,
    remember_user_memory,
)
from admin_tunnel import AdminTunnelManager
from bot_config import AppConfig, load_config
from conversation_graph import load_conversation_graph
from facts_memory import load_facts_memory
from openai_review_client import OpenAIReviewError, analyze_review_export, build_review_export, is_openai_review_enabled


def _graph_data_path(filename: str) -> str:
    return str(Path(__file__).with_name(filename))


def _normalize_graph_token(value: str) -> str:
    return " ".join((value or "").strip().split()).lower()


def _truncate_graph_label(value: str, limit: int = 72) -> str:
    text = " ".join((value or "").strip().split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _conversation_turn_matches_viewer(turn: dict, viewer_filter: str) -> bool:
    if not viewer_filter:
        return True
    speaker = _normalize_graph_token(str(turn.get("speaker", "")))
    targets = {_normalize_graph_token(str(item)) for item in turn.get("target_viewers", [])}
    if speaker == viewer_filter or viewer_filter in targets:
        return True
    message_text = _normalize_graph_token(str(turn.get("message_text", "")))
    bot_reply = _normalize_graph_token(str(turn.get("bot_reply", "")))
    return viewer_filter in message_text or viewer_filter in bot_reply


def build_conversation_graph_payload(graph: dict, viewer_filter: str = "") -> dict:
    normalized_viewer = _normalize_graph_token(viewer_filter)
    nodes_by_id: dict[str, dict] = {}
    links: list[dict] = []
    turn_by_id: dict[str, dict] = {}

    all_turns: list[dict] = []
    for channel_name, channel_data in graph.get("channels", {}).items():
        for turn in channel_data.get("turns", []):
            turn_copy = dict(turn)
            turn_copy["_channel"] = channel_name
            all_turns.append(turn_copy)
            turn_id = str(turn_copy.get("turn_id", "")).strip()
            if turn_id:
                turn_by_id[turn_id] = turn_copy

    selected_turn_ids: set[str] = set()
    if normalized_viewer:
        for turn in all_turns:
            turn_id = str(turn.get("turn_id", "")).strip()
            if turn_id and _conversation_turn_matches_viewer(turn, normalized_viewer):
                selected_turn_ids.add(turn_id)
        expanded = set(selected_turn_ids)
        for turn_id in list(selected_turn_ids):
            turn = turn_by_id.get(turn_id, {})
            for linked_id in (
                str(turn.get("reply_to_turn_id", "")).strip(),
                str(turn.get("corrects_turn_id", "")).strip(),
            ):
                if linked_id and linked_id in turn_by_id:
                    expanded.add(linked_id)
        for other_turn in all_turns:
            other_turn_id = str(other_turn.get("turn_id", "")).strip()
            if not other_turn_id:
                continue
            if str(other_turn.get("reply_to_turn_id", "")).strip() in selected_turn_ids:
                expanded.add(other_turn_id)
            if str(other_turn.get("corrects_turn_id", "")).strip() in selected_turn_ids:
                expanded.add(other_turn_id)
        selected_turn_ids = expanded
    else:
        selected_turn_ids = {turn_id for turn_id in turn_by_id}

    for turn_id in selected_turn_ids:
        turn = turn_by_id.get(turn_id)
        if not turn:
            continue
        speaker = str(turn.get("speaker", "")).strip() or "viewer"
        speaker_node_id = f"viewer:{speaker}"
        if speaker_node_id not in nodes_by_id:
            nodes_by_id[speaker_node_id] = {
                "id": speaker_node_id,
                "label": speaker,
                "kind": "viewer",
                "color": "#ffb703",
                "detail": {
                    "speaker": speaker,
                    "type": "viewer",
                },
            }

        turn_label = _truncate_graph_label(str(turn.get("message_text", "")) or "(tour)")
        event_type = str(turn.get("event_type", "")).strip() or "message"
        turn_node_id = f"turn:{turn_id}"
        nodes_by_id[turn_node_id] = {
            "id": turn_node_id,
            "label": turn_label,
            "kind": "turn",
            "color": "#219ebc" if event_type not in {"correction", "owner_correction"} else "#8ecae6",
            "detail": {
                "turn_id": turn_id,
                "type": "turn",
                "channel": str(turn.get("_channel", "")),
                "speaker": speaker,
                "event_type": event_type,
                "message_text": str(turn.get("message_text", "")),
                "bot_reply": str(turn.get("bot_reply", "")),
                "reply_to_turn_id": str(turn.get("reply_to_turn_id", "")),
                "corrects_turn_id": str(turn.get("corrects_turn_id", "")),
                "target_viewers": list(turn.get("target_viewers", [])),
                "timestamp": str(turn.get("timestamp", "")),
            },
        }
        links.append(
            {
                "source": speaker_node_id,
                "target": turn_node_id,
                "kind": "authored",
                "label": "authored",
                "color": "#ffb703",
            }
        )

        reply_to_turn_id = str(turn.get("reply_to_turn_id", "")).strip()
        if reply_to_turn_id and reply_to_turn_id in selected_turn_ids:
            links.append(
                {
                    "source": turn_node_id,
                    "target": f"turn:{reply_to_turn_id}",
                    "kind": "reply_to",
                    "label": "reply_to",
                    "color": "#90be6d",
                }
            )

        corrects_turn_id = str(turn.get("corrects_turn_id", "")).strip()
        if corrects_turn_id and corrects_turn_id in selected_turn_ids:
            links.append(
                {
                    "source": turn_node_id,
                    "target": f"turn:{corrects_turn_id}",
                    "kind": "corrects",
                    "label": "corrects",
                    "color": "#f94144",
                }
            )

        for target_viewer in turn.get("target_viewers", []):
            viewer_name = str(target_viewer).strip()
            if not viewer_name:
                continue
            target_node_id = f"viewer:{viewer_name}"
            if target_node_id not in nodes_by_id:
                nodes_by_id[target_node_id] = {
                    "id": target_node_id,
                    "label": viewer_name,
                    "kind": "viewer",
                    "color": "#fb8500",
                    "detail": {
                        "speaker": viewer_name,
                        "type": "viewer",
                    },
                }
            links.append(
                {
                    "source": turn_node_id,
                    "target": target_node_id,
                    "kind": "targets",
                    "label": "targets",
                    "color": "#fb8500",
                }
            )

    return {
        "ok": True,
        "kind": "conversation",
        "viewer_filter": viewer_filter,
        "nodes": list(nodes_by_id.values()),
        "links": links,
        "stats": {
            "node_count": len(nodes_by_id),
            "link_count": len(links),
            "turn_count": len(selected_turn_ids),
        },
    }


def build_facts_graph_payload(facts_memory: dict, viewer_filter: str = "") -> dict:
    normalized_viewer = _normalize_graph_token(viewer_filter)
    nodes_by_id: dict[str, dict] = {}
    links: list[dict] = []
    fact_index = 0

    for channel_name, channel_data in facts_memory.get("channels", {}).items():
        for fact in channel_data.get("facts", []):
            subject = str(fact.get("subject", "")).strip()
            source_speaker = str(fact.get("source_speaker", "")).strip()
            predicate = str(fact.get("predicate", "")).strip()
            value = str(fact.get("value", "")).strip()
            if not subject or not source_speaker or not value:
                continue

            if normalized_viewer:
                joined_text = " ".join((subject, source_speaker, value)).lower()
                if normalized_viewer not in joined_text:
                    continue

            subject_node_id = f"subject:{subject}"
            source_node_id = f"viewer:{source_speaker}"
            fact_node_id = f"fact:{channel_name}:{fact_index}"
            fact_index += 1

            nodes_by_id.setdefault(
                subject_node_id,
                {
                    "id": subject_node_id,
                    "label": subject,
                    "kind": "subject",
                    "color": "#ffb703",
                    "detail": {"type": "subject", "subject": subject},
                },
            )
            nodes_by_id.setdefault(
                source_node_id,
                {
                    "id": source_node_id,
                    "label": source_speaker,
                    "kind": "viewer",
                    "color": "#219ebc",
                    "detail": {"type": "viewer", "speaker": source_speaker},
                },
            )
            nodes_by_id[fact_node_id] = {
                "id": fact_node_id,
                "label": _truncate_graph_label(f"{predicate}: {value}", 68),
                "kind": "fact",
                "color": "#8ecae6",
                "detail": {
                    "type": "fact",
                    "channel": channel_name,
                    "subject": subject,
                    "predicate": predicate,
                    "value": value,
                    "source_speaker": source_speaker,
                    "verification_state": str(fact.get("verification_state", "")),
                    "timestamp": str(fact.get("timestamp", "")),
                },
            }

            links.append(
                {
                    "source": source_node_id,
                    "target": fact_node_id,
                    "kind": "reported",
                    "label": "reported",
                    "color": "#219ebc",
                }
            )
            links.append(
                {
                    "source": fact_node_id,
                    "target": subject_node_id,
                    "kind": "about",
                    "label": predicate or "about",
                    "color": "#ffb703",
                }
            )

    return {
        "ok": True,
        "kind": "facts",
        "viewer_filter": viewer_filter,
        "nodes": list(nodes_by_id.values()),
        "links": links,
        "stats": {
            "node_count": len(nodes_by_id),
            "link_count": len(links),
            "fact_count": fact_index,
        },
    }


def build_homegraph_payload(graph_payload: dict, viewer_filter: str = "") -> dict:
    raw_nodes = list(graph_payload.get("nodes", []))
    raw_links = list(graph_payload.get("links", []))
    stats = dict(graph_payload.get("stats", {}))
    meta = dict(graph_payload.get("meta", {}))

    kind_colors = {
        "viewer": "#ffb703",
        "game": "#90be6d",
        "topic": "#219ebc",
        "running_gag": "#fb8500",
        "trait": "#8ecae6",
        "stream_mode": "#f94144",
        "object": "#b5179e",
    }
    link_colors = {
        "plays": "#90be6d",
        "likes": "#2a9d8f",
        "dislikes": "#f94144",
        "talks_about": "#219ebc",
        "returns_to": "#577590",
        "knows": "#8d99ae",
        "compliments": "#f4a261",
        "jokes_about": "#e76f51",
        "interacts_with": "#457b9d",
        "uses_build_style": "#6d597a",
        "plays_in_mode": "#b56576",
        "owns": "#6a994e",
    }

    nodes: list[dict] = []
    for node in raw_nodes:
        node_id = str(node.get("id", "")).strip()
        if not node_id:
            continue
        node_kind = str(node.get("kind", "")).strip() or "object"
        label = str(node.get("label", "")).strip() or node_id
        detail = dict(node.get("detail", {})) if isinstance(node.get("detail"), dict) else {}
        nodes.append(
            {
                "id": node_id,
                "label": _truncate_graph_label(label, 72),
                "kind": node_kind,
                "color": str(node.get("color", "")).strip() or kind_colors.get(node_kind, "#8ecae6"),
                "detail": {
                    "type": "homegraph_node",
                    "viewer_filter": viewer_filter,
                    **detail,
                },
            }
        )

    links: list[dict] = []
    for index, link in enumerate(raw_links):
        source = str(link.get("source", "")).strip()
        target = str(link.get("target", "")).strip()
        if not source or not target:
            continue
        link_kind = str(link.get("kind", "")).strip() or "related_to"
        links.append(
            {
                "id": str(link.get("id", "")).strip() or f"homegraph-link-{index}",
                "source": source,
                "target": target,
                "kind": link_kind,
                "label": str(link.get("label", "")).strip() or link_kind,
                "color": str(link.get("color", "")).strip() or link_colors.get(link_kind, "#94a3b8"),
                "weight": link.get("weight"),
                "detail": dict(link.get("detail", {})) if isinstance(link.get("detail"), dict) else {},
            }
        )

    stats.setdefault("node_count", len(nodes))
    stats.setdefault("link_count", len(links))

    return {
        "ok": True,
        "kind": "homegraph",
        "viewer_filter": viewer_filter,
        "nodes": nodes,
        "links": links,
        "stats": stats,
        "meta": meta,
    }


HTML_PAGE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>Mem0 Admin</title>
  <script src="https://unpkg.com/3d-force-graph@1.76.2/dist/3d-force-graph.min.js"></script>
  <style>
    :root {
      --bg: #f4efe7;
      --panel: rgba(255, 250, 243, 0.92);
      --panel-strong: #fffdf8;
      --line: #d9cbb7;
      --line-strong: #b79f7f;
      --text: #24190f;
      --muted: #6a5848;
      --accent: #0d4f4d;
      --accent-soft: #dceceb;
      --accent-2: #b85c38;
      --danger: #ab2d2d;
      --success: #226a3d;
      --shadow: 0 20px 50px rgba(54, 34, 18, 0.12);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(13, 79, 77, 0.16), transparent 28%),
        radial-gradient(circle at top right, rgba(184, 92, 56, 0.16), transparent 24%),
        linear-gradient(180deg, #f7f1e8 0%, var(--bg) 100%);
    }
    .app-shell {
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 22px;
    }
    .title-block h1 {
      margin: 0;
      font-size: 2.1rem;
      letter-spacing: 0.01em;
    }
    .title-block p {
      margin: 8px 0 0;
      color: var(--muted);
      max-width: 720px;
    }
    .status-chip {
      min-width: 280px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: var(--shadow);
      font-size: 0.95rem;
      color: var(--muted);
    }
    .status-line { font-weight: 600; }
    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin: 0 0 22px;
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .toolbar-spacer {
      margin-left: auto;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .analysis-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin: -6px 0 22px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid rgba(13, 79, 77, 0.22);
      background: linear-gradient(135deg, rgba(13, 79, 77, 0.1), rgba(220, 236, 235, 0.78));
      box-shadow: var(--shadow);
    }
    .analysis-banner[hidden] { display: none; }
    .analysis-banner-main {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .analysis-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(13, 79, 77, 0.14);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .analysis-pill::before {
      content: '';
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 0 rgba(13, 79, 77, 0.35);
      animation: analysis-pulse 1.4s ease-out infinite;
    }
    .analysis-banner-text strong {
      display: block;
      margin-bottom: 2px;
    }
    .analysis-banner-text div {
      color: var(--muted);
      font-size: 0.94rem;
    }
    @keyframes analysis-pulse {
      0% { box-shadow: 0 0 0 0 rgba(13, 79, 77, 0.35); }
      70% { box-shadow: 0 0 0 10px rgba(13, 79, 77, 0); }
      100% { box-shadow: 0 0 0 0 rgba(13, 79, 77, 0); }
    }
    .row {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: calc(var(--radius) + 2px);
      padding: 18px;
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .panel-left {
      position: sticky;
      top: 20px;
      max-height: calc(100vh - 40px);
      overflow: auto;
    }
    .muted { color: var(--muted); }
    .error {
      color: var(--danger);
      margin-top: 16px;
      padding: 12px 14px;
      border: 1px solid rgba(171, 45, 45, 0.24);
      border-radius: 12px;
      background: rgba(171, 45, 45, 0.08);
    }
    button, select, input, textarea {
      font: inherit;
    }
    button {
      padding: 10px 14px;
      cursor: pointer;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fffdf9;
      color: var(--text);
      transition: 120ms ease;
    }
    button:hover { transform: translateY(-1px); border-color: var(--line-strong); }
    button:disabled { cursor: default; opacity: 0.55; transform: none; }
    .primary-button {
      background: var(--accent);
      color: #f6fffe;
      border-color: var(--accent);
    }
    .primary-button:hover { background: #0b4341; border-color: #0b4341; }
    ul { list-style: none; padding: 0; margin: 0; }
    li { margin: 10px 0; }
    .viewer-column-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 14px;
    }
    .viewer-column-title h2,
    .main-card-title h2,
    .section-head h2,
    .graph-card-title h3,
    .graph-sidebar h3 { margin: 0; }
    .viewer-count {
      color: var(--muted);
      font-size: 0.92rem;
    }
    .user-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      cursor: pointer;
      background: rgba(255, 255, 255, 0.75);
      transition: 140ms ease;
    }
    .user-item.active {
      border-color: var(--accent);
      background: linear-gradient(135deg, rgba(13, 79, 77, 0.12), rgba(255, 255, 255, 0.92));
      box-shadow: inset 0 0 0 1px rgba(13, 79, 77, 0.12);
    }
    .user-item:hover { background: rgba(255, 255, 255, 0.96); border-color: var(--line-strong); }
    .user-item-header { display: flex; flex-direction: column; gap: 10px; align-items: stretch; }
    .user-item-main { flex: 1; min-width: 0; }
    .user-item-main strong { display: block; margin-bottom: 2px; }
    .viewer-item-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .viewer-icon-button {
      min-width: 34px;
      height: 34px;
      padding: 0 8px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      background: rgba(13, 79, 77, 0.05);
      border-color: rgba(13, 79, 77, 0.16);
    }
    .viewer-icon-button svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
      stroke-width: 1.85;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .viewer-icon-button-edit {
      color: #1f5f8b;
      background: rgba(31, 95, 139, 0.08);
      border-color: rgba(31, 95, 139, 0.18);
    }
    .viewer-icon-button-export {
      color: var(--accent);
    }
    .viewer-icon-button-review {
      color: #8b5a1f;
      background: rgba(139, 90, 31, 0.08);
      border-color: rgba(139, 90, 31, 0.18);
    }
    .viewer-icon-button-danger {
      color: var(--danger);
      border-color: rgba(171, 45, 45, 0.28);
      background: rgba(171, 45, 45, 0.05);
    }
    .edit-panel { margin-top: 24px; }
    .scroll-box { max-height: 520px; overflow-y: auto; padding-right: 6px; }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(247, 241, 233, 0.92);
      padding: 12px;
      border-radius: 12px;
      margin: 0;
      border: 1px solid rgba(183, 159, 127, 0.18);
    }
    .memory-card {
      border: 1px solid rgba(183, 159, 127, 0.28);
      border-radius: 16px;
      padding: 14px;
      margin: 12px 0;
      background: rgba(255, 255, 255, 0.84);
    }
    .memory-meta { color: var(--muted); font-size: 0.9rem; margin-top: 8px; }
    .actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
    .proposal-accepted { border-color: rgba(34, 106, 61, 0.4); background: rgba(34, 106, 61, 0.08); }
    .proposal-rejected { border-color: rgba(171, 45, 45, 0.38); background: rgba(171, 45, 45, 0.08); }
    .btn-accept-selected { background: var(--success); color: white; border-color: var(--success); }
    .btn-reject-selected { background: var(--danger); color: white; border-color: var(--danger); }
    .graph-toolbar {
      display:flex;
      gap:12px;
      align-items:center;
      margin: 12px 0 16px;
      flex-wrap: wrap;
      padding: 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(183, 159, 127, 0.24);
    }
    .graph-toolbar label {
      font-size: 0.92rem;
      color: var(--muted);
    }
    .range-wrap {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 180px;
    }
    .range-wrap input[type="range"] {
      width: 120px;
      accent-color: var(--accent);
    }
    .range-value {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(13, 79, 77, 0.1);
      color: var(--accent);
      font-size: 0.88rem;
      font-weight: 700;
    }
    .graph-toolbar select,
    .graph-toolbar input,
    .toolbar select {
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fffdf9;
      color: var(--text);
    }
    .graph-layout { display:grid; grid-template-columns: minmax(0, 1fr) 360px; gap:16px; align-items: stretch; }
    .graph-stage-shell {
      min-height: clamp(420px, 68vh, 780px);
      height: clamp(420px, 68vh, 780px);
      position: relative;
      flex: 1;
    }
    .graph-stage {
      width: 100%;
      height: 100%;
      border: 1px solid rgba(11, 48, 56, 0.25);
      border-radius: 20px;
      overflow: hidden;
      background: radial-gradient(circle at top, #15324e 0%, #08121d 74%);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    }
    .graph-label-layer {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
      z-index: 3;
    }
    .graph-node-label {
      position: absolute;
      transform: translate(-50%, -50%);
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(8, 18, 29, 0.72);
      color: #f8fafc;
      font-size: 12px;
      line-height: 1.2;
      white-space: nowrap;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.22);
      border: 1px solid rgba(255,255,255,0.12);
      text-shadow: 0 1px 0 rgba(0,0,0,0.26);
    }
    .graph-sidebar {
      display: flex;
      flex-direction: column;
      gap: 14px;
      border: 1px solid rgba(183, 159, 127, 0.24);
      border-radius: 20px;
      padding: 14px;
      background: rgba(255, 252, 247, 0.88);
    }
    .graph-sidebar pre { min-height: 180px; }
    .graph-caption { color: var(--muted); font-size:0.95rem; }
    .graph-card {
      padding: 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(183, 159, 127, 0.22);
    }
    .graph-card-title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 10px;
    }
    .graph-legend-grid {
      display: grid;
      gap: 10px;
    }
    .graph-legend-section {
      display: grid;
      gap: 8px;
    }
    .graph-legend-section strong {
      font-size: 0.92rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }
    .legend-list {
      display: grid;
      gap: 8px;
    }
    .legend-item {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      font-size: 0.92rem;
    }
    .legend-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .legend-swatch,
    .legend-line {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      flex: 0 0 auto;
      border: 1px solid rgba(0,0,0,0.12);
    }
    .legend-line {
      height: 4px;
      width: 20px;
      border-radius: 999px;
      border: none;
    }
    .legend-note {
      font-size: 0.9rem;
      color: var(--muted);
      line-height: 1.4;
    }
    .memory-form { border: 1px solid rgba(183, 159, 127, 0.22); border-radius: 16px; padding: 14px; margin-bottom: 14px; background: rgba(255,255,255,0.86); }
    .memory-form textarea {
      width: 100%;
      min-height: 92px;
      resize: vertical;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffdf9;
    }
    .memory-form-row { display:flex; gap:10px; flex-wrap: wrap; margin: 10px 0; }
    .memory-form-row label { display:flex; flex-direction:column; gap:4px; font-size: 0.95rem; color: var(--muted); }
    .memory-form-row select { min-width: 140px; }
    .modebar {
      display:flex;
      gap:10px;
      margin: 0 0 18px;
      padding: 8px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid var(--line);
      width: fit-content;
      box-shadow: var(--shadow);
    }
    .mode-button {
      padding: 10px 16px;
      border: 1px solid transparent;
      border-radius: 999px;
      background: transparent;
    }
    .mode-button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    .mode-panel[hidden] { display:none; }
    .main-card-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 6px;
    }
    .section-head { display:flex; align-items:center; justify-content: space-between; gap:12px; margin: 0 0 12px; }
    .section-kicker {
      color: var(--accent-2);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
    }
    @media (max-width: 1120px) {
      .row { grid-template-columns: 1fr; }
      .panel-left { position: static; max-height: none; }
      .graph-layout { grid-template-columns: 1fr; }
      .topbar { flex-direction: column; }
      .status-chip { min-width: 0; width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <div class="topbar">
      <div class="title-block">
        <div class="section-kicker">Console Interne</div>
        <h1>Mem0 Admin Workspace</h1>
        <p>Pilotage global, data stewardship et inspection visuelle des graphes conversationnels, factuels et Homegraph.</p>
      </div>
      <div class="status-chip">
        <div class="section-kicker">Health</div>
        <div id="status" class="status-line">Chargement…</div>
      </div>
    </div>
    <div class="toolbar">
      <button id="refresh-button" class="primary-button" type="button">Rafraîchir</button>
      <label for="severity-select">Sévérité</label>
      <select id="severity-select">
        <option value="conservative">Conservateur</option>
        <option value="balanced" selected>Équilibré</option>
        <option value="aggressive">Agressif</option>
      </select>
      <span id="selection" class="toolbar-spacer">Aucun viewer sélectionné.</span>
    </div>
    <div id="analysis-banner" class="analysis-banner" hidden>
      <div class="analysis-banner-main">
        <span class="analysis-pill">Analyse GPT</span>
        <div class="analysis-banner-text">
          <strong id="analysis-banner-title">Analyse en cours</strong>
          <div id="analysis-banner-detail">La navigation est temporairement verrouillée.</div>
        </div>
      </div>
      <div id="analysis-banner-target" class="muted"></div>
    </div>
    <div class="modebar">
      <button id="mode-global-button" class="mode-button active" type="button">Global</button>
      <button id="mode-steward-button" class="mode-button" type="button">Data Steward</button>
    </div>
    <div class="row">
      <div class="panel panel-left">
        <div class="viewer-column-title">
          <h2>Viewers</h2>
          <span id="viewer-count" class="viewer-count">0 items</span>
        </div>
        <ul id="users"></ul>
      </div>
      <div class="panel">
        <div class="main-card-title">
          <div>
            <div class="section-kicker">Workspace</div>
            <h2>Inspection et opérations</h2>
          </div>
          <div class="muted">Navigation rapide entre exploration globale et stewardship.</div>
        </div>
      <div id="global-panel" class="mode-panel">
        <div class="section-head">
          <div>
            <div class="section-kicker">Exploration</div>
            <h2>Graph 3D</h2>
          </div>
          <span class="muted">Exploration globale, drill-down Homegraph et inspection des liens.</span>
        </div>
        <div class="graph-toolbar">
          <label for="graph-kind-select">Graphe</label>
          <select id="graph-kind-select">
            <option value="conversation">Conversation</option>
            <option value="facts">Faits</option>
            <option value="homegraph">Homegraph</option>
          </select>
          <span id="homegraph-filter-group" style="display:none;">
            <label for="homegraph-uncertain-select">Incertain</label>
            <select id="homegraph-uncertain-select">
              <option value="true" selected>Oui</option>
              <option value="false">Non</option>
            </select>
            <label for="homegraph-min-weight-input">Poids min</label>
            <input id="homegraph-min-weight-input" type="number" min="0" max="1" step="0.1" placeholder="0.7" style="width:72px;" />
            <label for="homegraph-max-links-input">Liens max</label>
            <input id="homegraph-max-links-input" type="number" min="1" step="1" value="12" style="width:72px;" />
            <label for="homegraph-depth-slider">Profondeur</label>
            <span class="range-wrap">
              <input id="homegraph-depth-slider" type="range" min="1" max="4" step="1" value="1" />
              <span id="homegraph-depth-value" class="range-value">1</span>
            </span>
            <input id="homegraph-max-depth-input" type="number" min="1" step="1" value="1" style="width:72px;" />
            <label for="homegraph-max-nodes-input">Nœuds max</label>
            <input id="homegraph-max-nodes-input" type="number" min="1" step="1" value="20" style="width:72px;" />
          </span>
          <button id="graph-refresh-button" type="button">Charger</button>
          <button id="graph-reset-button" type="button">Réinitialiser le focus</button>
          <span id="graph-selection" class="muted">Vue globale.</span>
        </div>
        <div class="graph-layout">
          <div class="graph-stage-shell">
            <div class="graph-stage" id="graph-stage"></div>
            <div class="graph-label-layer" id="graph-label-layer"></div>
          </div>
          <div class="graph-sidebar">
            <div class="graph-card">
              <div class="graph-card-title">
                <h3>État</h3>
                <span class="muted">Live</span>
              </div>
              <div class="graph-caption" id="graph-stats">Aucune donnée chargée.</div>
            </div>
            <div class="graph-card">
              <div class="graph-card-title">
                <h3>Légende</h3>
                <span class="muted" id="graph-legend-mode">Conversation</span>
              </div>
              <div id="graph-legend" class="graph-legend-grid"></div>
            </div>
            <div class="graph-card">
              <div class="graph-card-title">
                <h3>Détails</h3>
                <span class="muted">Nœud actif</span>
              </div>
              <pre id="graph-details">Clique sur un nœud pour isoler ses liens.</pre>
            </div>
          </div>
        </div>
      </div>
      <div id="steward-panel" class="mode-panel" hidden>
        <div class="section-head">
          <div>
            <div class="section-kicker">Stewardship</div>
            <h2>Recent</h2>
          </div>
          <span class="muted">Inspection, édition et revue des souvenirs.</span>
        </div>
        <div id="recent">Sélectionne un viewer.</div>
        <div class="edit-panel">
          <div class="section-head" style="margin-top:24px;">
            <h2>Édition</h2>
            <span id="editor-selection" class="muted">Aucun viewer ouvert en édition.</span>
          </div>
          <div id="editor" class="muted">Clique sur “Éditer” pour afficher toute la mémoire d’un viewer.</div>
        </div>
        <div class="section-head" style="margin-top:24px;">
          <h2>Review</h2>
          <div class="actions" style="margin-top:0;">
            <button id="analyze-button" type="button" disabled>Analyser avec GPT</button>
            <button id="verbose-button" type="button">Verbose: OFF</button>
          </div>
        </div>
        <div id="review" class="muted">Aucune analyse lancée.</div>
      </div>
      <div id="error" class="error"></div>
    </div>
  </div>
  </div>
  <script>
    let selectedUserId = null;
    let selectedViewerLabel = null;
    let editingUserId = null;
    let editingViewerLabel = null;
    let knownUsers = [];
    let verboseEnabled = false;
    let reviewSeverity = 'balanced';
    let graphKind = 'conversation';
    let homegraphIncludeUncertain = true;
    let homegraphMinWeight = '';
    let homegraphMaxLinks = '12';
    let homegraphMaxDepth = '1';
    let homegraphMaxNodes = '20';
    let homegraphCenterNodeId = '';
    let homegraphRootNodeId = '';
    let homegraphDepthReloadTimer = null;
    let graphInstance = null;
    let graphResizeObserver = null;
    let fullGraphData = { nodes: [], links: [] };
    let displayedGraphData = { nodes: [], links: [] };
    let lastGraphSignature = '';
    let focusedNodeId = null;
    let adminMode = 'global';
    window.currentAnalysis = null;
    window.proposalDecisions = {};
    window.analysisInFlight = null;

    function setError(message) {
      document.getElementById('error').textContent = message || '';
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function normalizeToken(value) {
      return String(value || '').trim().toLowerCase();
    }

    function getAnalysisInFlight() {
      const state = window.analysisInFlight;
      if (!state || !state.userId) {
        return null;
      }
      return state;
    }

    function isAnalysisPending() {
      return !!getAnalysisInFlight();
    }

    function setAnalysisInFlight(userId, viewerLabel) {
      window.analysisInFlight = {
        userId: userId || '',
        viewerLabel: viewerLabel || userId || '',
      };
    }

    function clearAnalysisInFlight(userId = '') {
      const pending = getAnalysisInFlight();
      if (!pending) {
        return;
      }
      if (userId && normalizeToken(pending.userId) !== normalizeToken(userId)) {
        return;
      }
      window.analysisInFlight = null;
    }

    function canOpenViewer(targetUserId, targetViewerLabel = targetUserId) {
      const pending = getAnalysisInFlight();
      if (!pending) {
        return true;
      }
      if (normalizeToken(pending.userId) === normalizeToken(targetUserId)) {
        return true;
      }
      setError(
        `Analyse GPT en cours pour ${pending.viewerLabel || pending.userId}. Attends la fin avant d’ouvrir ${targetViewerLabel || targetUserId}.`
      );
      return false;
    }

    function updateAnalysisBanner() {
      const bannerNode = document.getElementById('analysis-banner');
      const titleNode = document.getElementById('analysis-banner-title');
      const detailNode = document.getElementById('analysis-banner-detail');
      const targetNode = document.getElementById('analysis-banner-target');
      if (!bannerNode || !titleNode || !detailNode || !targetNode) {
        return;
      }
      const pending = getAnalysisInFlight();
      if (!pending) {
        bannerNode.hidden = true;
        titleNode.textContent = 'Analyse en cours';
        detailNode.textContent = 'La navigation est temporairement verrouillée.';
        targetNode.textContent = '';
        return;
      }
      bannerNode.hidden = false;
      titleNode.textContent = `Analyse GPT en cours pour ${pending.viewerLabel || pending.userId}`;
      detailNode.textContent = 'Attends le résultat avant d’ouvrir un autre viewer ou une autre édition.';
      targetNode.textContent = pending.userId || '';
    }

    function updateModeState() {
      const globalButton = document.getElementById('mode-global-button');
      const stewardButton = document.getElementById('mode-steward-button');
      const globalPanel = document.getElementById('global-panel');
      const stewardPanel = document.getElementById('steward-panel');
      globalButton.classList.toggle('active', adminMode === 'global');
      stewardButton.classList.toggle('active', adminMode === 'steward');
      globalPanel.hidden = adminMode !== 'global';
      stewardPanel.hidden = adminMode !== 'steward';
    }

    function updateSelectionState() {
      const pendingAnalysis = getAnalysisInFlight();
      document.getElementById('selection').textContent = selectedViewerLabel
        ? `Viewer sélectionné : ${selectedViewerLabel}`
        : 'Aucun viewer sélectionné.';
      document.getElementById('editor-selection').textContent = editingViewerLabel
        ? `Édition ouverte : ${editingViewerLabel}`
        : 'Aucun viewer ouvert en édition.';
      document.getElementById('analyze-button').disabled = !selectedUserId || !!pendingAnalysis;
      document.getElementById('analyze-button').title = pendingAnalysis
        ? `Analyse GPT en cours pour ${pendingAnalysis.viewerLabel || pendingAnalysis.userId}.`
        : '';
      document.getElementById('verbose-button').textContent = `Verbose: ${verboseEnabled ? 'ON' : 'OFF'}`;
      document.getElementById('graph-selection').textContent = selectedViewerLabel
        ? `Vue filtrée sur : ${selectedViewerLabel}`
        : 'Vue globale.';
      if (graphKind === 'homegraph' && homegraphCenterNodeId) {
        document.getElementById('graph-selection').textContent += ` | centre: ${homegraphCenterNodeId}`;
      }
      document.getElementById('homegraph-filter-group').style.display = graphKind === 'homegraph' ? 'contents' : 'none';
      renderGraphLegend();
      updateAnalysisBanner();
      updateModeState();
    }

    function getGraphLegendModel() {
      if (graphKind === 'homegraph') {
        return {
          mode: 'Homegraph',
          nodeItems: [
            { label: 'Viewer', color: '#4F46E5' },
            { label: 'Jeu', color: '#22C55E' },
            { label: 'Sujet', color: '#0EA5E9' },
            { label: 'Running gag', color: '#F97316' },
            { label: 'Mode de jeu', color: '#EF4444' },
            { label: 'Objet / autre', color: '#A855F7' },
          ],
          linkItems: [
            { label: 'plays', color: '#22C55E' },
            { label: 'likes', color: '#14B8A6' },
            { label: 'talks_about', color: '#0EA5E9' },
            { label: 'interacts_with', color: '#3B82F6' },
            { label: 'compliments', color: '#F59E0B' },
            { label: 'jokes_about', color: '#F97316' },
          ],
          note: 'Les couleurs portent le type des nœuds et des relations. Le libellé affiché près du nœud reste limité au nom.',
        };
      }
      if (graphKind === 'facts') {
        return {
          mode: 'Faits',
          nodeItems: [
            { label: 'Sujet', color: '#FFB703' },
            { label: 'Viewer source', color: '#219EBC' },
            { label: 'Fait', color: '#8ECAE6' },
          ],
          linkItems: [
            { label: 'reported', color: '#219EBC' },
            { label: 'about', color: '#FFB703' },
          ],
          note: 'Le graphe de faits sépare le sujet, la source et l’assertion mémorisée.',
        };
      }
      return {
        mode: 'Conversation',
        nodeItems: [
          { label: 'Viewer', color: '#FFB703' },
          { label: 'Tour', color: '#219EBC' },
          { label: 'Correction', color: '#8ECAE6' },
        ],
        linkItems: [
          { label: 'authored', color: '#FFB703' },
          { label: 'reply_to', color: '#90BE6D' },
          { label: 'corrects', color: '#F94144' },
          { label: 'targets', color: '#FB8500' },
        ],
        note: 'Le graphe conversationnel montre les tours, leurs auteurs, les réponses et les corrections.',
      };
    }

    function renderGraphLegend() {
      const legendNode = document.getElementById('graph-legend');
      const legendModeNode = document.getElementById('graph-legend-mode');
      if (!legendNode || !legendModeNode) {
        return;
      }
      const model = getGraphLegendModel();
      legendModeNode.textContent = model.mode;
      const renderItems = (items, swatchClass) => items.map((item) => `
        <div class="legend-item">
          <span class="legend-chip">
            <span class="${swatchClass}" style="background:${item.color};"></span>
            <span>${escapeHtml(item.label)}</span>
          </span>
        </div>
      `).join('');
      legendNode.innerHTML = `
        <div class="graph-legend-section">
          <strong>Nœuds</strong>
          <div class="legend-list">${renderItems(model.nodeItems, 'legend-swatch')}</div>
        </div>
        <div class="graph-legend-section">
          <strong>Liens</strong>
          <div class="legend-list">${renderItems(model.linkItems, 'legend-line')}</div>
        </div>
        <div class="legend-note">${escapeHtml(model.note)}</div>
      `;
    }

    function resetReviewPanel(message = 'Aucune analyse lancée.') {
      window.currentAnalysis = null;
      window.proposalDecisions = {};
      document.getElementById('review').innerHTML = `<div class="muted">${escapeHtml(message)}</div>`;
    }

    function updateProposalCardState(index) {
      const card = document.getElementById(`proposal-${index}`);
      const acceptButton = document.getElementById(`proposal-accept-${index}`);
      const rejectButton = document.getElementById(`proposal-reject-${index}`);
      if (!card || !acceptButton || !rejectButton) {
        return;
      }
      card.classList.remove('proposal-accepted', 'proposal-rejected');
      acceptButton.classList.remove('btn-accept-selected');
      rejectButton.classList.remove('btn-reject-selected');

      const decision = window.proposalDecisions[index] || 'pending';
      if (decision === 'accepted') {
        card.classList.add('proposal-accepted');
        acceptButton.classList.add('btn-accept-selected');
      } else if (decision === 'rejected') {
        card.classList.add('proposal-rejected');
        rejectButton.classList.add('btn-reject-selected');
      }
    }

    function renderCommitToolbar() {
      const acceptedCount = Object.values(window.proposalDecisions).filter((v) => v === 'accepted').length;
      return `
        <div class="memory-card" data-commit-toolbar="true">
          <strong>Commit</strong>
          <pre class="commit-count">Propositions acceptées: ${acceptedCount}</pre>
          <div class="actions">
            <button class="commit-button" type="button" onclick="commitAcceptedProposals()" ${acceptedCount === 0 ? 'disabled' : ''}>Commit</button>
          </div>
        </div>
      `;
    }

    async function toggleVerbose() {
      const response = await fetch('/api/review-verbose', { method: 'POST' });
      const data = await response.json();
      verboseEnabled = !!data.enabled;
      updateSelectionState();
    }

    async function loadStatus() {
      const response = await fetch('/api/status');
      const data = await response.json();
      verboseEnabled = !!data.review_verbose;
      document.getElementById('status').textContent =
        `Tunnel: ${data.tunnel.running ? 'OK' : 'OFF'} | Port local: ${data.tunnel.local_port_open ? 'OK' : 'OFF'} | Admin API: ${data.admin_api_ok ? 'OK' : 'KO'}`;
      updateSelectionState();
    }

    async function loadUsers() {
      const response = await fetch('/api/users');
      const data = await response.json();
      setError(data.ok ? '' : (data.error || 'Erreur lors du chargement des viewers.'));
      const usersNode = document.getElementById('users');
      const viewerCountNode = document.getElementById('viewer-count');
      usersNode.innerHTML = '';
      if (!data.ok) {
        if (viewerCountNode) {
          viewerCountNode.textContent = '0 items';
        }
        usersNode.innerHTML = '<li class="muted">Impossible de charger les viewers.</li>';
        return;
      }
      if (!data.users || data.users.length === 0) {
        if (viewerCountNode) {
          viewerCountNode.textContent = '0 items';
        }
        usersNode.innerHTML = '<li class="muted">Aucun viewer retourné par l\\'API admin.</li>';
        return;
      }
      knownUsers = Array.isArray(data.users) ? data.users : [];
      if (viewerCountNode) {
        viewerCountNode.textContent = `${knownUsers.length} items`;
      }
      for (const user of data.users) {
        const item = document.createElement('li');
        const button = document.createElement('div');
        const viewerLabel = user.viewer || user.user_id;
        button.className = 'user-item';
        button.title = user.user_id || viewerLabel;
        if (user.user_id === selectedUserId) {
          button.classList.add('active');
        }
        button.innerHTML = `
          <div class="user-item-header">
            <div class="user-item-main">
              <strong>${escapeHtml(viewerLabel)}</strong>
            </div>
            <div class="viewer-item-actions">
              <button type="button" class="viewer-icon-button viewer-icon-button-edit edit-viewer-button" title="Éditer ${escapeHtml(viewerLabel)}" aria-label="Éditer ${escapeHtml(viewerLabel)}">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4Z"/></svg>
              </button>
              <button type="button" class="viewer-icon-button viewer-icon-button-export export-viewer-button" title="Exporter ${escapeHtml(viewerLabel)}" aria-label="Exporter ${escapeHtml(viewerLabel)}">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
              </button>
              <button type="button" class="viewer-icon-button viewer-icon-button-review export-review-viewer-button" title="Exporter pour revue ${escapeHtml(viewerLabel)}" aria-label="Exporter pour revue ${escapeHtml(viewerLabel)}">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14l4-3h10a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6"/></svg>
              </button>
              <button type="button" class="viewer-icon-button viewer-icon-button-danger purge-viewer-button" title="Purger ${escapeHtml(viewerLabel)}" aria-label="Purger ${escapeHtml(viewerLabel)}">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
              </button>
            </div>
          </div>
        `;
        const editButton = button.querySelector('.edit-viewer-button');
        if (editButton) {
          editButton.onclick = (event) => {
            event.stopPropagation();
            openEditor(user.user_id, viewerLabel);
          };
        }
        const exportButton = button.querySelector('.export-viewer-button');
        if (exportButton) {
          exportButton.onclick = (event) => {
            event.stopPropagation();
            exportUser(user.user_id, viewerLabel);
          };
        }
        const exportReviewButton = button.querySelector('.export-review-viewer-button');
        if (exportReviewButton) {
          exportReviewButton.onclick = (event) => {
            event.stopPropagation();
            exportUserForReview(user.user_id, viewerLabel);
          };
        }
        const purgeButton = button.querySelector('.purge-viewer-button');
        if (purgeButton) {
          purgeButton.onclick = (event) => {
            event.stopPropagation();
            purgeUser(user.user_id, viewerLabel);
          };
        }
        button.onclick = () => loadRecent(user.user_id, user.viewer || user.user_id);
        item.appendChild(button);
        usersNode.appendChild(item);
      }
    }

    function resolveHomegraphViewerUser(node) {
      if (!node || node.kind !== 'viewer') {
        return null;
      }
      const nodeId = String(node.id || '').trim();
      const nodeLabel = String(node.label || '').trim();
      const shortId = nodeId.startsWith('viewer:') ? nodeId.slice('viewer:'.length) : nodeId;
      const currentUserParts = String(selectedUserId || '').split(':');
      const currentChannel = currentUserParts.length >= 2 ? currentUserParts[1] : '';

      for (const user of knownUsers) {
        if (normalizeToken(user.user_id) === normalizeToken(shortId)) {
          return user;
        }
      }
      for (const user of knownUsers) {
        if (normalizeToken(user.viewer) === normalizeToken(shortId)) {
          return user;
        }
      }
      for (const user of knownUsers) {
        if (normalizeToken(user.viewer) === normalizeToken(nodeLabel)) {
          return user;
        }
      }
      if (currentChannel && shortId && !shortId.includes(':')) {
        return {
          user_id: `twitch:${currentChannel}:viewer:${shortId}`,
          channel: currentChannel,
          viewer: nodeLabel || shortId,
        };
      }
      return null;
    }

    function cloneGraphData(data) {
      return {
        nodes: (data.nodes || []).map((node) => ({ ...node })),
        links: (data.links || []).map((link, index) => ({ ...link, id: link.id || `link-${index}` })),
      };
    }

    function getFocusedGraphData(data, nodeId) {
      if (!nodeId) {
        return cloneGraphData(data);
      }
      const linkedNodeIds = new Set([nodeId]);
      const links = [];
      for (const link of (data.links || [])) {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        if (sourceId === nodeId || targetId === nodeId) {
          linkedNodeIds.add(sourceId);
          linkedNodeIds.add(targetId);
          links.push({ ...link, source: sourceId, target: targetId });
        }
      }
      const nodes = (data.nodes || []).filter((node) => linkedNodeIds.has(node.id)).map((node) => ({ ...node }));
      return { nodes, links };
    }

    function renderGraphDetails(node) {
      const detailsNode = document.getElementById('graph-details');
      if (!node) {
        detailsNode.textContent = graphKind === 'homegraph'
          ? 'Clique sur un nœud Homegraph pour recharger un sous-graphe centré sur ce nœud.'
          : 'Clique sur un nœud pour isoler ses liens.';
        return;
      }
      const detail = node.detail || {};
      detailsNode.textContent = JSON.stringify(
        {
          id: node.id,
          label: node.label,
          kind: node.kind,
          ...detail,
        },
        null,
        2
      );
    }

    function setGraphStatus(message) {
      document.getElementById('graph-stats').textContent = message;
    }

    function findNodeById(data, nodeId) {
      if (!nodeId) {
        return null;
      }
      for (const node of (data.nodes || [])) {
        if (node.id === nodeId) {
          return node;
        }
      }
      return null;
    }

    function computeGraphSignature(data) {
      const nodeIds = (data.nodes || []).map((node) => String(node.id || '')).sort();
      const linkIds = (data.links || []).map((link) => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        return `${sourceId}|${targetId}|${link.kind || ''}`;
      }).sort();
      return JSON.stringify({ nodeIds, linkIds });
    }

    function focusCameraOnNode(node) {
      if (!graphInstance || !node) {
        return;
      }
      const distance = 110;
      const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
      graphInstance.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        900
      );
    }

    function applyGraphMouseConfig() {
      if (!graphInstance || !graphInstance.controls) {
        return;
      }
      const controls = graphInstance.controls();
      if (!controls) {
        return;
      }
      controls.mouseButtons = {
        LEFT: 0,
        MIDDLE: 1,
        RIGHT: 2,
      };
    }

    function resetGraphInteractionState() {
      if (!graphInstance || !graphInstance.controls) {
        return;
      }
      const controls = graphInstance.controls();
      const stage = document.getElementById('graph-stage');
      if (stage) {
        stage.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        stage.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
        stage.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
      }
      if (!controls) {
        return;
      }
      controls.enabled = false;
      window.setTimeout(() => {
        controls.enabled = true;
        applyGraphMouseConfig();
        if (typeof controls.update === 'function') {
          controls.update();
        }
      }, 0);
    }

    function getNodeVisualSize(node) {
      if (graphKind === 'homegraph' && homegraphCenterNodeId && node.id === homegraphCenterNodeId) {
        return 12;
      }
      return node.kind === 'turn' || node.kind === 'fact' ? 4 : 7;
    }

    function getHomegraphRequestMode() {
      if (!homegraphCenterNodeId) {
        return '';
      }
      if (homegraphCenterNodeId.startsWith('viewer:')) {
        return 'multihop';
      }
      const depthValue = Math.max(1, parseInt(homegraphMaxDepth || '1', 10) || 1);
      return depthValue <= 1 ? 'entity_focus' : 'multihop';
    }

    function syncHomegraphDepthControls() {
      const sliderNode = document.getElementById('homegraph-depth-slider');
      const inputNode = document.getElementById('homegraph-max-depth-input');
      const valueNode = document.getElementById('homegraph-depth-value');
      const depthValue = String(Math.max(1, parseInt(homegraphMaxDepth || '1', 10) || 1));
      homegraphMaxDepth = depthValue;
      if (sliderNode) {
        sliderNode.value = depthValue;
      }
      if (inputNode) {
        inputNode.value = depthValue;
      }
      if (valueNode) {
        valueNode.textContent = depthValue;
      }
    }

    function scheduleHomegraphReload() {
      if (graphKind !== 'homegraph' || !selectedUserId) {
        return;
      }
      if (homegraphDepthReloadTimer) {
        window.clearTimeout(homegraphDepthReloadTimer);
      }
      homegraphDepthReloadTimer = window.setTimeout(() => {
        homegraphDepthReloadTimer = null;
        loadGraph();
      }, 120);
    }

    function renderGraphNodeLabels() {
      const layer = document.getElementById('graph-label-layer');
      if (!layer) {
        return;
      }
      const nodes = (displayedGraphData && Array.isArray(displayedGraphData.nodes)) ? displayedGraphData.nodes : [];
      layer.innerHTML = nodes.map((node) => {
        const label = escapeHtml(String(node.label || '').trim());
        if (!label) {
          return '';
        }
        return `<div class="graph-node-label" data-node-id="${escapeHtml(String(node.id || ''))}" style="display:none;">${label}</div>`;
      }).join('');
    }

    function updateGraphNodeLabelPositions() {
      if (!graphInstance) {
        return;
      }
      const layer = document.getElementById('graph-label-layer');
      const stage = document.getElementById('graph-stage');
      if (!layer || !stage || typeof graphInstance.graph2ScreenCoords !== 'function') {
        return;
      }
      const width = stage.clientWidth || 0;
      const height = stage.clientHeight || 0;
      if (!width || !height) {
        return;
      }
      const graphData = graphInstance && typeof graphInstance.graphData === 'function'
        ? graphInstance.graphData()
        : displayedGraphData;
      const nodes = (graphData && Array.isArray(graphData.nodes)) ? graphData.nodes : [];
      const labels = layer.querySelectorAll('.graph-node-label');
      for (const labelNode of labels) {
        const nodeId = labelNode.getAttribute('data-node-id') || '';
        const node = nodes.find((item) => String(item.id || '') === nodeId);
        if (!node || typeof node.x !== 'number' || typeof node.y !== 'number' || typeof node.z !== 'number') {
          labelNode.style.display = 'none';
          continue;
        }
        const projected = graphInstance.graph2ScreenCoords(node.x, node.y, node.z);
        if (!projected || !Number.isFinite(projected.x) || !Number.isFinite(projected.y)) {
          labelNode.style.display = 'none';
          continue;
        }
        const x = projected.x;
        const y = projected.y - getNodeVisualSize(node) - 8;
        const outOfBounds = x < -48 || y < -32 || x > width + 48 || y > height + 32;
        if (outOfBounds) {
          labelNode.style.display = 'none';
          continue;
        }
        labelNode.style.left = `${x}px`;
        labelNode.style.top = `${y}px`;
        labelNode.style.display = 'block';
      }
    }

    function syncGraphViewport() {
      if (!graphInstance) {
        return;
      }
      const stage = document.getElementById('graph-stage');
      if (!stage) {
        return;
      }
      const width = Math.max(320, Math.floor(stage.clientWidth || 0));
      const height = Math.max(320, Math.floor(stage.clientHeight || 0));
      graphInstance.width(width);
      graphInstance.height(height);
      updateGraphNodeLabelPositions();
    }

    function ensureGraphInstance() {
      if (graphInstance) {
        syncGraphViewport();
        return graphInstance;
      }
      const stage = document.getElementById('graph-stage');
      graphInstance = ForceGraph3D()(stage)
        .backgroundColor('#07111d')
        .nodeLabel((node) => `${node.label}`)
        .nodeAutoColorBy(null)
        .enableNodeDrag(true)
        .nodeColor((node) => node.color || '#8ecae6')
        .nodeVal((node) => getNodeVisualSize(node))
        .linkColor((link) => link.color || '#94a3b8')
        .linkOpacity(0.75)
        .linkWidth((link) => link.kind === 'corrects' ? 2.5 : 1.2)
        .onEngineTick(() => {
          updateGraphNodeLabelPositions();
        })
        .onEngineStop(() => {
          updateGraphNodeLabelPositions();
        })
        .onNodeClick(async (node) => {
          if (graphKind === 'homegraph') {
            const targetUser = resolveHomegraphViewerUser(node);
            if (targetUser && normalizeToken(targetUser.user_id) !== normalizeToken(selectedUserId)) {
              homegraphCenterNodeId = '';
              homegraphRootNodeId = '';
              setError('');
              setGraphStatus(`Chargement du Homegraph de ${targetUser.viewer || targetUser.user_id}...`);
              renderGraphDetails(node);
              await loadRecent(targetUser.user_id, targetUser.viewer || targetUser.user_id);
              return;
            }
            if (node.id === homegraphRootNodeId) {
              homegraphCenterNodeId = '';
              setError('');
              renderGraphDetails(node);
              await loadGraph();
              return;
            }
            homegraphCenterNodeId = node.id || '';
            if (!homegraphCenterNodeId.startsWith('viewer:')) {
              homegraphMaxDepth = '1';
              syncHomegraphDepthControls();
            }
            setError('');
            setGraphStatus(`Chargement du sous-graphe centré sur ${homegraphCenterNodeId} (${getHomegraphRequestMode() || 'homegraph'})...`);
            renderGraphDetails(node);
            await loadGraph();
            return;
          }
          focusedNodeId = node.id === focusedNodeId ? null : node.id;
          renderGraphDetails(node.id === focusedNodeId ? null : node);
          applyGraphFocus();
          if (focusedNodeId) {
            focusCameraOnNode(node);
          }
        })
        .onBackgroundClick(() => {
          if (graphKind === 'homegraph') {
            return;
          }
          focusedNodeId = null;
          renderGraphDetails(null);
          applyGraphFocus();
        });
      syncGraphViewport();
      if (typeof ResizeObserver !== 'undefined' && !graphResizeObserver) {
        graphResizeObserver = new ResizeObserver(() => {
          syncGraphViewport();
        });
        graphResizeObserver.observe(stage);
      } else if (!graphResizeObserver) {
        window.addEventListener('resize', syncGraphViewport);
        graphResizeObserver = { disconnect() {} };
      }
      const controls = graphInstance.controls ? graphInstance.controls() : null;
      if (controls && typeof controls.addEventListener === 'function') {
        controls.addEventListener('change', updateGraphNodeLabelPositions);
      }
      applyGraphMouseConfig();
      return graphInstance;
    }

    function applyGraphFocus() {
      const graph = ensureGraphInstance();
      const data = getFocusedGraphData(fullGraphData, focusedNodeId);
      displayedGraphData = data;
      renderGraphNodeLabels();
      graph.graphData(data);
      applyGraphMouseConfig();
      updateGraphNodeLabelPositions();
      resetGraphInteractionState();
    }

    async function loadGraph() {
      try {
        const viewer = selectedViewerLabel || '';
        const userId = selectedUserId || '';
        const query = new URLSearchParams({
          kind: graphKind,
          viewer,
          user_id: userId,
        });
        if (graphKind === 'homegraph') {
          query.set('include_uncertain', String(homegraphIncludeUncertain));
          if (homegraphMinWeight !== '') {
            query.set('min_weight', String(homegraphMinWeight));
          }
          if (homegraphMaxLinks !== '') {
            query.set('max_links', String(homegraphMaxLinks));
          }
          if (homegraphMaxDepth !== '') {
            query.set('max_depth', String(homegraphMaxDepth));
          }
          if (homegraphMaxNodes !== '') {
            query.set('max_nodes', String(homegraphMaxNodes));
          }
          if (homegraphCenterNodeId !== '') {
            query.set('center_node_id', homegraphCenterNodeId);
            const requestMode = getHomegraphRequestMode();
            if (requestMode) {
              query.set('mode', requestMode);
            }
          }
        }
        const response = await fetch(`/api/graph?${query.toString()}`);
        const data = await response.json();
        if (!data.ok) {
          setError(data.error || 'Impossible de charger le graphe.');
          return;
        }
        setError('');
        focusedNodeId = null;
        const previousSignature = lastGraphSignature;
        fullGraphData = {
          nodes: data.nodes || [],
          links: data.links || [],
        };
        lastGraphSignature = computeGraphSignature(fullGraphData);
        if (graphKind === 'homegraph') {
          homegraphRootNodeId = (data.meta && data.meta.root_node_id) ? data.meta.root_node_id : '';
        }
        updateSelectionState();
        let graphStatus =
          `${data.kind} | ${data.stats.node_count} nœud(s) | ${data.stats.link_count} lien(s)` +
          (data.viewer_filter ? ` | filtre: ${data.viewer_filter}` : '') +
          (graphKind === 'homegraph' && data.meta && data.meta.center_node_id ? ` | centre: ${data.meta.center_node_id}` : '') +
          (graphKind === 'homegraph' && homegraphCenterNodeId ? ` | mode: ${getHomegraphRequestMode() || 'viewer'}` : '') +
          (graphKind === 'homegraph' && data.meta && data.meta.truncated ? ' | tronqué' : '');
        if (graphKind === 'homegraph' && previousSignature && previousSignature === lastGraphSignature) {
          graphStatus += ' | sous-graphe inchangé';
        }
        setGraphStatus(graphStatus);
        applyGraphFocus();
        resetGraphInteractionState();
        if (graphKind === 'homegraph' && homegraphCenterNodeId) {
          const centerNode = findNodeById(fullGraphData, homegraphCenterNodeId);
          renderGraphDetails(centerNode);
        } else {
          renderGraphDetails(null);
        }
      } catch (error) {
        setError(`graph_load_failed: ${error}`);
        setGraphStatus('Chargement du graphe impossible.');
      }
    }

    async function loadRecent(userId, viewerLabel = userId) {
      if (!canOpenViewer(userId, viewerLabel)) {
        return;
      }
      const viewerChanged = selectedUserId !== userId;
      selectedUserId = userId;
      selectedViewerLabel = viewerLabel;
      homegraphCenterNodeId = '';
      homegraphRootNodeId = '';
      if (viewerChanged) {
        resetReviewPanel(`Aucune analyse lancée pour ${viewerLabel}.`);
      }
      updateSelectionState();
      await loadUsers();
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/recent`);
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Erreur lors du chargement des souvenirs récents.');
        document.getElementById('recent').textContent = 'Impossible de charger les souvenirs.';
        return;
      }
      setError('');
      const recentNode = document.getElementById('recent');
      if (!data.results || data.results.length === 0) {
        recentNode.innerHTML = '<div class="muted">Aucun souvenir récent pour ce viewer.</div>';
        return;
      }
      recentNode.innerHTML = data.results.map((item) => `
        <div class="memory-card">
          <pre>${escapeHtml(item.memory || '')}</pre>
          <div class="memory-meta">
            id: ${escapeHtml(item.id || '')}<br />
            created_at: ${escapeHtml(item.created_at || '')}<br />
            score: ${escapeHtml(item.score ?? '')}
          </div>
        </div>
      `).join('');
      await loadGraph();
    }

    async function openEditor(userId, viewerLabel = userId) {
      if (!canOpenViewer(userId, viewerLabel)) {
        return;
      }
      adminMode = 'steward';
      editingUserId = userId;
      editingViewerLabel = viewerLabel;
      selectedUserId = userId;
      selectedViewerLabel = viewerLabel;
      updateSelectionState();
      await loadUsers();
      const editorNode = document.getElementById('editor');
      editorNode.innerHTML = '<div class="muted">Chargement de toute la mémoire…</div>';
      const recentNode = document.getElementById('recent');
      recentNode.innerHTML = '<div class="muted">Chargement des souvenirs récents…</div>';
      await loadGraph();
      const recentResponse = await fetch(`/api/users/${encodeURIComponent(userId)}/recent`);
      const recentData = await recentResponse.json();
      if (!recentData.ok) {
        setError(recentData.error || 'Erreur lors du chargement des souvenirs récents.');
        recentNode.innerHTML = '<div class="muted">Impossible de charger les souvenirs.</div>';
      } else if (!recentData.results || recentData.results.length === 0) {
        recentNode.innerHTML = '<div class="muted">Aucun souvenir récent pour ce viewer.</div>';
      } else {
        recentNode.innerHTML = recentData.results.map((item) => `
          <div class="memory-card">
            <pre>${escapeHtml(item.memory || '')}</pre>
            <div class="memory-meta">
              id: ${escapeHtml(item.id || '')}<br />
              created_at: ${escapeHtml(item.created_at || '')}<br />
              score: ${escapeHtml(item.score ?? '')}
            </div>
          </div>
        `).join('');
      }
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/all-memories`);
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Erreur lors du chargement complet de la mémoire.');
        editorNode.innerHTML = '<div class="muted">Impossible de charger la mémoire complète.</div>';
        return;
      }
      setError('');
      renderEditorMemories(data.results || []);
    }

    function renderMemoryAddForm() {
      if (!editingUserId) {
        return '';
      }
      return `
        <div class="memory-form" id="memory-add-form" data-user-id="${escapeHtml(editingUserId)}" data-viewer-label="${escapeHtml(editingViewerLabel || editingUserId)}">
          <strong>Ajouter un souvenir</strong>
          <div class="muted" style="margin-top:6px;">Ajout manuel pour ${escapeHtml(editingViewerLabel || editingUserId)}.</div>
          <div class="muted" style="margin-top:4px;">Cible: ${escapeHtml(editingUserId)}</div>
          <div style="margin-top:10px;">
            <textarea id="memory-add-text" placeholder="Ex: joue souvent à Satisfactory et aime optimiser ses usines."></textarea>
          </div>
          <div class="memory-form-row">
            <label>
              Catégorie
              <select id="memory-add-category">
                <option value="general">Général</option>
                <option value="game">Jeu</option>
                <option value="topic">Sujet</option>
                <option value="social">Social</option>
                <option value="preference">Préférence</option>
                <option value="running_gag">Running gag</option>
                <option value="stream_mode">Mode de jeu</option>
              </select>
            </label>
            <label>
              Confiance
              <select id="memory-add-confidence">
                <option value="medium" selected>Moyenne</option>
                <option value="high">Haute</option>
                <option value="low">Basse</option>
              </select>
            </label>
            <label>
              Portée
              <select id="memory-add-scope">
                <option value="durable" selected>Durable</option>
                <option value="session">Session</option>
                <option value="ephemeral">Éphémère</option>
              </select>
            </label>
          </div>
          <div class="actions">
            <button type="button" onclick="addManualMemory()">Ajouter</button>
          </div>
        </div>
      `;
    }

    function renderEditorMemories(results) {
      const editorNode = document.getElementById('editor');
      const formHtml = renderMemoryAddForm();
      if (!results || results.length === 0) {
        editorNode.innerHTML = `${formHtml}<div class="muted">Aucun souvenir pour ce viewer.</div>`;
        return;
      }
      editorNode.innerHTML = `
        ${formHtml}
        <div class="scroll-box">
          ${results.map((item) => `
            <div class="memory-card">
              <pre>${escapeHtml(item.memory || '')}</pre>
              <div class="memory-meta">
                user_id: ${escapeHtml(item.user_id || editingUserId || '')}<br />
                id: ${escapeHtml(item.id || '')}<br />
                created_at: ${escapeHtml(item.created_at || '')}
                ${item.metadata && Object.keys(item.metadata).length ? `<br />metadata: ${escapeHtml(JSON.stringify(item.metadata))}` : ''}
              </div>
              <div class="actions">
                <button type="button" onclick='deleteSingleMemory(${JSON.stringify(String(item.id || ""))}, ${JSON.stringify(String(item.user_id || editingUserId || ""))}, ${JSON.stringify(String(editingViewerLabel || editingUserId || ""))})'>Supprimer</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    async function addManualMemory() {
      const formNode = document.getElementById('memory-add-form');
      const targetUserId = formNode ? String(formNode.dataset.userId || '').trim() : '';
      const targetViewerLabel = formNode ? String(formNode.dataset.viewerLabel || '').trim() : '';
      if (!targetUserId) {
        return;
      }
      const textNode = document.getElementById('memory-add-text');
      const categoryNode = document.getElementById('memory-add-category');
      const confidenceNode = document.getElementById('memory-add-confidence');
      const scopeNode = document.getElementById('memory-add-scope');
      const text = (textNode && textNode.value ? textNode.value : '').trim();
      if (!text) {
        setError('Le texte du souvenir est vide.');
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(targetUserId)}/remember`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          metadata: {
            source: 'admin_ui_manual',
            manual_target_user_id: targetUserId,
            manual_target_viewer: targetViewerLabel || targetUserId,
            category: categoryNode ? categoryNode.value : 'general',
            confidence: confidenceNode ? confidenceNode.value : 'medium',
            scope: scopeNode ? scopeNode.value : 'durable',
          },
        }),
      });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de l’ajout du souvenir.');
        return;
      }
      if (textNode) {
        textNode.value = '';
      }
      await openEditor(targetUserId, targetViewerLabel || targetUserId);
    }

    async function deleteSingleMemory(memoryId, userId, viewerLabel = userId) {
      if (!memoryId || !userId) {
        return;
      }
      const confirmed = window.confirm(`Supprimer le souvenir ${memoryId} pour ${viewerLabel || userId} ?`);
      if (!confirmed) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/memories/${encodeURIComponent(memoryId)}/delete`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de la suppression du souvenir.');
        return;
      }
      await openEditor(userId, viewerLabel || userId);
    }

    function triggerJsonDownload(payload, filename) {
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    }

    async function purgeUser(userId, viewerLabel = userId) {
      if (!userId) {
        return;
      }
      const confirmed = window.confirm(`Purger toute la mémoire de ${viewerLabel || userId} ?`);
      if (!confirmed) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/purge`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de la purge.');
        return;
      }
      if (selectedUserId === userId) {
        document.getElementById('recent').innerHTML =
          `<div class="muted">Purge effectuée : ${escapeHtml(data.deleted_count ?? 0)} souvenir(s) supprimé(s).</div>`;
      }
      if (editingUserId === userId) {
        editingUserId = null;
        editingViewerLabel = null;
        document.getElementById('editor').innerHTML = '<div class="muted">La mémoire complète a été purgée.</div>';
        updateSelectionState();
      }
      await loadUsers();
      await loadGraph();
    }

    async function exportUser(userId, viewerLabel = userId) {
      if (!userId) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/export`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de l’export.');
        return;
      }

      const safeViewer = (viewerLabel || 'viewer').replaceAll(/[^a-zA-Z0-9_-]/g, '_');
      triggerJsonDownload(data, `${safeViewer}_mem0_export.json`);
    }

    async function exportUserForReview(userId, viewerLabel = userId) {
      if (!userId) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/export-review`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de l’export review.');
        return;
      }

      const safeViewer = (viewerLabel || 'viewer').replaceAll(/[^a-zA-Z0-9_-]/g, '_');
      triggerJsonDownload(data.review_export, `${safeViewer}_mem0_review_export.json`);
    }

    async function analyzeSelectedUser() {
      if (!selectedUserId || isAnalysisPending()) {
        return;
      }
      const analysisUserId = selectedUserId;
      const analysisViewerLabel = selectedViewerLabel || selectedUserId;
      setError('');
      setAnalysisInFlight(analysisUserId, analysisViewerLabel);
      updateSelectionState();
      document.getElementById('review').innerHTML = `
        <div class="memory-card">
          <strong>Analyse GPT en cours</strong>
          <pre>Viewer: ${escapeHtml(analysisViewerLabel)}</pre>
          <div class="muted">La navigation vers un autre viewer est temporairement verrouillée jusqu’au résultat.</div>
        </div>
      `;
      try {
        const response = await fetch(
          `/api/users/${encodeURIComponent(analysisUserId)}/analyze?severity=${encodeURIComponent(reviewSeverity)}`,
          { method: 'POST' }
        );
        const data = await response.json();
        if (!data.ok) {
          setError(data.error || 'Échec de l’analyse GPT.');
          document.getElementById('review').innerHTML = '<div class="muted">Analyse indisponible.</div>';
          return;
        }

        const proposals = data.analysis.proposals || [];
        const summary = data.analysis.summary || '';
        const counts = { keep: 0, delete: 0, rewrite: 0, review: 0 };
        for (const item of proposals) {
          if (Object.prototype.hasOwnProperty.call(counts, item.action)) {
            counts[item.action] += 1;
          }
        }
        if (proposals.length === 0) {
          document.getElementById('review').innerHTML = `<div class="muted">${escapeHtml(summary || 'Aucune proposition.')}</div>`;
          return;
        }

        window.proposalDecisions = {};
        document.getElementById('review').innerHTML =
          renderCommitToolbar() +
          `<div class="memory-card"><strong>Répartition</strong><pre>keep: ${counts.keep} | rewrite: ${counts.rewrite} | review: ${counts.review} | delete: ${counts.delete}</pre></div>` +
          `<div class="memory-card"><strong>Résumé</strong><pre>${escapeHtml(summary)}</pre></div>` +
          proposals.map((item, index) => `
            <div class="memory-card" id="proposal-${index}">
              <div><strong>${escapeHtml(item.memory_id || '')}</strong></div>
              <div class="memory-meta">action: ${escapeHtml(item.action || '')}</div>
              <pre>${escapeHtml(item.reason || '')}</pre>
              ${item.proposed_text ? `<div class="memory-meta">proposed_text</div><pre>${escapeHtml(item.proposed_text)}</pre>` : ''}
              <div class="actions">
                <button id="proposal-accept-${index}" type="button" onclick="acceptProposal(${index})">Valider</button>
                <button id="proposal-reject-${index}" type="button" onclick="rejectProposal(${index})">Refuser</button>
              </div>
            </div>
          `).join('') +
          renderCommitToolbar();
        window.currentAnalysis = data.analysis;
      } finally {
        clearAnalysisInFlight(analysisUserId);
        updateSelectionState();
      }
    }

    function acceptProposal(index) {
      window.proposalDecisions[index] = 'accepted';
      updateProposalCardState(index);
      rerenderCommitButtons();
    }

    function rejectProposal(index) {
      window.proposalDecisions[index] = 'rejected';
      updateProposalCardState(index);
      rerenderCommitButtons();
    }

    function rerenderCommitButtons() {
      const acceptedCount = Object.values(window.proposalDecisions).filter((v) => v === 'accepted').length;
      const reviewNode = document.getElementById('review');
      const buttons = reviewNode.querySelectorAll('.commit-button');
      for (const button of buttons) {
        button.disabled = acceptedCount === 0;
      }
      const labels = reviewNode.querySelectorAll('.commit-count');
      for (const label of labels) {
        label.textContent = `Propositions acceptées: ${acceptedCount}`;
      }
    }

    async function commitAcceptedProposals() {
      if (!selectedUserId || !window.currentAnalysis || !window.currentAnalysis.proposals) {
        return;
      }
      const proposals = window.currentAnalysis.proposals.filter((_, index) => window.proposalDecisions[index] === 'accepted');
      if (proposals.length === 0) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(selectedUserId)}/commit-proposals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposals }),
      });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec du commit.');
        return;
      }
      resetReviewPanel(`Commit terminé : ${data.result.applied_count} proposition(s) appliquée(s).`);
      await loadRecent(selectedUserId, selectedViewerLabel || selectedUserId);
    }

    async function refreshAll() {
      await loadStatus();
      await loadUsers();
      if (selectedUserId) {
        await loadRecent(selectedUserId, selectedViewerLabel || selectedUserId);
      } else {
        await loadGraph();
      }
    }

    async function init() {
      document.getElementById('mode-global-button').onclick = () => {
        adminMode = 'global';
        updateModeState();
      };
      document.getElementById('mode-steward-button').onclick = () => {
        adminMode = 'steward';
        updateModeState();
      };
      document.getElementById('refresh-button').onclick = refreshAll;
      document.getElementById('analyze-button').onclick = analyzeSelectedUser;
      document.getElementById('verbose-button').onclick = toggleVerbose;
      document.getElementById('graph-refresh-button').onclick = loadGraph;
      document.getElementById('graph-reset-button').onclick = () => {
        if (graphKind === 'homegraph') {
          homegraphCenterNodeId = '';
          loadGraph();
          return;
        }
        focusedNodeId = null;
        renderGraphDetails(null);
        applyGraphFocus();
      };
      document.getElementById('graph-kind-select').onchange = (event) => {
        graphKind = event.target.value;
        updateSelectionState();
      };
      document.getElementById('homegraph-uncertain-select').onchange = (event) => {
        homegraphIncludeUncertain = event.target.value !== 'false';
      };
      document.getElementById('homegraph-min-weight-input').onchange = (event) => {
        homegraphMinWeight = event.target.value.trim();
      };
      document.getElementById('homegraph-max-links-input').onchange = (event) => {
        homegraphMaxLinks = event.target.value.trim();
      };
      document.getElementById('homegraph-max-depth-input').onchange = (event) => {
        homegraphMaxDepth = event.target.value.trim() || '1';
        syncHomegraphDepthControls();
        scheduleHomegraphReload();
      };
      document.getElementById('homegraph-depth-slider').oninput = (event) => {
        homegraphMaxDepth = event.target.value.trim() || '1';
        syncHomegraphDepthControls();
        scheduleHomegraphReload();
      };
      document.getElementById('homegraph-max-nodes-input').onchange = (event) => {
        homegraphMaxNodes = event.target.value.trim();
      };
      document.getElementById('severity-select').onchange = (event) => {
        reviewSeverity = event.target.value;
      };
      syncHomegraphDepthControls();
      resetReviewPanel();
      updateSelectionState();
      await refreshAll();
    }
    init();
  </script>
</body>
</html>
"""


class AdminUiServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], request_handler_class, config: AppConfig):
        super().__init__(server_address, request_handler_class)
        self.config = config
        self.tunnel = AdminTunnelManager(config)
        self.review_verbose = False


class AdminUiHandler(BaseHTTPRequestHandler):
    server: AdminUiServer

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/favicon.ico":
            self._send_no_content()
            return

        if route == "/":
            self._send_html(HTML_PAGE)
            return

        if route == "/api/status":
            tunnel_status = self.server.tunnel.status()
            try:
                admin_ok = admin_healthcheck(self.server.config)
            except Exception:
                admin_ok = False
            self._send_json(
                {
                    "ok": True,
                    "tunnel": {
                        "running": tunnel_status.running,
                        "local_port_open": tunnel_status.local_port_open,
                        "pid": tunnel_status.pid,
                    },
                    "admin_api_ok": admin_ok,
                    "review_verbose": self.server.review_verbose,
                }
            )
            return

        if route == "/api/users":
            try:
                users = list_admin_users(self.server.config)
                self._send_json(
                    {
                        "ok": True,
                        "users": [
                            {"user_id": user.user_id, "channel": user.channel, "viewer": user.viewer}
                            for user in users
                        ],
                    }
                )
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route == "/api/graph":
            kind = (query.get("kind", ["conversation"])[0] or "conversation").strip().lower()
            viewer = (query.get("viewer", [""])[0] or "").strip()
            user_id = (query.get("user_id", [""])[0] or "").strip()
            include_uncertain_param = (query.get("include_uncertain", [""])[0] or "").strip().lower()
            include_uncertain = None
            if include_uncertain_param in {"true", "false"}:
                include_uncertain = include_uncertain_param == "true"
            min_weight_param = (query.get("min_weight", [""])[0] or "").strip()
            max_links_param = (query.get("max_links", [""])[0] or "").strip()
            max_depth_param = (query.get("max_depth", [""])[0] or "").strip()
            max_nodes_param = (query.get("max_nodes", [""])[0] or "").strip()
            center_node_id = (query.get("center_node_id", [""])[0] or "").strip()
            graph_mode = (query.get("mode", [""])[0] or "").strip()
            try:
                if kind == "homegraph":
                    if center_node_id:
                        payload = build_homegraph_payload(
                            get_homegraph_multihop_graph(
                                self.server.config,
                                center_node_id,
                                mode=graph_mode or None,
                                include_uncertain=include_uncertain,
                                min_weight=float(min_weight_param) if min_weight_param else None,
                                max_links=int(max_links_param) if max_links_param else None,
                                max_depth=int(max_depth_param) if max_depth_param else None,
                                max_nodes=int(max_nodes_param) if max_nodes_param else None,
                            ),
                            viewer_filter=viewer,
                        )
                    elif not user_id:
                        self._send_json(
                            {
                                "ok": True,
                                "kind": "homegraph",
                                "viewer_filter": viewer,
                                "nodes": [],
                                "links": [],
                                "stats": {"node_count": 0, "link_count": 0},
                                "meta": {"note": "viewer_required"},
                            }
                        )
                        return
                    else:
                        payload = build_homegraph_payload(
                            get_homegraph_user_graph(
                                self.server.config,
                                user_id,
                                include_uncertain=include_uncertain,
                                min_weight=float(min_weight_param) if min_weight_param else None,
                                max_links=int(max_links_param) if max_links_param else None,
                            ),
                            viewer_filter=viewer,
                        )
                elif kind == "facts":
                    payload = build_facts_graph_payload(
                        load_facts_memory(_graph_data_path("facts_memory.json")),
                        viewer_filter=viewer,
                    )
                else:
                    payload = build_conversation_graph_payload(
                        load_conversation_graph(_graph_data_path("conversation_graph.json")),
                        viewer_filter=viewer,
                    )
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"ok": False, "error": f"graph_build_failed: {exc}"}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/recent"):
            user_id = unquote(route[len("/api/users/") : -len("/recent")].strip("/"))
            try:
                results = get_recent_memories(self.server.config, user_id)
                self._send_json({"ok": True, "results": results})
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/all-memories"):
            user_id = unquote(route[len("/api/users/") : -len("/all-memories")].strip("/"))
            try:
                payload = export_user_memories(self.server.config, user_id)
                export_root = payload.get("export", payload)
                self._send_json(
                    {
                        "ok": True,
                        "count": export_root.get("count", 0),
                        "results": list(export_root.get("records", [])),
                    }
                )
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        route, _, query_string = self.path.partition("?")

        if route.startswith("/api/users/") and "/memories/" in route and route.endswith("/delete"):
            remainder = route[len("/api/users/") : -len("/delete")].strip("/")
            user_part, _, memory_part = remainder.partition("/memories/")
            user_id = unquote(user_part.strip("/"))
            memory_id = unquote(memory_part.strip("/"))
            try:
                deleted = forget_user_memory(self.server.config, user_id, memory_id)
                self._send_json({"ok": True, "user_id": user_id, "memory_id": memory_id, "deleted": deleted})
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/export"):
            user_id = unquote(route[len("/api/users/") : -len("/export")].strip("/"))
            try:
                payload = export_user_memories(self.server.config, user_id)
                self._send_json({"ok": True, "export": payload})
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/export-review"):
            user_id = unquote(route[len("/api/users/") : -len("/export-review")].strip("/"))
            try:
                payload = export_user_memories(self.server.config, user_id)
                review_export = build_review_export(self.server.config, payload)
                self._send_json({"ok": True, "review_export": review_export})
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/analyze"):
            user_id = unquote(route[len("/api/users/") : -len("/analyze")].strip("/"))
            severity = "balanced"
            if query_string.startswith("severity="):
                severity = query_string.split("=", 1)[1].strip() or "balanced"
            try:
                if self.server.review_verbose:
                    print(f"[admin-ui] analyze start user_id={user_id}", flush=True)
                payload = export_user_memories(self.server.config, user_id)
                review_export = build_review_export(self.server.config, payload)
                if self.server.review_verbose:
                    print(
                        f"[admin-ui] review export ready viewer={review_export.get('viewer', '')} "
                        f"records={len(review_export.get('records', []))}",
                        flush=True,
                    )
                if not is_openai_review_enabled(self.server.config):
                    self._send_json(
                        {
                            "ok": False,
                            "error": "OpenAI review is not enabled or configuration is incomplete.",
                        },
                        status=HTTPStatus.BAD_GATEWAY,
                    )
                    return
                analysis = analyze_review_export(
                    self.server.config,
                    review_export,
                    severity=severity,
                    verbose=self.server.review_verbose,
                )
                if self.server.review_verbose:
                    print(f"[admin-ui] analyze done user_id={user_id}", flush=True)
                self._send_json({"ok": True, "review_export": review_export, "analysis": analysis})
            except (AdminApiError, OpenAIReviewError) as exc:
                if self.server.review_verbose:
                    print(f"[admin-ui] analyze failed user_id={user_id}: {exc}", flush=True)
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/commit-proposals"):
            user_id = unquote(route[len("/api/users/") : -len("/commit-proposals")].strip("/"))
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw_body.decode("utf-8"))
                proposals = payload.get("proposals", [])
                result = self._commit_review_proposals(user_id, proposals)
                self._send_json({"ok": True, "result": result})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": f"invalid proposal payload: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            except (AdminApiError, OpenAIReviewError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route == "/api/review-verbose":
            self.server.review_verbose = not self.server.review_verbose
            self._send_json({"ok": True, "enabled": self.server.review_verbose})
            return

        if route.startswith("/api/users/") and route.endswith("/purge"):
            user_id = unquote(route[len("/api/users/") : -len("/purge")].strip("/"))
            try:
                result = delete_user_memories(self.server.config, user_id)
                self._send_json(
                    {
                        "ok": result.ok,
                        "user_id": result.user_id,
                        "deleted_count": result.deleted_count,
                        "truncated": result.truncated,
                    }
                )
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        if route.startswith("/api/users/") and route.endswith("/remember"):
            user_id = unquote(route[len("/api/users/") : -len("/remember")].strip("/"))
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw_body.decode("utf-8"))
                text = str(payload.get("text", "")).strip()
                metadata = payload.get("metadata", {})
                created = remember_user_memory(self.server.config, user_id, text, metadata=metadata)
                self._send_json({"ok": True, "result": created})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": f"invalid remember payload: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            except AdminApiError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _apply_review_proposal(self, user_id: str, proposal: dict) -> dict:
        from admin_client import forget_user_memory, remember_user_memory

        memory_id = str(proposal.get("memory_id", "")).strip()
        action = str(proposal.get("action", "")).strip().lower()
        proposed_text = str(proposal.get("proposed_text", "")).strip()

        if not memory_id or action not in {"keep", "review", "delete", "rewrite"}:
            raise ValueError("unsupported proposal")

        if action in {"keep", "review"}:
            return {"action": action, "applied": False, "reason": "no backend mutation for this action"}

        if action == "delete":
            deleted = forget_user_memory(self.server.config, user_id, memory_id)
            return {"action": action, "deleted": bool(deleted)}

        export_payload = export_user_memories(self.server.config, user_id)
        export_root = export_payload.get("export", export_payload)
        record = None
        for item in export_root.get("records", []):
            if str(item.get("id", "")) == memory_id:
                record = item
                break

        metadata = dict(record.get("metadata", {})) if isinstance(record, dict) else {}
        created = remember_user_memory(self.server.config, user_id, proposed_text, metadata=metadata)
        deleted = forget_user_memory(self.server.config, user_id, memory_id)
        return {"action": action, "created": created, "deleted": bool(deleted)}

    def _commit_review_proposals(self, user_id: str, proposals: list[dict]) -> dict:
        results = []
        applied_count = 0
        for proposal in proposals:
            result = self._apply_review_proposal(user_id, proposal)
            results.append(result)
            if result.get("action") in {"delete", "rewrite"}:
                applied_count += 1
        return {"applied_count": applied_count, "results": results}

    def log_message(self, format: str, *args):
        return

    def _send_html(self, content: str):
        body = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _send_no_content(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()


def run_admin_ui(config: AppConfig | None = None, open_browser: bool = True) -> int:
    config = config or load_config()
    server = AdminUiServer((config.admin_ui_host, config.admin_ui_port), AdminUiHandler, config)
    server.tunnel.start()
    url = f"http://{config.admin_ui_host}:{config.admin_ui_port}"
    print(f"Admin UI locale : {url}")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.tunnel.stop()

    return 0
