from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from bot_config import AppConfig
from homegraph_ids import resolve_homegraph_viewer_id


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


_LOCAL_MEMORY_BACKEND = None


def _is_local_homegraph_enabled(config: AppConfig) -> bool:
    return bool(config.homegraph_local_enabled and config.homegraph_db_path)


def _has_local_admin_capability(config: AppConfig) -> bool:
    return bool(config.mem0_local_backend_enabled or _is_local_homegraph_enabled(config))


def _homegraph_db_path(config: AppConfig) -> Path:
    return Path(config.homegraph_db_path).resolve()


def _resolve_homegraph_user_id(config: AppConfig, user_id: str) -> str:
    return resolve_homegraph_viewer_id(_homegraph_db_path(config), user_id)


def _load_local_homegraph_modules():
    from homegraph.context import build_viewer_context_payload
    from homegraph.graph import STABLE_NODE_KINDS, STABLE_LINK_KINDS, build_viewer_graph_payload
    from homegraph.merge_extraction import merge_payload
    from homegraph.multihop_graph import build_multihop_graph_payload
    from homegraph.schema import init_db

    return {
        "build_viewer_context_payload": build_viewer_context_payload,
        "build_viewer_graph_payload": build_viewer_graph_payload,
        "build_multihop_graph_payload": build_multihop_graph_payload,
        "merge_payload": merge_payload,
        "init_db": init_db,
        "stable_node_kinds": STABLE_NODE_KINDS,
        "stable_link_kinds": STABLE_LINK_KINDS,
    }


def _load_local_memory_backend():
    global _LOCAL_MEMORY_BACKEND
    if _LOCAL_MEMORY_BACKEND is None:
        from memory_service.backend import build_backend
        from memory_service.config import Settings

        _LOCAL_MEMORY_BACKEND = build_backend(Settings.load())
    return _LOCAL_MEMORY_BACKEND


def _parse_user_parts(user_id: str) -> tuple[str, str]:
    parts = user_id.split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[1], parts[3]
    return "", ""


def _is_test_user_id(user_id: str) -> bool:
    channel, viewer = _parse_user_parts(user_id)
    if channel.lower() == "integration":
        return True
    return viewer.lower().startswith("windows_linux_e2e_")


def _record_to_admin_memory_result(record) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "user_id": str(record.user_id),
        "memory": str(record.memory),
        "metadata": dict(record.metadata or {}),
        "created_at": str(record.created_at),
        "updated_at": str(record.updated_at),
        "score": float(record.score),
    }


def _build_local_homegraph_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        "facts": len(payload.get("facts", [])),
        "relations": len(payload.get("relations", [])),
        "links": len(payload.get("links", [])),
    }


