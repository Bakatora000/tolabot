from __future__ import annotations

from fastapi import Header, HTTPException, status


def require_api_key(expected_key: str, provided_key: str | None) -> None:
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"ok": False, "error": "missing_api_key"},
        )
    if provided_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "error": "invalid_api_key"},
        )


def header_key_dependency(header_name: str, expected_key: str):
    def _dependency(provided_key: str | None = Header(default=None, alias=header_name)) -> None:
        require_api_key(expected_key, provided_key)

    return _dependency


def api_key_dependency(expected_key: str):
    return header_key_dependency("X-API-Key", expected_key)


def admin_key_dependency(expected_key: str):
    return header_key_dependency("X-Admin-Key", expected_key)
