from __future__ import annotations

import argparse
import asyncio
import json
import os
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

    graphiti = build_graphiti(db_path)
    try:
        await graphiti.build_indices_and_constraints(delete_existing=False)
        imported = 0
        for index, memory in enumerate(memories, start=1):
            body = build_episode_body(memory)
            if not body:
                continue
            memory_id = str(memory.get("id", "")).strip() or None
            created_at = parse_reference_time(memory.get("created_at"))
            source_description = f"mem0 export for viewer={viewer or user_id}"
            if channel:
                source_description += f" channel={channel}"
            await graphiti.add_episode(
                name=build_episode_name(memory_id, viewer, index),
                episode_body=body,
                source_description=source_description,
                reference_time=created_at,
                source=EpisodeType.text,
                group_id=group_id or user_id or None,
            )
            imported += 1
        print(f"import_ok user_id={user_id} imported={imported} db={db_path}")
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
