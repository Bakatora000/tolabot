from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

try:
    from graphiti.common import build_graphiti
except ModuleNotFoundError:
    from common import build_graphiti


async def run_validation(db_path: Path, reset: bool) -> None:
    graphiti = build_graphiti(db_path)
    try:
        await graphiti.build_indices_and_constraints(delete_existing=reset)
        print(f"graphiti_kuzu_init_ok db={db_path}")
    finally:
        await graphiti.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a local Graphiti + Kuzu setup.")
    parser.add_argument(
        "--db",
        default=os.getenv("GRAPHITI_KUZU_DB_PATH", "graphiti/data/graphiti.kuzu"),
        help="Path to the local Kuzu database file.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Recreate Graphiti indices/constraints from scratch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_validation(Path(args.db), reset=args.reset))


if __name__ == "__main__":
    main()
