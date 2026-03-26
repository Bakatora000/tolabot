from __future__ import annotations

import argparse
from pathlib import Path


PROMPT_TEMPLATE_PATH = Path("homegraph/extraction_prompt_v1.md")
PROMPT_TEMPLATE_V2_PATH = Path("homegraph/extraction_prompt_v2.md")


def build_extraction_prompt(
    input_path: Path,
    *,
    template_path: Path,
    output_path: Path,
) -> str:
    prompt = (
        template_path.read_text(encoding="utf-8").rstrip()
        + "\n\n## Payload Viewer\n\n```json\n"
        + input_path.read_text(encoding="utf-8").strip()
        + "\n```\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt + "\n", encoding="utf-8")
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a ready-to-send GPT extraction prompt from a homegraph payload."
    )
    parser.add_argument("input_path", help="Path to the homegraph viewer payload JSON file.")
    parser.add_argument(
        "--template",
        default=None,
        help="Path to the extraction prompt template.",
    )
    parser.add_argument(
        "--version",
        choices=("v1", "v2"),
        default="v1",
        help="Prompt template version shortcut when --template is not provided.",
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
    if args.template:
        template_path = Path(args.template)
    else:
        template_path = PROMPT_TEMPLATE_V2_PATH if args.version == "v2" else PROMPT_TEMPLATE_PATH

    if args.output:
        output_path = Path(args.output)
    else:
        stem = input_path.stem
        output_path = input_path.with_name(f"{stem}_prompt.txt")

    build_extraction_prompt(
        input_path,
        template_path=template_path,
        output_path=output_path,
    )
    print(f"homegraph_prompt_ok input={input_path} output={output_path}")


if __name__ == "__main__":
    main()
