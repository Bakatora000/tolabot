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

KNOWN_TOPICS = [
    "automation",
    "optimisation",
    "build",
    "usines",
    "construction",
    "K7VHS",
]

KNOWN_STREAM_MODES = [
    "no death",
    "hardcore",
    "cauchemar",
]

AMBIGUOUS_VIEWER_LABELS = {
    "k7vhs",
}

QUESTION_FALSE_POSITIVES = {
    "qui",
    "quoi",
    "quel",
    "quels",
    "quelle",
    "quelles",
    "ou",
    "où",
    "quand",
    "comment",
    "pourquoi",
    "peut",
    "puis",
    "mais",
    "une",
}

NON_VIEWER_ENTITY_LABELS = {
    "atp",
    "tennis",
    "tessnis",
    "reuters",
    "lyon",
    "villeurbanne",
    "twitch",
    "monde",
    "hormuz",
    "projet",
    "mary",
    "trump",
    "wow",
    "hollow",
    "clair",
    "obscur",
    "knight",
    "edge",
    "dvd",
    "grece",
    "supercopter",
    "k2000",
    "tonnerre",
    "vhs",
    "dieu",
}

KNOWN_VIEWER_FALSE_POSITIVES = {
    *(item.lower() for item in KNOWN_GAMES),
    *(item.lower() for item in KNOWN_TOPICS if item.lower() not in AMBIGUOUS_VIEWER_LABELS),
    *(item.lower() for item in KNOWN_STREAM_MODES),
    "oui",
    "ich",
    "les",
    *QUESTION_FALSE_POSITIVES,
    *NON_VIEWER_ENTITY_LABELS,
}


def normalize_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value or "").strip().lower())


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


