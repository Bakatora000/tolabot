from __future__ import annotations

from pathlib import Path
import sys

from bot_config import AppConfig
from context_sources import make_context_source_result
from homegraph_ids import resolve_homegraph_viewer_id


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def is_homegraph_local_enabled(config: AppConfig) -> bool:
    return bool(config.homegraph_local_enabled and config.homegraph_db_path)


def build_homegraph_context_source(config: AppConfig, channel: str, viewer: str):
    if not is_homegraph_local_enabled(config):
        return None

    from homegraph.context import build_viewer_context_payload
    from homegraph.schema import init_db
    from memory_client import build_mem0_user_id

    db_path = Path(config.homegraph_db_path).resolve()
    init_db(db_path)
    viewer_id = resolve_homegraph_viewer_id(db_path, build_mem0_user_id(channel, viewer), viewer)
    payload = build_viewer_context_payload(viewer_id, db_path)
    text_block = str(payload.get("text_block", "")).strip()
    if not text_block:
        return None

    stale = bool(payload.get("staleness", {}).get("is_stale", False))
    confidence = 0.72 if stale else 0.84
    return make_context_source_result(
        "homegraph_local",
        text_block,
        priority=87,
        confidence=confidence,
        stale=stale,
        meta={
            "context_label": "homegraph-local",
            "viewer_id": str(payload.get("viewer_id", "")),
            "profile_last_updated_at": payload.get("staleness", {}).get("profile_last_updated_at"),
        },
    )