def _validate_local_homegraph_payload(user_id: str, payload: dict[str, Any], stable_node_kinds: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if str(payload.get("viewer_id", "")).strip() != user_id:
        errors.append("Payload viewer_id must match the route user_id.")

    if not any(
        [
            str(payload.get("summary_short", "")).strip(),
            str(payload.get("summary_long", "")).strip(),
            payload.get("facts"),
            payload.get("relations"),
            payload.get("links"),
        ]
    ):
        errors.append("Payload contains no mergeable Homegraph content.")

    if not str(payload.get("model_name", "")).strip():
        warnings.append("model_name is missing; GPT provenance will be less traceable.")
    if not str(payload.get("source_ref", "")).strip():
        warnings.append("source_ref is missing; merge provenance will be less traceable.")

    seen_fact_keys: set[tuple[str, str]] = set()
    for fact in payload.get("facts", []):
        kind = str(fact.get("kind", "")).strip()
        value = str(fact.get("value", "")).strip()
        key = (kind.lower(), value.lower())
        if key in seen_fact_keys:
            warnings.append(f"Duplicate fact detected: {kind} / {value}")
        seen_fact_keys.add(key)
        if not fact.get("source_memory_ids"):
            warnings.append(f"Fact without source_memory_ids: {kind} / {value}")

    seen_relation_keys: set[tuple[str, str, str]] = set()
    for relation in payload.get("relations", []):
        target_type = str(relation.get("target_type", "")).strip()
        target_id_or_value = str(relation.get("target_id_or_value", "")).strip()
        relation_type = str(relation.get("relation_type", "")).strip()
        key = (target_type.lower(), target_id_or_value.lower(), relation_type.lower())
        if key in seen_relation_keys:
            warnings.append(f"Duplicate relation detected: {target_type} / {target_id_or_value} / {relation_type}")
        seen_relation_keys.add(key)
        if target_type and target_type not in stable_node_kinds:
            warnings.append(f"Relation target_type is not a stable Homegraph kind: {target_type}")
        if not relation.get("source_memory_ids"):
            warnings.append(f"Relation without source_memory_ids: {target_type} / {target_id_or_value} / {relation_type}")

    seen_link_keys: set[tuple[str, str, str]] = set()
    for link in payload.get("links", []):
        target_type = str(link.get("target_type", "")).strip()
        target_value = str(link.get("target_value") or link.get("target_id_or_value") or "").strip()
        relation_type = str(link.get("relation_type", "")).strip()
        key = (target_type.lower(), target_value.lower(), relation_type.lower())
        if key in seen_link_keys:
            warnings.append(f"Duplicate link detected: {target_type} / {target_value} / {relation_type}")
        seen_link_keys.add(key)
        if target_type and target_type not in stable_node_kinds:
            warnings.append(f"Link target_type is not a stable Homegraph kind: {target_type}")
        if not link.get("source_memory_ids"):
            warnings.append(f"Link without source_memory_ids: {target_type} / {target_value} / {relation_type}")

    return errors, warnings


def _build_local_homegraph_response(
    *,
    source: str,
    user_id: str,
    payload: dict[str, Any],
    db_path: Path,
) -> dict[str, Any]:
    modules = _load_local_homegraph_modules()
    context = modules["build_viewer_context_payload"](user_id, db_path)
    graph = modules["build_viewer_graph_payload"](user_id, db_path)
    return {
        "ok": True,
        "viewer_id": user_id,
        "source": source,
        "context": context.get("context", {}),
        "text_block": context.get("text_block", ""),
        "graph_stats": graph.get("stats", {}),
        "merged": _build_local_homegraph_counts(payload),
    }


def is_admin_ui_enabled(config: AppConfig) -> bool:
    return bool(config.admin_ui_enabled and _has_local_admin_capability(config))


def admin_healthcheck(config: AppConfig) -> bool:
    return _has_local_admin_capability(config)


def list_admin_users(config: AppConfig) -> list[AdminUser]:
    if _has_local_admin_capability(config):
        users: list[AdminUser] = []
        for user_id in _load_local_memory_backend().list_user_ids():
            if _is_test_user_id(user_id):
                continue
            channel, viewer = _parse_user_parts(user_id)
            users.append(
                AdminUser(
                    user_id=user_id,
                    channel=channel,
                    viewer=viewer,
                )
            )
        users.sort(key=lambda item: item.user_id)
        return users

    raise AdminApiError("Admin local SQLite indisponible.")


def get_recent_memories(config: AppConfig, user_id: str) -> list[dict[str, Any]]:
    if _has_local_admin_capability(config):
        return [
            _record_to_admin_memory_result(item)
            for item in _load_local_memory_backend().recent(user_id, 1000)
        ]

    raise AdminApiError("Admin local SQLite indisponible.")


def search_user_memories(config: AppConfig, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    if _has_local_admin_capability(config):
        return [
            _record_to_admin_memory_result(item)
            for item in _load_local_memory_backend().search(user_id, query, max(1, limit))
        ]

    raise AdminApiError("Admin local SQLite indisponible.")


def delete_user_memories(config: AppConfig, user_id: str) -> DeleteUserResult:
    if _has_local_admin_capability(config):
        deleted_count, truncated = _load_local_memory_backend().purge_user(user_id, 1000)
        return DeleteUserResult(
            ok=True,
            user_id=user_id,
            deleted_count=deleted_count,
            truncated=truncated,
        )

    raise AdminApiError("Admin local SQLite indisponible.")


def delete_memory(config: AppConfig, memory_id: str) -> bool:
    if _has_local_admin_capability(config):
        return bool(_load_local_memory_backend().delete_memory(memory_id))

    raise AdminApiError("Admin local SQLite indisponible.")


def forget_user_memory(config: AppConfig, user_id: str, memory_id: str) -> bool:
    if _has_local_admin_capability(config):
        return bool(_load_local_memory_backend().forget(user_id, memory_id))

    raise AdminApiError("Admin local SQLite indisponible.")


def export_user_memories(config: AppConfig, user_id: str) -> dict[str, Any]:
    if _has_local_admin_capability(config):
        records = _load_local_memory_backend().export_user(user_id, 1000)
        return {
            "ok": True,
            "user_id": user_id,
            "count": len(records),
            "truncated": len(records) >= 1000,
            "records": [_record_to_admin_memory_result(item) for item in records],
        }

    raise AdminApiError("Admin local SQLite indisponible.")


def get_homegraph_user_graph(
    config: AppConfig,
    user_id: str,
    *,
    include_uncertain: bool | None = None,
    min_weight: float | None = None,
    max_links: int | None = None,
) -> dict[str, Any]:
    if _is_local_homegraph_enabled(config):
        modules = _load_local_homegraph_modules()
        modules["init_db"](_homegraph_db_path(config))
        resolved_user_id = _resolve_homegraph_user_id(config, user_id)
        return modules["build_viewer_graph_payload"](
            resolved_user_id,
            _homegraph_db_path(config),
            include_uncertain=True if include_uncertain is None else include_uncertain,
            min_weight=min_weight,
            max_links=max_links,
        )

    raise AdminApiError("Homegraph local SQLite indisponible.")


def get_homegraph_multihop_graph(
    config: AppConfig,
    center_node_id: str,
    *,
    mode: str | None = None,
    max_depth: int | None = None,
    max_nodes: int | None = None,
    max_links: int | None = None,
    include_uncertain: bool | None = None,
    min_weight: float | None = None,
) -> dict[str, Any]:
    if _is_local_homegraph_enabled(config):
        modules = _load_local_homegraph_modules()
        modules["init_db"](_homegraph_db_path(config))
        return modules["build_multihop_graph_payload"](
            center_node_id,
            _homegraph_db_path(config),
            mode=mode or "multihop",
            max_depth=max_depth or 1,
            max_nodes=max_nodes,
            max_links=max_links,
            include_uncertain=True if include_uncertain is None else include_uncertain,
            min_weight=min_weight,
        )

    raise AdminApiError("Homegraph local SQLite indisponible.")


def merge_homegraph_enrichment(config: AppConfig, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if _is_local_homegraph_enabled(config):
        modules = _load_local_homegraph_modules()
        modules["init_db"](_homegraph_db_path(config))
        errors, _warnings = _validate_local_homegraph_payload(user_id, payload, modules["stable_node_kinds"])
        if errors:
            raise AdminApiError(f"Local Homegraph validation failed: {errors[0]}")
        modules["merge_payload"](
            payload,
            db_path=_homegraph_db_path(config),
            source_ref=str(payload.get("source_ref", "")).strip() or None,
            model_name=str(payload.get("model_name", "")).strip() or None,
        )
        return _build_local_homegraph_response(
            source="homegraph_enrichment_v1_local",
            user_id=user_id,
            payload=payload,
            db_path=_homegraph_db_path(config),
        )

    raise AdminApiError("Homegraph local SQLite indisponible.")


def validate_homegraph_enrichment(config: AppConfig, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if _is_local_homegraph_enabled(config):
        modules = _load_local_homegraph_modules()
        errors, warnings = _validate_local_homegraph_payload(user_id, payload, modules["stable_node_kinds"])
        return {
            "ok": True,
            "viewer_id": user_id,
            "source": "homegraph_enrichment_validation_v1_local",
            "mergeable": not errors,
            "counts": _build_local_homegraph_counts(payload),
            "errors": errors,
            "warnings": warnings,
        }

    raise AdminApiError("Homegraph local SQLite indisponible.")


def preview_homegraph_enrichment(config: AppConfig, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if _is_local_homegraph_enabled(config):
        modules = _load_local_homegraph_modules()
        modules["init_db"](_homegraph_db_path(config))
        errors, _warnings = _validate_local_homegraph_payload(user_id, payload, modules["stable_node_kinds"])
        if errors:
            raise AdminApiError(f"Local Homegraph validation failed: {errors[0]}")

        source_db = _homegraph_db_path(config)
        with tempfile.TemporaryDirectory(prefix="homegraph-preview-") as temp_dir:
            preview_db = Path(temp_dir) / source_db.name
            if source_db.exists():
                shutil.copy2(source_db, preview_db)
            else:
                modules["init_db"](preview_db)
            modules["merge_payload"](
                payload,
                db_path=preview_db,
                source_ref=str(payload.get("source_ref", "")).strip() or None,
                model_name=str(payload.get("model_name", "")).strip() or None,
            )
            result = _build_local_homegraph_response(
                source="homegraph_enrichment_v1_local_preview",
                user_id=user_id,
                payload=payload,
                db_path=preview_db,
            )
            result["dry_run"] = True
            return result

    raise AdminApiError("Homegraph local SQLite indisponible.")


def import_user_memories(config: AppConfig, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if _has_local_admin_capability(config):
        imported_count = _load_local_memory_backend().import_records(user_id, list(payload.get("records", [])))
        return {
            "ok": True,
            "user_id": user_id,
            "imported_count": imported_count,
        }

    raise AdminApiError("Admin local SQLite indisponible.")


def remember_user_memory(config: AppConfig, user_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if _has_local_admin_capability(config):
        memory_id = _load_local_memory_backend().remember(user_id, text, metadata=metadata or {})
        return {"ok": True, "id": memory_id}

    raise AdminApiError("Admin local SQLite indisponible.")
