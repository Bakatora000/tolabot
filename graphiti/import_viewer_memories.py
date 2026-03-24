from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from graphiti.common import build_graphiti
except ModuleNotFoundError:
    from common import build_graphiti
from graphiti_core.nodes import EpisodeType


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a viewer memory export into local Graphiti.")
    parser.add_argument("input_path", help="Path to the viewer export JSON file.")
    parser.add_argument(
        "--db",
        default=os.getenv("GRAPHITI_KUZU_DB_PATH", "graphiti/data/graphiti.kuzu"),
        help="Path to the local Kuzu database file.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of memories to import from the file.",
    )
    parser.add_argument(
        "--group-id",
        default=None,
        help="Optional Graphiti group_id override. Defaults to the exported user_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the file and print what would be imported without writing to Graphiti.",
    )
    return parser.parse_args()


def parse_reference_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def build_episode_name(memory_id: str | None, viewer: str | None, index: int) -> str:
    if memory_id:
        return f"mem0:{memory_id}"
    if viewer:
        return f"mem0:{viewer}:{index}"
    return f"mem0:episode:{index}"


def build_episode_body(memory: dict) -> str:
    return str(memory.get("memory", "")).strip()


def normalize_group_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    if not normalized:
        return None
    return normalized


async def ensure_kuzu_indexes(graphiti) -> None:
    index_queries = [
        "CALL CREATE_FTS_INDEX('Episodic', 'episode_content', ['content', 'source', 'source_description']);",
        "CALL CREATE_FTS_INDEX('Entity', 'node_name_and_summary', ['name', 'summary']);",
        "CALL CREATE_FTS_INDEX('Community', 'community_name', ['name']);",
        "CALL CREATE_FTS_INDEX('RelatesToNode_', 'edge_name_and_fact', ['name', 'fact']);",
    ]
    for query in index_queries:
        try:
            await graphiti.driver.execute_query(query)
        except Exception as exc:
            message = str(exc)
            if "already exists" in message:
                continue
            raise


async def run_import(input_path: Path, db_path: Path, limit: int | None, group_id: str | None, dry_run: bool) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    user_id = str(payload.get("user_id", "")).strip()
    viewer = str(payload.get("viewer", "")).strip() or None
    channel = str(payload.get("channel", "")).strip() or None
    memories = list(payload.get("memories", []))
    if limit is not None:
        memories = memories[: max(0, limit)]

    if dry_run:
        print(f"dry_run_ok user_id={user_id} count={len(memories)} input={input_path}")
        return

    resolved_group_id = normalize_group_id(group_id or user_id)
    if not resolved_group_id:
        raise ValueError("Could not derive a valid Graphiti group_id from the export payload.")

    run_started = time.perf_counter()
    print(
        f"import_start user_id={user_id} group_id={resolved_group_id} count={len(memories)} db={db_path}"
    )

    graphiti = build_graphiti(db_path)
    try:
        if getattr(graphiti.driver, "provider", None) and getattr(graphiti.driver.provider, "value", None) == "kuzu":
            await ensure_kuzu_indexes(graphiti)
        else:
            await graphiti.build_indices_and_constraints(delete_existing=False)
        # Graphiti 0.28.2 expects drivers to expose `_database`, but KuzuDriver
        # currently only implements `with_database()` and stores all groups in
        # one local file. Pin the active group id on the driver to avoid the
        # Neo4j/Falkor-style clone path.
        setattr(graphiti.driver, "_database", resolved_group_id)
        imported = 0
        for index, memory in enumerate(memories, start=1):
            body = build_episode_body(memory)
            if not body:
                continue
            memory_id = str(memory.get("id", "")).strip() or None
            created_at = parse_reference_time(memory.get("created_at"))
            episode_name = build_episode_name(memory_id, viewer, index)
            source_description = f"mem0 export for viewer={viewer or user_id}"
            if channel:
                source_description += f" channel={channel}"
            if user_id:
                source_description += f" user_id={user_id}"
            episode_started = time.perf_counter()
            print(
                f"episode_start index={index} total={len(memories)} name={episode_name} created_at={created_at.isoformat()}"
            )
            await graphiti.add_episode(
                name=episode_name,
                episode_body=body,
                source_description=source_description,
                reference_time=created_at,
                source=EpisodeType.text,
                group_id=resolved_group_id,
            )
            imported += 1
            print(
                f"episode_ok index={index} name={episode_name} duration_s={time.perf_counter() - episode_started:.2f}"
            )
        print(
            "import_ok "
            f"user_id={user_id} group_id={resolved_group_id} imported={imported} "
            f"duration_s={time.perf_counter() - run_started:.2f} db={db_path}"
        )
    finally:
        await graphiti.close()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_import(
            input_path=Path(args.input_path),
            db_path=Path(args.db),
            limit=args.limit,
            group_id=args.group_id,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
