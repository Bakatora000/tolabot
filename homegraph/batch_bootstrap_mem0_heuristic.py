from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from homegraph.bootstrap_mem0_heuristic import heuristic_extract
    from homegraph.merge_extraction import merge_file
    from homegraph.schema import DEFAULT_DB_PATH
except ModuleNotFoundError:
    from bootstrap_mem0_heuristic import heuristic_extract
    from merge_extraction import merge_file
    from schema import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate heuristic homegraph extraction JSON files from a directory of mem0 exports."
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing mem0 export JSON files, typically *_export.json.",
    )
    parser.add_argument(
        "--pattern",
        default="*_export.json",
        help="Glob pattern used to select export files inside input_dir.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where heuristic extraction files will be written. Defaults to input_dir.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge each generated extraction into SQLite after writing it.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path used when --merge is enabled.",
    )
    return parser.parse_args()


def build_output_path(output_dir: Path, export_path: Path) -> Path:
    return output_dir / f"{export_path.stem.replace('_export', '')}_heuristic_extraction.json"


def process_export_file(export_path: Path, output_dir: Path, *, merge: bool, db_path: str) -> dict[str, str | int]:
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    extraction = heuristic_extract(payload)
    output_path = build_output_path(output_dir, export_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if merge:
        merge_file(
            output_path,
            db_path=db_path,
            model_name="heuristic-bootstrap-v2",
            source_ref=f"heuristic-batch:{extraction['viewer_id']}",
        )

    return {
        "viewer_id": str(extraction.get("viewer_id", "")),
        "facts": len(extraction.get("facts", [])),
        "relations": len(extraction.get("relations", [])),
        "links": len(extraction.get("links", [])),
        "output_path": str(output_path),
    }


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    export_paths = sorted(input_dir.glob(args.pattern))

    if not export_paths:
        print(f"homegraph_heuristic_batch_noop input_dir={input_dir} pattern={args.pattern}")
        return

    processed = 0
    for export_path in export_paths:
        result = process_export_file(
            export_path,
            output_dir,
            merge=args.merge,
            db_path=args.db,
        )
        processed += 1
        print(
            f"homegraph_heuristic_batch_item viewer_id={result['viewer_id']} "
            f"facts={result['facts']} relations={result['relations']} links={result['links']} "
            f"output={result['output_path']}"
        )

    print(
        f"homegraph_heuristic_batch_ok input_dir={input_dir} pattern={args.pattern} "
        f"processed={processed} merge={bool(args.merge)}"
    )


if __name__ == "__main__":
    main()
