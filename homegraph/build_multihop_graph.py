import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from homegraph.multihop_graph import payload_as_json
    from homegraph.schema import DEFAULT_DB_PATH
except ModuleNotFoundError:
    from multihop_graph import payload_as_json
    from schema import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Homegraph multi-hop graph JSON payload.")
    parser.add_argument("--center-node-id", required=True, help="Center node id, for example game:valheim")
    parser.add_argument(
        "--mode",
        choices=("multihop", "entity_focus"),
        default="multihop",
        help="Graph expansion mode.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file.",
    )
    parser.add_argument("--max-depth", type=int, default=1, help="Maximum BFS depth from the center node.")
    parser.add_argument("--max-nodes", type=int, default=None, help="Optional maximum number of nodes.")
    parser.add_argument("--max-links", type=int, default=None, help="Optional maximum number of links.")
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
        help="Optional minimum weight/confidence to keep a link in the graph.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        payload_as_json(
            args.center_node_id,
            Path(args.db),
            mode=args.mode,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
            max_links=args.max_links,
            include_uncertain=args.include_uncertain,
            min_weight=args.min_weight,
        )
    )


if __name__ == "__main__":
    main()
