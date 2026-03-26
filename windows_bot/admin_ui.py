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
    delete_memory,
    delete_user_memories,
    export_user_memories,
    get_homegraph_multihop_graph,
    get_homegraph_user_graph,
    get_recent_memories,
    list_admin_users,
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
  <script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script>
  <script src="https://unpkg.com/3d-force-graph@1.76.2/dist/3d-force-graph.min.js"></script>
  <style>
    body { font-family: sans-serif; margin: 24px; max-width: 1280px; }
    .toolbar { display: flex; gap: 12px; align-items: center; margin: 16px 0 24px; }
    .row { display: flex; gap: 24px; align-items: flex-start; }
    .panel { border: 1px solid #ccc; border-radius: 8px; padding: 16px; flex: 1; }
    .panel-left { max-width: 360px; }
    .status-line { margin-bottom: 12px; font-weight: 600; }
    .muted { color: #666; }
    .error { color: #a40000; margin-top: 12px; }
    button { padding: 8px 12px; cursor: pointer; }
    button:disabled { cursor: default; opacity: 0.6; }
    ul { list-style: none; padding: 0; margin: 0; }
    li { margin: 8px 0; }
    .user-item { border: 1px solid #ddd; border-radius: 6px; padding: 10px 12px; cursor: pointer; }
    .user-item.active { border-color: #1d70b8; background: #eef6ff; }
    .user-item:hover { background: #f7f7f7; }
    .user-item-header { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
    .user-item-main { flex: 1; min-width: 0; }
    .edit-panel { margin-top: 24px; }
    .scroll-box { max-height: 420px; overflow-y: auto; padding-right: 6px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f7f7f7; padding: 12px; border-radius: 6px; margin: 0; }
    .memory-card { border: 1px solid #e1e1e1; border-radius: 6px; padding: 12px; margin: 10px 0; background: #fafafa; }
    .memory-meta { color: #666; font-size: 0.9rem; margin-top: 8px; }
    .actions { display: flex; gap: 8px; margin-top: 12px; }
    .proposal-accepted { border-color: #1f7a1f; background: #eef9ee; }
    .proposal-rejected { border-color: #a40000; background: #fdeeee; }
    .btn-accept-selected { background: #1f7a1f; color: white; border-color: #1f7a1f; }
    .btn-reject-selected { background: #a40000; color: white; border-color: #a40000; }
    .graph-toolbar { display:flex; gap:12px; align-items:center; margin: 12px 0; flex-wrap: wrap; }
    .graph-layout { display:flex; gap:16px; align-items: stretch; }
    .graph-stage { min-height: 520px; flex: 1; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background: radial-gradient(circle at top, #10223a 0%, #07111d 70%); }
    .graph-sidebar { width: 320px; border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fafafa; }
    .graph-sidebar pre { min-height: 180px; }
    .graph-caption { color:#666; font-size:0.95rem; }
  </style>
</head>
<body>
  <h1>Mem0 Admin</h1>
  <div id="status" class="status-line">Chargement…</div>
  <div class="toolbar">
    <button id="refresh-button" type="button">Rafraîchir</button>
    <button id="export-button" type="button" disabled>Exporter ce viewer</button>
    <button id="export-review-button" type="button" disabled>Exporter pour revue</button>
    <button id="analyze-button" type="button" disabled>Analyser avec GPT</button>
    <button id="purge-button" type="button" disabled>Purger ce viewer</button>
    <label for="severity-select">Sévérité</label>
    <select id="severity-select">
      <option value="conservative">Conservateur</option>
      <option value="balanced" selected>Équilibré</option>
      <option value="aggressive">Agressif</option>
    </select>
    <span id="selection" class="muted">Aucun viewer sélectionné.</span>
  </div>
  <div class="row">
    <div class="panel panel-left">
      <h2>Viewers</h2>
      <ul id="users"></ul>
    </div>
    <div class="panel">
      <h2>Recent</h2>
      <div id="recent">Sélectionne un viewer.</div>
      <div class="edit-panel">
        <div style="display:flex; align-items:center; gap:12px;">
          <h2 style="margin:0;">Édition</h2>
          <span id="editor-selection" class="muted">Aucun viewer ouvert en édition.</span>
        </div>
        <div id="editor" class="muted">Clique sur “Éditer” pour afficher toute la mémoire d’un viewer.</div>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-top: 24px;">
        <h2 style="margin:0;">Review</h2>
        <button id="verbose-button" type="button">Verbose: OFF</button>
      </div>
      <div id="review" class="muted">Aucune analyse lancée.</div>
      <div style="display:flex; align-items:center; gap:12px; margin-top: 24px;">
        <h2 style="margin:0;">Graph 3D</h2>
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
          <label for="homegraph-max-depth-input">Profondeur</label>
          <input id="homegraph-max-depth-input" type="number" min="1" step="1" value="2" style="width:72px;" />
          <label for="homegraph-max-nodes-input">Nœuds max</label>
          <input id="homegraph-max-nodes-input" type="number" min="1" step="1" value="20" style="width:72px;" />
        </span>
        <button id="graph-refresh-button" type="button">Charger</button>
        <button id="graph-reset-button" type="button">Réinitialiser le focus</button>
        <span id="graph-selection" class="muted">Vue globale.</span>
      </div>
      <div class="graph-layout">
        <div class="graph-stage" id="graph-stage"></div>
        <div class="graph-sidebar">
          <div class="graph-caption" id="graph-stats">Aucune donnée chargée.</div>
          <h3>Détails</h3>
          <pre id="graph-details">Clique sur un nœud pour isoler ses liens.</pre>
        </div>
      </div>
      <div id="error" class="error"></div>
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
    let homegraphMaxDepth = '2';
    let homegraphMaxNodes = '20';
    let homegraphCenterNodeId = '';
    let homegraphRootNodeId = '';
    let graphInstance = null;
    let fullGraphData = { nodes: [], links: [] };
    let lastGraphSignature = '';
    let focusedNodeId = null;
    window.currentAnalysis = null;
    window.proposalDecisions = {};

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

    function updateSelectionState() {
      document.getElementById('selection').textContent = selectedViewerLabel
        ? `Viewer sélectionné : ${selectedViewerLabel}`
        : 'Aucun viewer sélectionné.';
      document.getElementById('editor-selection').textContent = editingViewerLabel
        ? `Édition ouverte : ${editingViewerLabel}`
        : 'Aucun viewer ouvert en édition.';
      document.getElementById('export-button').disabled = !selectedUserId;
      document.getElementById('export-review-button').disabled = !selectedUserId;
      document.getElementById('analyze-button').disabled = !selectedUserId;
      document.getElementById('purge-button').disabled = !selectedUserId;
      document.getElementById('verbose-button').textContent = `Verbose: ${verboseEnabled ? 'ON' : 'OFF'}`;
      document.getElementById('graph-selection').textContent = selectedViewerLabel
        ? `Vue filtrée sur : ${selectedViewerLabel}`
        : 'Vue globale.';
      if (graphKind === 'homegraph' && homegraphCenterNodeId) {
        document.getElementById('graph-selection').textContent += ` | centre: ${homegraphCenterNodeId}`;
      }
      document.getElementById('homegraph-filter-group').style.display = graphKind === 'homegraph' ? 'contents' : 'none';
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
      usersNode.innerHTML = '';
      if (!data.ok) {
        usersNode.innerHTML = '<li class="muted">Impossible de charger les viewers.</li>';
        return;
      }
      if (!data.users || data.users.length === 0) {
        usersNode.innerHTML = '<li class="muted">Aucun viewer retourné par l\\'API admin.</li>';
        return;
      }
      knownUsers = Array.isArray(data.users) ? data.users : [];
      for (const user of data.users) {
        const item = document.createElement('li');
        const button = document.createElement('div');
        const viewerLabel = user.viewer || user.user_id;
        button.className = 'user-item';
        if (user.user_id === selectedUserId) {
          button.classList.add('active');
        }
        button.innerHTML = `
          <div class="user-item-header">
            <div class="user-item-main">
              <strong>${escapeHtml(viewerLabel)}</strong>
              <div class="muted">${escapeHtml(user.user_id)}</div>
            </div>
            <button type="button" class="edit-viewer-button">Éditer</button>
          </div>
        `;
        const editButton = button.querySelector('.edit-viewer-button');
        if (editButton) {
          editButton.onclick = (event) => {
            event.stopPropagation();
            openEditor(user.user_id, viewerLabel);
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

    function ensureGraphInstance() {
      if (graphInstance) {
        return graphInstance;
      }
      const stage = document.getElementById('graph-stage');
      graphInstance = ForceGraph3D()(stage)
        .backgroundColor('#07111d')
        .nodeLabel((node) => `${node.label} (${node.kind})`)
        .nodeAutoColorBy(null)
        .nodeColor((node) => node.color || '#8ecae6')
        .nodeVal((node) => {
          if (graphKind === 'homegraph' && homegraphCenterNodeId && node.id === homegraphCenterNodeId) {
            return 12;
          }
          return node.kind === 'turn' || node.kind === 'fact' ? 4 : 7;
        })
        .linkColor((link) => link.color || '#94a3b8')
        .linkOpacity(0.75)
        .linkWidth((link) => link.kind === 'corrects' ? 2.5 : 1.2)
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
            homegraphCenterNodeId = node.id || '';
            setError('');
            setGraphStatus(`Chargement du sous-graphe centré sur ${homegraphCenterNodeId}...`);
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
      return graphInstance;
    }

    function applyGraphFocus() {
      const graph = ensureGraphInstance();
      const data = getFocusedGraphData(fullGraphData, focusedNodeId);
      graph.graphData(data);
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
          (graphKind === 'homegraph' && data.meta && data.meta.truncated ? ' | tronqué' : '');
        if (graphKind === 'homegraph' && previousSignature && previousSignature === lastGraphSignature) {
          graphStatus += ' | sous-graphe inchangé';
        }
        setGraphStatus(graphStatus);
        applyGraphFocus();
        if (graphKind === 'homegraph' && homegraphCenterNodeId) {
          const centerNode = findNodeById(fullGraphData, homegraphCenterNodeId);
          renderGraphDetails(centerNode);
          focusCameraOnNode(centerNode);
        } else {
          renderGraphDetails(null);
        }
      } catch (error) {
        setError(`graph_load_failed: ${error}`);
        setGraphStatus('Chargement du graphe impossible.');
      }
    }

    async function loadRecent(userId, viewerLabel = userId) {
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
      editingUserId = userId;
      editingViewerLabel = viewerLabel;
      updateSelectionState();
      const editorNode = document.getElementById('editor');
      editorNode.innerHTML = '<div class="muted">Chargement de toute la mémoire…</div>';
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

    function renderEditorMemories(results) {
      const editorNode = document.getElementById('editor');
      if (!results || results.length === 0) {
        editorNode.innerHTML = '<div class="muted">Aucun souvenir pour ce viewer.</div>';
        return;
      }
      editorNode.innerHTML = `
        <div class="scroll-box">
          ${results.map((item) => `
            <div class="memory-card">
              <pre>${escapeHtml(item.memory || '')}</pre>
              <div class="memory-meta">
                id: ${escapeHtml(item.id || '')}<br />
                created_at: ${escapeHtml(item.created_at || '')}
              </div>
              <div class="actions">
                <button type="button" onclick="deleteSingleMemory('${escapeHtml(item.id || '')}')">Supprimer</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    async function deleteSingleMemory(memoryId) {
      if (!memoryId) {
        return;
      }
      const confirmed = window.confirm(`Supprimer le souvenir ${memoryId} ?`);
      if (!confirmed) {
        return;
      }
      setError('');
      const response = await fetch(`/api/memories/${encodeURIComponent(memoryId)}/delete`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de la suppression du souvenir.');
        return;
      }
      if (selectedUserId) {
        await loadRecent(selectedUserId, selectedViewerLabel || selectedUserId);
      }
      if (editingUserId) {
        await openEditor(editingUserId, editingViewerLabel || editingUserId);
      }
    }

    async function purgeSelectedUser() {
      if (!selectedUserId) {
        return;
      }
      const confirmed = window.confirm(`Purger toute la mémoire de ${selectedViewerLabel || selectedUserId} ?`);
      if (!confirmed) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(selectedUserId)}/purge`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de la purge.');
        return;
      }
      document.getElementById('recent').innerHTML =
        `<div class="muted">Purge effectuée : ${escapeHtml(data.deleted_count ?? 0)} souvenir(s) supprimé(s).</div>`;
      if (editingUserId === selectedUserId) {
        editingUserId = null;
        editingViewerLabel = null;
        document.getElementById('editor').innerHTML = '<div class="muted">La mémoire complète a été purgée.</div>';
        updateSelectionState();
      }
      await loadUsers();
      await loadGraph();
    }

    async function exportSelectedUser() {
      if (!selectedUserId) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(selectedUserId)}/export`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de l’export.');
        return;
      }

      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      const safeViewer = (selectedViewerLabel || 'viewer').replaceAll(/[^a-zA-Z0-9_-]/g, '_');
      link.href = url;
      link.download = `${safeViewer}_mem0_export.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    }

    async function exportSelectedUserForReview() {
      if (!selectedUserId) {
        return;
      }
      setError('');
      const response = await fetch(`/api/users/${encodeURIComponent(selectedUserId)}/export-review`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || 'Échec de l’export review.');
        return;
      }

      const blob = new Blob([JSON.stringify(data.review_export, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      const safeViewer = (selectedViewerLabel || 'viewer').replaceAll(/[^a-zA-Z0-9_-]/g, '_');
      link.href = url;
      link.download = `${safeViewer}_mem0_review_export.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    }

    async function analyzeSelectedUser() {
      if (!selectedUserId) {
        return;
      }
      setError('');
      document.getElementById('review').innerHTML = '<div class="muted">Analyse en cours…</div>';
      const response = await fetch(
        `/api/users/${encodeURIComponent(selectedUserId)}/analyze?severity=${encodeURIComponent(reviewSeverity)}`,
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
      document.getElementById('refresh-button').onclick = refreshAll;
      document.getElementById('export-button').onclick = exportSelectedUser;
      document.getElementById('export-review-button').onclick = exportSelectedUserForReview;
      document.getElementById('analyze-button').onclick = analyzeSelectedUser;
      document.getElementById('purge-button').onclick = purgeSelectedUser;
      document.getElementById('verbose-button').onclick = toggleVerbose;
      document.getElementById('graph-refresh-button').onclick = loadGraph;
      document.getElementById('graph-reset-button').onclick = () => {
        if (graphKind === 'homegraph' && homegraphCenterNodeId && homegraphCenterNodeId !== homegraphRootNodeId) {
          homegraphCenterNodeId = homegraphRootNodeId || '';
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
        homegraphMaxDepth = event.target.value.trim();
      };
      document.getElementById('homegraph-max-nodes-input').onchange = (event) => {
        homegraphMaxNodes = event.target.value.trim();
      };
      document.getElementById('severity-select').onchange = (event) => {
        reviewSeverity = event.target.value;
      };
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
            try:
                if kind == "homegraph":
                    if center_node_id:
                        payload = build_homegraph_payload(
                            get_homegraph_multihop_graph(
                                self.server.config,
                                center_node_id,
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

        if route.startswith("/api/memories/") and route.endswith("/delete"):
            memory_id = unquote(route[len("/api/memories/") : -len("/delete")].strip("/"))
            try:
                deleted = delete_memory(self.server.config, memory_id)
                self._send_json({"ok": True, "memory_id": memory_id, "deleted": deleted})
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

        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _apply_review_proposal(self, user_id: str, proposal: dict) -> dict:
        from admin_client import delete_memory, remember_user_memory

        memory_id = str(proposal.get("memory_id", "")).strip()
        action = str(proposal.get("action", "")).strip().lower()
        proposed_text = str(proposal.get("proposed_text", "")).strip()

        if not memory_id or action not in {"keep", "review", "delete", "rewrite"}:
            raise ValueError("unsupported proposal")

        if action in {"keep", "review"}:
            return {"action": action, "applied": False, "reason": "no backend mutation for this action"}

        if action == "delete":
            deleted = delete_memory(self.server.config, memory_id)
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
        deleted = delete_memory(self.server.config, memory_id)
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
