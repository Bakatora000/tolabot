from __future__ import annotations

import json
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from admin_client import (
    AdminApiError,
    admin_healthcheck,
    delete_memory,
    delete_user_memories,
    export_user_memories,
    get_recent_memories,
    list_admin_users,
)
from admin_tunnel import AdminTunnelManager
from bot_config import AppConfig, load_config
from openai_review_client import OpenAIReviewError, analyze_review_export, build_review_export, is_openai_review_enabled


HTML_PAGE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>Mem0 Admin</title>
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
    pre { white-space: pre-wrap; word-break: break-word; background: #f7f7f7; padding: 12px; border-radius: 6px; margin: 0; }
    .memory-card { border: 1px solid #e1e1e1; border-radius: 6px; padding: 12px; margin: 10px 0; background: #fafafa; }
    .memory-meta { color: #666; font-size: 0.9rem; margin-top: 8px; }
    .actions { display: flex; gap: 8px; margin-top: 12px; }
    .proposal-accepted { border-color: #1f7a1f; background: #eef9ee; }
    .proposal-rejected { border-color: #a40000; background: #fdeeee; }
    .btn-accept-selected { background: #1f7a1f; color: white; border-color: #1f7a1f; }
    .btn-reject-selected { background: #a40000; color: white; border-color: #a40000; }
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
      <div style="display:flex; align-items:center; gap:12px; margin-top: 24px;">
        <h2 style="margin:0;">Review</h2>
        <button id="verbose-button" type="button">Verbose: OFF</button>
      </div>
      <div id="review" class="muted">Aucune analyse lancée.</div>
      <div id="error" class="error"></div>
    </div>
  </div>
  <script>
    let selectedUserId = null;
    let selectedViewerLabel = null;
    let verboseEnabled = false;
    let reviewSeverity = 'balanced';
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

    function updateSelectionState() {
      document.getElementById('selection').textContent = selectedViewerLabel
        ? `Viewer sélectionné : ${selectedViewerLabel}`
        : 'Aucun viewer sélectionné.';
      document.getElementById('export-button').disabled = !selectedUserId;
      document.getElementById('export-review-button').disabled = !selectedUserId;
      document.getElementById('analyze-button').disabled = !selectedUserId;
      document.getElementById('purge-button').disabled = !selectedUserId;
      document.getElementById('verbose-button').textContent = `Verbose: ${verboseEnabled ? 'ON' : 'OFF'}`;
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
      for (const user of data.users) {
        const item = document.createElement('li');
        const button = document.createElement('div');
        button.className = 'user-item';
        if (user.user_id === selectedUserId) {
          button.classList.add('active');
        }
        button.innerHTML = `<strong>${escapeHtml(user.viewer || user.user_id)}</strong><div class="muted">${escapeHtml(user.user_id)}</div>`;
        button.onclick = () => loadRecent(user.user_id, user.viewer || user.user_id);
        item.appendChild(button);
        usersNode.appendChild(item);
      }
    }

    async function loadRecent(userId, viewerLabel = userId) {
      const viewerChanged = selectedUserId !== userId;
      selectedUserId = userId;
      selectedViewerLabel = viewerLabel;
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
          <div class="actions">
            <button type="button" onclick="deleteSingleMemory('${escapeHtml(item.id || '')}')">Supprimer</button>
          </div>
        </div>
      `).join('');
    }

    async function deleteSingleMemory(memoryId) {
      if (!selectedUserId || !memoryId) {
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
      await loadRecent(selectedUserId, selectedViewerLabel || selectedUserId);
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
      await loadUsers();
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
      }
    }

    async function init() {
      document.getElementById('refresh-button').onclick = refreshAll;
      document.getElementById('export-button').onclick = exportSelectedUser;
      document.getElementById('export-review-button').onclick = exportSelectedUserForReview;
      document.getElementById('analyze-button').onclick = analyzeSelectedUser;
      document.getElementById('purge-button').onclick = purgeSelectedUser;
      document.getElementById('verbose-button').onclick = toggleVerbose;
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
        if self.path == "/":
            self._send_html(HTML_PAGE)
            return

        if self.path == "/api/status":
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

        if self.path == "/api/users":
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

        if self.path.startswith("/api/users/") and self.path.endswith("/recent"):
            user_id = unquote(self.path[len("/api/users/") : -len("/recent")].strip("/"))
            try:
                results = get_recent_memories(self.server.config, user_id)
                self._send_json({"ok": True, "results": results})
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
