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
    parser.add_argument(
        "--include-uncertain",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include uncertain links and lower-confidence fallback relations.",
    )
    parser.add_argument(
        "--min-weight",
        type=float,
        default=None,
        help="Optional minimum weight/confidence to keep a link in the exported subgraph.",
    )
    parser.add_argument(
        "--max-links",
        type=int,
        default=None,
        help="Optional maximum number of links to include in the exported subgraph.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        payload_as_json(
            args.viewer_id,
            Path(args.db),
            include_uncertain=args.include_uncertain,
            min_weight=args.min_weight,
            max_links=args.max_links,
        )
    )


if __name__ == "__main__":
    main()
