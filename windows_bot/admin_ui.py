from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from admin_client import AdminApiError, admin_healthcheck, get_recent_memories, list_admin_users
from admin_tunnel import AdminTunnelManager
from bot_config import AppConfig, load_config


HTML_PAGE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>Mem0 Admin</title>
  <style>
    body { font-family: sans-serif; margin: 24px; max-width: 1100px; }
    .row { display: flex; gap: 24px; align-items: flex-start; }
    .panel { border: 1px solid #ccc; border-radius: 8px; padding: 16px; flex: 1; }
    ul { list-style: none; padding: 0; }
    li { margin: 8px 0; cursor: pointer; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f7f7f7; padding: 12px; border-radius: 6px; }
  </style>
</head>
<body>
  <h1>Mem0 Admin</h1>
  <div id="status">Chargement…</div>
  <div class="row">
    <div class="panel">
      <h2>Viewers</h2>
      <ul id="users"></ul>
    </div>
    <div class="panel">
      <h2>Recent</h2>
      <div id="recent">Sélectionne un viewer.</div>
    </div>
  </div>
  <script>
    async function loadStatus() {
      const response = await fetch('/api/status');
      const data = await response.json();
      document.getElementById('status').textContent =
        `Tunnel: ${data.tunnel.running ? 'OK' : 'OFF'} | Port local: ${data.tunnel.local_port_open ? 'OK' : 'OFF'} | Admin API: ${data.admin_api_ok ? 'OK' : 'KO'}`;
    }

    async function loadUsers() {
      const response = await fetch('/api/users');
      const data = await response.json();
      const usersNode = document.getElementById('users');
      usersNode.innerHTML = '';
      for (const user of data.users) {
        const item = document.createElement('li');
        item.textContent = `${user.viewer} (${user.user_id})`;
        item.onclick = () => loadRecent(user.user_id);
        usersNode.appendChild(item);
      }
    }

    async function loadRecent(userId) {
      const response = await fetch(`/api/users/${encodeURIComponent(userId)}/recent`);
      const data = await response.json();
      document.getElementById('recent').innerHTML = `<pre>${JSON.stringify(data.results, null, 2)}</pre>`;
    }

    async function init() {
      await loadStatus();
      await loadUsers();
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

    def log_message(self, format: str, *args):
        return

    def _send_html(self, content: str):
        body = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
