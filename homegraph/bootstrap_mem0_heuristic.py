from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from homegraph.schema import DEFAULT_DB_PATH
    from homegraph.merge_extraction import merge_file
except ModuleNotFoundError:
    from schema import DEFAULT_DB_PATH
    from merge_extraction import merge_file


KNOWN_GAMES = [
    "Valheim",
    "Satisfactory",
    "World of Warcraft",
    "Enshrouded",
    "Hollow Knight",
    "REPO",
    "Clair Obscur",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap a homegraph extraction JSON from a mem0 export using simple heuristics."
    )
    parser.add_argument("input_path", help="Path to the mem0 export JSON file.")
    parser.add_argument("--output", default=None, help="Optional extraction JSON output path.")
    parser.add_argument("--merge", action="store_true", help="Merge the generated extraction into SQLite.")
    parser.add_argument("--db", default=None, help="Optional SQLite database path for --merge.")
    return parser.parse_args()


def clean_memory_text(value: str) -> str:
    text = str(value or "").strip()
    if "Réponse du bot:" in text:
        text = text.split("Réponse du bot:", 1)[0].strip()
    return text


def sentence_case(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    return value[0].upper() + value[1:]


def find_games(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for game in KNOWN_GAMES:
        if game.lower() in lowered and game not in found:
            found.append(game)
    return found


def build_fact(
    kind: str,
    value: str,
    memory_id: str,
    confidence: float,
    status: str = "active",
    source_excerpt: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "value": value,
        "confidence": confidence,
        "status": status,
        "source_memory_ids": [memory_id],
        "source_excerpt": source_excerpt or value,
    }


def build_relation(
    target_type: str,
    target_value: str,
    relation_type: str,
    memory_id: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "target_id_or_value": target_value,
        "relation_type": relation_type,
        "confidence": confidence,
        "source_memory_ids": [memory_id],
    }


def merge_items(items: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in items:
        key = tuple(str(item.get(field) or "").strip() for field in key_fields)
        if key not in merged:
            merged[key] = dict(item)
            continue
        existing = merged[key]
        existing["confidence"] = max(float(existing.get("confidence") or 0), float(item.get("confidence") or 0))
        source_ids = list(existing.get("source_memory_ids") or [])
        for source_id in item.get("source_memory_ids") or []:
            if source_id not in source_ids:
                source_ids.append(source_id)
        existing["source_memory_ids"] = source_ids
    return list(merged.values())


def heuristic_extract(payload: dict[str, Any]) -> dict[str, Any]:
    viewer_id = str(payload.get("user_id") or "").strip()
    channel = str(payload.get("channel") or "").strip() or None
    viewer_login = str(payload.get("viewer") or "").strip() or None
    display_name = viewer_login
    facts: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    topic_counter: Counter[str] = Counter()
    question_like_count = 0

    for memory in payload.get("memories", []):
        memory_id = str(memory.get("id") or "").strip()
        text = clean_memory_text(memory.get("memory", ""))
        lowered = text.lower()
        if not text:
            continue
        if "?" in text:
            question_like_count += 1

        games = find_games(text)
        for game in games:
            topic_counter[game] += 1

        if "je joue" in lowered:
            for game in games:
                facts.append(build_fact("plays_game", game, memory_id, 0.86, source_excerpt=text))
                relations.append(build_relation("game", game, "plays", memory_id, 0.86))

        if "builder compétent" in lowered and "satisfactory" in lowered:
            facts.append(build_fact("plays_game", "Satisfactory", memory_id, 0.9, source_excerpt=text))
            relations.append(build_relation("game", "Satisfactory", "plays", memory_id, 0.9))
            facts.append(
                build_fact(
                    "build_style",
                    "builder compétent sur Satisfactory",
                    memory_id,
                    0.88,
                    source_excerpt=text,
                )
            )

        if "lit son chat pendant ses constructions" in lowered:
            facts.append(
                build_fact(
                    "personality_trait",
                    "lit son chat pendant ses constructions",
                    memory_id,
                    0.72,
                    source_excerpt=text,
                )
            )

        if "complimente parfois sarahp79" in lowered:
            facts.append(
                build_fact(
                    "social_relation",
                    "complimente parfois Sarahp79",
                    memory_id,
                    0.68,
                    status="uncertain",
                    source_excerpt=text,
                )
            )

        if "n'a pas plus emball" in lowered or "n a pas plus emball" in lowered:
            for game in games:
                facts.append(build_fact("dislikes_game", game, memory_id, 0.82, source_excerpt=text))
                relations.append(build_relation("game", game, "dislikes", memory_id, 0.82))

        if "j'aime" in lowered and "douves" in lowered:
            facts.append(build_fact("personality_trait", "aime les douves bien profondes", memory_id, 0.76, source_excerpt=text))

        if "k7vhs" in lowered:
            topic_counter["K7VHS"] += 1

        if "valheim" in lowered and ("no death" in lowered or "cauchemar" in lowered):
            facts.append(
                build_fact(
                    "stream_context",
                    "associe souvent Valheim a des defis no-death ou cauchemar",
                    memory_id,
                    0.83,
                    source_excerpt=text,
                )
            )
            relations.append(build_relation("topic", "no death", "likes", memory_id, 0.76))

        if "grand maître" in text or "dieu" in lowered:
            topic_counter["running_gag_k7vhs"] += 1

    if topic_counter["K7VHS"] >= 2:
        facts.append(
            {
                "kind": "recurring_topic",
                "value": "K7VHS",
                "confidence": 0.74,
                "status": "active",
                "source_memory_ids": [],
                "source_excerpt": "Plusieurs souvenirs mentionnent K7VHS.",
            }
        )
    if topic_counter["running_gag_k7vhs"] >= 2:
        facts.append(
            {
                "kind": "personality_trait",
                "value": "utilise souvent l'humour autour de K7VHS et de figures divines",
                "confidence": 0.72,
                "status": "uncertain",
                "source_memory_ids": [],
                "source_excerpt": "Plusieurs souvenirs tournent autour d'une blague recurrente sur K7VHS.",
            }
        )
    if question_like_count >= 4:
        facts.append(
            {
                "kind": "personality_trait",
                "value": "pose souvent des questions au bot",
                "confidence": 0.7,
                "status": "active",
                "source_memory_ids": [],
                "source_excerpt": "Le viewer enchaine souvent les questions au bot.",
            }
        )

    facts = merge_items(facts, ["kind", "value"])
    relations = merge_items(relations, ["target_type", "target_id_or_value", "relation_type"])

    summary_bits: list[str] = []
    plays = [fact["value"] for fact in facts if fact["kind"] == "plays_game" and fact["status"] == "active"]
    if plays:
        summary_bits.append(f"joue a {plays[0]}")
    build_styles = [fact["value"] for fact in facts if fact["kind"] == "build_style"]
    if build_styles:
        summary_bits.append(build_styles[0])
    recurring = [fact["value"] for fact in facts if fact["kind"] == "recurring_topic"]
    if recurring:
        summary_bits.append(f"revient souvent sur {recurring[0]}")
    traits = [fact["value"] for fact in facts if fact["kind"] == "personality_trait" and fact["status"] == "active"]
    if traits:
        summary_bits.append(traits[0])

    if summary_bits:
        summary_short = sentence_case(", ".join(summary_bits[:2]))
    elif question_like_count >= 3:
        summary_short = "Viewer qui pose souvent des questions au bot."
    else:
        summary_short = ""

    return {
        "viewer_id": viewer_id,
        "channel": channel,
        "viewer_login": viewer_login,
        "display_name": display_name,
        "summary_short": summary_short,
        "summary_long": "",
        "facts": facts,
        "relations": relations,
        "conflicts": [],
        "needs_human_review": [],
    }


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    extraction = heuristic_extract(payload)

    output_path = Path(
        args.output
        or input_path.with_name(input_path.stem.replace("_export", "") + "_heuristic_extraction.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"homegraph_heuristic_ok viewer_id={extraction['viewer_id']} facts={len(extraction['facts'])} relations={len(extraction['relations'])} output={output_path}"
    )

    if args.merge:
        merge_file(
            output_path,
            db_path=args.db or DEFAULT_DB_PATH,
            model_name="heuristic-bootstrap-v1",
            source_ref=f"heuristic:{extraction['viewer_id']}",
        )


if __name__ == "__main__":
    main()
