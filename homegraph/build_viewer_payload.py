from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a GPT extraction payload from a mem0 viewer export."
    )
    parser.add_argument("input_path", help="Path to a mem0 viewer export JSON file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional explicit output path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of memories to include.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    memories = list(payload.get("memories", []))
    if args.limit is not None:
        memories = memories[: max(0, args.limit)]

    packed_memories = []
    for memory in memories:
        packed_memories.append(
            {
                "memory_id": memory.get("id"),
                "text": memory.get("memory", ""),
                "created_at": memory.get("created_at"),
                "metadata": memory.get("metadata", {}),
            }
        )

    output_payload = {
        "viewer_id": payload.get("user_id"),
        "channel": payload.get("channel"),
        "viewer_login": payload.get("viewer"),
        "memory_count": len(packed_memories),
        "instructions": {
            "goal": "Extract useful viewer facts and relations for a Twitch bot memory graph.",
            "rules": [
                "Do not invent facts.",
                "Return only facts supported by the memories.",
                "Assign a confidence between 0 and 1.",
                "Mark uncertain or conflicting facts clearly.",
                "Keep source_memory_ids for every extracted fact or relation.",
            ],
            "output_format": "JSON",
        },
        "memories": packed_memories,
    }

    output_path = Path(
        args.output
        or f"homegraph/payloads/{(payload.get('viewer') or 'viewer')}_gpt_payload.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"homegraph_payload_ok viewer_id={output_payload['viewer_id']} count={output_payload['memory_count']} output={output_path}"
    )


if __name__ == "__main__":
    main()
