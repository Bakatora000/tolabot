from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a viewer's memories from the local mem0 admin API.")
    parser.add_argument("user_id", help="Viewer user_id, for example twitch:streamer:viewer:alice")
    parser.add_argument(
        "--base-url",
        default=os.getenv("GRAPHITI_MEM0_ADMIN_BASE_URL", "http://127.0.0.1:8000/admin"),
        help="Base URL of the local mem0 admin API.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional explicit output file path.",
    )
    return parser.parse_args()


def split_user_id(user_id: str) -> tuple[str | None, str | None]:
    parts = user_id.split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[1] or None, parts[3] or None
    return None, None


def main() -> None:
    args = parse_args()
    admin_key = os.getenv("MEM0_ADMIN_KEY", "").strip()
    if not admin_key:
        raise SystemExit("MEM0_ADMIN_KEY is required.")

    encoded_user_id = quote(args.user_id, safe="")
    response = requests.post(
        f"{args.base_url}/users/{encoded_user_id}/export",
        headers={"X-Admin-Key": admin_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    channel, viewer = split_user_id(args.user_id)
    output_path = Path(
        args.output
        or os.getenv("GRAPHITI_EXPORT_OUTPUT", f"graphiti/imports/{(viewer or 'viewer')}.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    export_payload = {
        "user_id": args.user_id,
        "channel": channel,
        "viewer": viewer,
        "count": payload.get("count", 0),
        "truncated": bool(payload.get("truncated", False)),
        "memories": payload.get("records", []),
    }
    output_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"export_ok user_id={args.user_id} count={export_payload['count']} output={output_path}")


if __name__ == "__main__":
    main()
