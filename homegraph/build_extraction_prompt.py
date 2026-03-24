from __future__ import annotations

import argparse
from pathlib import Path


PROMPT_TEMPLATE_PATH = Path("homegraph/extraction_prompt_v1.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a ready-to-send GPT extraction prompt from a homegraph payload."
    )
    parser.add_argument("input_path", help="Path to the homegraph viewer payload JSON file.")
    parser.add_argument(
        "--template",
        default=str(PROMPT_TEMPLATE_PATH),
        help="Path to the extraction prompt template.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output file path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    template_path = Path(args.template)

    prompt = (
        template_path.read_text(encoding="utf-8").rstrip()
        + "\n\n## Payload Viewer\n\n```json\n"
        + input_path.read_text(encoding="utf-8").strip()
        + "\n```\n"
    )

    if args.output:
        output_path = Path(args.output)
    else:
        stem = input_path.stem
        output_path = input_path.with_name(f"{stem}_prompt.txt")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt + "\n", encoding="utf-8")
    print(f"homegraph_prompt_ok input={input_path} output={output_path}")


if __name__ == "__main__":
    main()