def find_topics(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for topic in KNOWN_TOPICS:
        if topic.lower() in lowered and topic not in found:
            found.append(topic)
    if any(token in lowered for token in ("optimis", "usine", "factory", "factories")) and "automation" not in found:
        found.append("automation")
    return found


def find_stream_modes(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for mode in KNOWN_STREAM_MODES:
        if mode.lower() in lowered and mode not in found:
            found.append(mode)
    return found


def find_viewers(text: str) -> list[str]:
    found: list[str] = []
    stopwords = {
        "reponse",
        "bot",
        "viewer",
        "elle",
        "il",
        "ils",
        "elles",
        "lui",
        "leur",
        "leurs",
        "on",
        "nous",
        "vous",
        "tu",
        "toi",
        "je",
        "j",
        "affirme",
        "dit",
        "pense",
        "ajoute",
        "explique",
        "raconte",
        "precise",
        "précise",
        "demande",
        "aime",
        "adore",
        "deteste",
        "déteste",
        "joue",
    }
    animal_context_tokens = (
        "chien",
        "chienne",
        "chat",
        "chatte",
        "chiot",
        "animal",
        "bouledogue",
        "berger",
        "husky",
        "labrador",
        "caniche",
    )
    object_context_tokens = (
        "bijou",
        "bijoux",
        "porte cle",
        "porte clé",
        "string",
        "cotte de maille",
        "haubergiste",
    )
    news_context_tokens = (
        "reuters",
        "monde",
        "actualit",
        "météo",
        "meteo",
        "cinéma",
        "cinema",
        "journal",
        "classement",
    )
    for match in re.finditer(r"@?([A-Z][A-Za-z0-9_]{2,})", text or ""):
        viewer = match.group(1)
        lowered = viewer.lower()
        if lowered in stopwords:
            continue
        preceded_by_at = match.group(0).startswith("@")
        has_twitch_shape = "_" in viewer or any(char.isdigit() for char in viewer)
        is_sentence_initial_plain_word = (
            not preceded_by_at
            and not has_twitch_shape
            and match.start() == 0
            and viewer[1:].islower()
        )
        if is_sentence_initial_plain_word:
            continue
        local_window_start = max(0, match.start() - 32)
        local_window_end = min(len(text or ""), match.end() + 32)
        local_context = (text or "")[local_window_start:local_window_end].lower()
        if any(token in local_context for token in animal_context_tokens) and not (preceded_by_at or has_twitch_shape):
            continue
        if any(token in local_context for token in object_context_tokens) and not (preceded_by_at or has_twitch_shape):
            continue
        if lowered in QUESTION_FALSE_POSITIVES:
            continue
        if lowered in NON_VIEWER_ENTITY_LABELS and not preceded_by_at:
            continue
        if any(token in local_context for token in news_context_tokens) and lowered in NON_VIEWER_ENTITY_LABELS:
            continue
        if viewer not in found:
            found.append(viewer)
    return found


def filter_candidate_viewers(viewers: list[str]) -> list[str]:
    filtered: list[str] = []
    for viewer in viewers:
        lowered = viewer.strip().lower()
        if not lowered:
            continue
        if lowered in KNOWN_VIEWER_FALSE_POSITIVES:
            continue
        if viewer not in filtered:
            filtered.append(viewer)
    return filtered


def find_viewer_alias_tokens(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"([A-Z][A-Za-z0-9_]{2,})", text or ""):
        viewer = match.group(1)
        if viewer not in found:
            found.append(viewer)
    return filter_candidate_viewers(found)


def derive_viewer_alias_hints(
    memories: list[dict[str, Any]],
) -> tuple[dict[str, str], set[str]]:
    alias_map: dict[str, str] = {}
    non_viewer_keys: set[str] = set()

    def register_aliases(canonical: str, alias_fragment: str) -> None:
        canonical_candidates = filter_candidate_viewers([canonical])
        if not canonical_candidates:
            return
        canonical_name = canonical_candidates[0]
        canonical_key = normalize_name_key(canonical_name)
        if not canonical_key:
            return
        alias_map[canonical_key] = canonical_name
        for alias in find_viewer_alias_tokens(alias_fragment):
            alias_key = normalize_name_key(alias)
            if not alias_key or alias_key == canonical_key:
                continue
            alias_map[alias_key] = canonical_name

    for memory in memories:
        text = clean_memory_text(memory.get("memory", ""))
        if not text:
            continue

        for match in re.finditer(r'\b(?:trio|groupe)\s+surnomm[ée]?\s+"?les\s+([A-Z][A-Za-z0-9_]{2,})', text, re.IGNORECASE):
            non_viewer_keys.add(normalize_name_key(match.group(1)))
        for match in re.finditer(r"\bLes\s+([A-Z][A-Za-z0-9_]{2,})\s+sont\s+(?:le|un)\s+(?:trio|groupe)\b", text, re.IGNORECASE):
            non_viewer_keys.add(normalize_name_key(match.group(1)))

        for match in re.finditer(
            r"([A-Z][A-Za-z0-9_]{2,})\s+est\s+le\s+plus\s+souvent\s+appel[a-zéèêîïôûùç]*\s+([^.]+)",
            text,
            re.IGNORECASE,
        ):
            register_aliases(match.group(1), match.group(2))

        for match in re.finditer(
            r"([A-Z][A-Za-z0-9_]{2,})\s*,\s*surnomm[ée][^,]*\s+([^.]+)",
            text,
            re.IGNORECASE,
        ):
            register_aliases(match.group(1), match.group(2))

        for match in re.finditer(r"([A-Z][A-Za-z0-9_]{2,})\s*\(([^)]+)\)", text):
            register_aliases(match.group(1), match.group(2))

    return alias_map, non_viewer_keys


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
        "source_memory_ids": [memory_id] if memory_id else [],
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
        "source_memory_ids": [memory_id] if memory_id else [],
    }


def build_link(
    target_type: str,
    target_value: str,
    relation_type: str,
    memory_id: str,
    strength: float,
    confidence: float,
    *,
    status: str = "active",
    polarity: str = "neutral",
    source_excerpt: str | None = None,
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "target_value": target_value,
        "relation_type": relation_type,
        "strength": strength,
        "confidence": confidence,
        "status": status,
        "polarity": polarity,
        "source_memory_ids": [memory_id] if memory_id else [],
        "source_excerpt": source_excerpt or target_value,
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


def merge_links(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            str(item.get("target_type") or "").strip(),
            str(item.get("target_value") or "").strip(),
            str(item.get("relation_type") or "").strip(),
        )
        if key not in merged:
            merged[key] = dict(item)
            continue
        existing = merged[key]
        existing["confidence"] = max(float(existing.get("confidence") or 0), float(item.get("confidence") or 0))
        existing["strength"] = max(float(existing.get("strength") or 0), float(item.get("strength") or 0))
        source_ids = list(existing.get("source_memory_ids") or [])
        for source_id in item.get("source_memory_ids") or []:
            if source_id not in source_ids:
                source_ids.append(source_id)
        existing["source_memory_ids"] = source_ids
        if not existing.get("source_excerpt") and item.get("source_excerpt"):
            existing["source_excerpt"] = item["source_excerpt"]
    return list(merged.values())


def heuristic_extract(payload: dict[str, Any]) -> dict[str, Any]:
    viewer_id = str(payload.get("user_id") or "").strip()
    channel = str(payload.get("channel") or "").strip() or None
    viewer_login = str(payload.get("viewer") or "").strip() or None
    display_name = viewer_login
    facts: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    topic_counter: Counter[str] = Counter()
    question_like_count = 0
    alias_map, non_viewer_keys = derive_viewer_alias_hints(payload.get("memories", []))
    viewer_login_key = normalize_name_key(viewer_login or "")

    for memory in payload.get("memories", []):
        memory_id = str(memory.get("id") or "").strip()
        text = clean_memory_text(memory.get("memory", ""))
        lowered = text.lower()
        if not text:
            continue
        if "?" in text:
            question_like_count += 1

        games = find_games(text)
        topics = find_topics(text)
        stream_modes = find_stream_modes(text)
        viewers: list[str] = []
        for viewer in filter_candidate_viewers(find_viewers(text)):
            normalized = alias_map.get(normalize_name_key(viewer), viewer)
            normalized_key = normalize_name_key(normalized)
            if not normalized_key:
                continue
            if normalized_key == viewer_login_key:
                continue
            if normalized_key in non_viewer_keys:
                continue
            if normalized not in viewers:
                viewers.append(normalized)

        for game in games:
            topic_counter[game] += 1
        for topic in topics:
            topic_counter[topic] += 1
        for mode in stream_modes:
            topic_counter[mode] += 1

        if "je joue" in lowered or "joue surtout" in lowered:
            for game in games:
                facts.append(build_fact("plays_game", game, memory_id, 0.86, source_excerpt=text))
                relations.append(build_relation("game", game, "plays", memory_id, 0.86))
                links.append(build_link("game", game, "plays", memory_id, 0.84, 0.86, polarity="positive", source_excerpt=text))

        if "j'adore" in lowered or "j adore" in lowered or "j'aime" in lowered:
            for game in games:
                links.append(build_link("game", game, "likes", memory_id, 0.8, 0.82, polarity="positive", source_excerpt=text))

        if "builder compétent" in lowered and "satisfactory" in lowered:
            facts.append(build_fact("plays_game", "Satisfactory", memory_id, 0.9, source_excerpt=text))
            relations.append(build_relation("game", "Satisfactory", "plays", memory_id, 0.9))
            links.append(build_link("game", "Satisfactory", "plays", memory_id, 0.9, 0.9, polarity="positive", source_excerpt=text))
            facts.append(
                build_fact(
                    "build_style",
                    "builder compétent sur Satisfactory",
                    memory_id,
                    0.88,
                    source_excerpt=text,
                )
            )
            links.append(
                build_link(
                    "topic",
                    "build efficace",
                    "uses_build_style",
                    memory_id,
                    0.82,
                    0.86,
                    polarity="positive",
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
            links.append(
                build_link(
                    "topic",
                    "construction",
                    "talks_about",
                    memory_id,
                    0.62,
                    0.7,
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
            links.append(
                build_link(
                    "viewer",
                    "Sarahp79",
                    "compliments",
                    memory_id,
                    0.66,
                    0.68,
                    status="uncertain",
                    polarity="positive",
                    source_excerpt=text,
                )
            )

        if "n'a pas plus emball" in lowered or "n a pas plus emball" in lowered:
            for game in games:
                facts.append(build_fact("dislikes_game", game, memory_id, 0.82, source_excerpt=text))
                relations.append(build_relation("game", game, "dislikes", memory_id, 0.82))
                links.append(build_link("game", game, "dislikes", memory_id, 0.78, 0.82, polarity="negative", source_excerpt=text))

        if "j'aime" in lowered and "douves" in lowered:
            facts.append(build_fact("personality_trait", "aime les douves bien profondes", memory_id, 0.76, source_excerpt=text))
            links.append(build_link("topic", "douves", "likes", memory_id, 0.7, 0.76, polarity="positive", source_excerpt=text))

        if "k7vhs" in lowered:
            topic_counter["K7VHS"] += 1
            links.append(build_link("running_gag", "K7VHS", "returns_to", memory_id, 0.7, 0.76, source_excerpt=text))

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
            links.append(build_link("game", "Valheim", "plays", memory_id, 0.8, 0.83, polarity="positive", source_excerpt=text))
            links.append(build_link("stream_mode", "no death", "plays_in_mode", memory_id, 0.76, 0.8, polarity="positive", source_excerpt=text))

        for topic in topics:
            relation_type = "returns_to" if topic_counter[topic] >= 2 else "talks_about"
            links.append(build_link("topic", topic, relation_type, memory_id, 0.66, 0.72, source_excerpt=text))

        for mode in stream_modes:
            if mode != "no death":
                links.append(build_link("stream_mode", mode, "likes", memory_id, 0.7, 0.74, polarity="positive", source_excerpt=text))

        for viewer in viewers:
            if "compliment" in lowered:
                links.append(build_link("viewer", viewer, "compliments", memory_id, 0.68, 0.72, polarity="positive", source_excerpt=text))
            elif "blague" in lowered or "vanne" in lowered:
                links.append(build_link("viewer", viewer, "jokes_about", memory_id, 0.62, 0.66, source_excerpt=text))
            elif "avec" in lowered or "parle avec" in lowered or "joue avec" in lowered:
                links.append(build_link("viewer", viewer, "interacts_with", memory_id, 0.64, 0.7, source_excerpt=text))
            else:
                links.append(build_link("viewer", viewer, "knows", memory_id, 0.55, 0.62, status="uncertain", source_excerpt=text))

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
        links.append(
            {
                "target_type": "running_gag",
                "target_value": "K7VHS",
                "relation_type": "returns_to",
                "strength": 0.72,
                "confidence": 0.74,
                "status": "active",
                "polarity": "neutral",
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
    links = merge_links(links)

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
        "links": links,
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
        f"homegraph_heuristic_ok viewer_id={extraction['viewer_id']} "
        f"facts={len(extraction['facts'])} relations={len(extraction['relations'])} "
        f"links={len(extraction['links'])} output={output_path}"
    )

    if args.merge:
        merge_file(
            output_path,
            db_path=args.db or DEFAULT_DB_PATH,
            model_name="heuristic-bootstrap-v2",
            source_ref=f"heuristic:{extraction['viewer_id']}",
        )


if __name__ == "__main__":
    main()
