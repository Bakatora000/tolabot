from __future__ import annotations

import argparse
from pathlib import Path

try:
    from homegraph.schema import DEFAULT_DB_PATH, init_db
except ModuleNotFoundError:
    from schema import DEFAULT_DB_PATH, init_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize the homegrown graph SQLite database.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = init_db(Path(args.db))
    print(f"homegraph_init_ok db={db_path}")


if __name__ == "__main__":
    main()
