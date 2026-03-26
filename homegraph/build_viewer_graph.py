import argparse
from pathlib import Path

try:
    from homegraph.graph import payload_as_json
    from homegraph.schema import DEFAULT_DB_PATH
except ModuleNotFoundError:
    from graph import payload_as_json
    from schema import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Homegraph viewer subgraph JSON payload.")
    parser.add_argument("--viewer-id", required=True, help="Viewer user_id.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(payload_as_json(args.viewer_id, Path(args.db)))


if __name__ == "__main__":
    main()
