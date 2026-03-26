from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

try:
    from homegraph.schema import DEFAULT_DB_PATH
except ModuleNotFoundError:
    from schema import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the homegrown graph SQLite database.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    try:
        for table in [
            "viewer_profiles",
            "viewer_facts",
            "viewer_relations",
            "graph_entities",
            "viewer_links",
            "link_evidence",
            "graph_jobs",
            "graph_job_items",
        ]:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            count = int(row[0] if row else 0)
            print(f"{table}={count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
