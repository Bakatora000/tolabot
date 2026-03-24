from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from bot_config import AppConfig


class AdminApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminUser:
    user_id: str
    channel: str
    viewer: str


@dataclass(frozen=True)
class DeleteUserResult:
    ok: bool
    user_id: str
    deleted_count: int
    truncated: bool


def build_admin_headers(config: AppConfig) -> dict[str, str]:
    return {
        "X-Admin-Key": config.admin_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def is_admin_ui_enabled(config: AppConfig) -> bool:
    return bool(config.admin_ui_enabled and config.admin_api_local_url and config.admin_api_key)


def _request(
    config: AppConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    if not is_admin_ui_enabled(config):
        raise AdminApiError("Admin UI not enabled or configuration incomplete.")

    url = f"{config.admin_api_local_url}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=build_admin_headers(config),
            json=payload,
            timeout=config.admin_api_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise AdminApiError(f"Admin API network error: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip() or None
        raise AdminApiError(f"Admin API HTTP {response.status_code}: {detail}")

    return response


def admin_healthcheck(config: AppConfig) -> bool:
    response = _request(config, "GET", "/admin/health")
    data = response.json()
    return bool(data.get("ok", True)) and data.get("status") == "ok"


def list_admin_users(config: AppConfig) -> list[AdminUser]:
    response = _request(config, "GET", "/admin/users")
    data = response.json()
    return [
        AdminUser(
            user_id=str(item.get("user_id", "")),
            channel=str(item.get("channel", "")),
            viewer=str(item.get("viewer", "")),
        )
        for item in data.get("users", [])
    ]


def get_recent_memories(config: AppConfig, user_id: str) -> list[dict[str, Any]]:
    response = _request(config, "GET", f"/admin/users/{user_id}/recent")
    data = response.json()
    return list(data.get("results", []))


def search_user_memories(config: AppConfig, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    response = _request(
        config,
        "POST",
        f"/admin/users/{user_id}/search",
        payload={"query": query, "limit": max(1, limit)},
    )
    data = response.json()
    return list(data.get("results", []))


def delete_user_memories(config: AppConfig, user_id: str) -> DeleteUserResult:
    response = _request(config, "DELETE", f"/admin/users/{user_id}")
    data = response.json()
    return DeleteUserResult(
        ok=bool(data.get("ok", False)),
        user_id=str(data.get("user_id", user_id)),
        deleted_count=int(data.get("deleted_count", 0)),
        truncated=bool(data.get("truncated", False)),
    )


def delete_memory(config: AppConfig, memory_id: str) -> bool:
    response = _request(config, "DELETE", f"/admin/memories/{memory_id}")
    data = response.json()
    return bool(data.get("deleted", True))


def export_user_memories(config: AppConfig, user_id: str) -> dict[str, Any]:
    response = _request(config, "POST", f"/admin/users/{user_id}/export")
    return response.json()


def import_user_memories(config: AppConfig, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = _request(config, "POST", f"/admin/users/{user_id}/import", payload=payload)
    return response.json()


def remember_user_memory(config: AppConfig, user_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    response = _request(
        config,
        "POST",
        f"/admin/users/{user_id}/remember",
        payload={"text": text, "metadata": metadata or {}},
    )
    return response.json()
