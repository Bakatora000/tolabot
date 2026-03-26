from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from graphiti.export_viewer_memories import export_viewer_memories, split_user_id
except ModuleNotFoundError:
    from export_viewer_memories import export_viewer_memories, split_user_id

try:
    from homegraph.build_extraction_prompt import (
        PROMPT_TEMPLATE_PATH,
        PROMPT_TEMPLATE_V2_PATH,
        build_extraction_prompt,
    )
    from homegraph.build_viewer_payload import build_viewer_payload
except ModuleNotFoundError:
    from build_extraction_prompt import (
        PROMPT_TEMPLATE_PATH,
        PROMPT_TEMPLATE_V2_PATH,
        build_extraction_prompt,
    )
    from build_viewer_payload import build_viewer_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the full Homegraph extraction workflow for one viewer."
    )
    parser.add_argument("user_id", help="Viewer user_id, for example twitch:streamer:viewer:alice")
    parser.add_argument(
        "--base-url",
        default=os.getenv("GRAPHITI_MEM0_ADMIN_BASE_URL", "http://127.0.0.1:8000/admin"),
        help="Base URL of the local mem0 admin API.",
    )
    parser.add_argument(
        "--version",
        choices=("v1", "v2"),
        default="v2",
        help="Prompt workflow version.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of memories to include in the GPT payload.",
    )
    parser.add_argument(
        "--output-dir",
        default="homegraph/payloads",
        help="Directory where export, payload, and prompt files will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    admin_key = os.getenv("MEM0_ADMIN_KEY", "").strip()
    if not admin_key:
        raise SystemExit("MEM0_ADMIN_KEY is required.")

    _, viewer = split_user_id(args.user_id)
    viewer_slug = viewer or "viewer"
    output_dir = Path(args.output_dir)
    export_path = output_dir / f"{viewer_slug}_export.json"
    payload_path = output_dir / f"{viewer_slug}_gpt_payload.json"
    prompt_suffix = "_prompt_v2.txt" if args.version == "v2" else "_prompt.txt"
    prompt_path = output_dir / f"{viewer_slug}{prompt_suffix}"

    export_payload = export_viewer_memories(
        args.user_id,
        base_url=args.base_url,
        admin_key=admin_key,
        output_path=export_path,
    )
    gpt_payload = build_viewer_payload(
        export_path,
        output_path=payload_path,
        limit=args.limit,
    )
    template_path = PROMPT_TEMPLATE_V2_PATH if args.version == "v2" else PROMPT_TEMPLATE_PATH
    build_extraction_prompt(
        payload_path,
        template_path=template_path,
        output_path=prompt_path,
    )

    print(
        "homegraph_prepare_ok "
        f"user_id={args.user_id} "
        f"export_count={export_payload['count']} "
        f"payload_count={gpt_payload['memory_count']} "
        f"export={export_path} payload={payload_path} prompt={prompt_path}"
    )


if __name__ == "__main__":
    main()
