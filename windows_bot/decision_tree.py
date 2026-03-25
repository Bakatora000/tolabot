from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
import re


DECISION_TREE_FILE = Path(__file__).with_name("decision_tree.json")


@lru_cache(maxsize=1)
def load_decision_tree() -> dict[str, Any]:
    with DECISION_TREE_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_social_triggers(kind: str) -> tuple[str, ...]:
    social = load_decision_tree().get("social", {})
    values = social.get(kind, [])
    return tuple(str(item) for item in values)


def get_web_search_fragments(kind: str) -> tuple[str, ...]:
    web_search = load_decision_tree().get("web_search", {})
    values = web_search.get(kind, [])
    return tuple(str(item) for item in values)


def get_web_rules() -> tuple[dict[str, Any], ...]:
    rules = load_decision_tree().get("web_rules", [])
    return tuple(rule for rule in rules if isinstance(rule, dict))


def get_social_reply_template(intent: str, repeated: bool = False) -> str:
    templates = load_decision_tree().get("social", {}).get("reply_templates", {})
    intent_templates = templates.get(intent, {})
    key = "repeated" if repeated else "default"
    return str(intent_templates.get(key, ""))


def classify_social_intent(normalized_text: str) -> str:
    lowered = (normalized_text or "").strip().lower()
    if lowered in get_social_triggers("greeting_triggers"):
        return "greeting"
    if lowered in get_social_triggers("closing_triggers"):
        return "closing"
    if lowered in get_social_triggers("short_acknowledgment_triggers"):
        return "short_ack"
    return ""


def build_web_search_decision(message: str, context_text: str, mode: str = "auto") -> dict[str, str | bool]:
    normalized_mode = "auto" if not mode else str(mode).strip().lower()
    if normalized_mode == "always":
        return {"enabled": True, "reason": "mode_always", "rule_id": "mode_always", "query": message}
    if normalized_mode in {"off", "false", "0", "disabled"}:
        return {"enabled": False, "reason": "mode_disabled", "rule_id": "mode_disabled", "query": ""}

    lowered = str(message).lower()
    context_lower = str(context_text).lower()
    trigger_fragments = get_web_search_fragments("trigger_fragments")
    followup_fragments = get_web_search_fragments("followup_fragments")
    context_indicators = get_web_search_fragments("context_indicators")
    weather_terms = get_web_search_fragments("weather_followup_terms")
    temperature_terms = get_web_search_fragments("temperature_followup_terms")
    actions = load_decision_tree().get("web_search_actions", {})

    if any(fragment in lowered for fragment in followup_fragments) and any(indicator in context_lower for indicator in context_indicators):
        query = message
        location_match = re.search(r"\b(?:à|a)\s+([A-ZÀ-ÖØ-öø-ÿ][a-zà-öø-ÿ-]+)\b", context_text)
        if any(fragment in lowered for fragment in weather_terms) and ("météo" in context_lower or "meteo" in context_lower):
            if location_match:
                query = str(actions.get("weather_followup_template", "météo demain à {location}")).format(location=location_match.group(1))
            else:
                query = str(actions.get("weather_default_query", "météo demain"))
        elif any(fragment in lowered for fragment in temperature_terms) and (
            "météo" in context_lower or "meteo" in context_lower or "quel temps fait" in context_lower
        ):
            if location_match:
                query = str(actions.get("temperature_followup_template", "température actuelle à {location}")).format(location=location_match.group(1))
            else:
                query = str(actions.get("temperature_default_query", "température actuelle"))
        return {"enabled": True, "reason": "context_followup", "rule_id": "context_followup", "query": query}

    for rule in get_web_rules():
        match_all = tuple(str(item) for item in rule.get("match_all", []))
        match_any = tuple(str(item) for item in rule.get("match_any", []))
        if match_all and not all(term in lowered for term in match_all):
            continue
        if match_any and not any(term in lowered for term in match_any):
            continue

        query_action = str(rule.get("query_action", "")).strip()
        if not query_action:
            continue
        query_value = str(actions.get(query_action, "")).strip()
        if not query_value:
            continue

        if bool(rule.get("requires_location")):
            location_match = re.search(r"\b(?:à|a)\s+([A-ZÀ-ÖØ-öø-ÿ][a-zà-öø-ÿ-]+)\b", message)
            if not location_match:
                continue
            return {
                "enabled": True,
                "reason": "direct_trigger",
                "rule_id": str(rule.get("rule_id", "structured_rule")),
                "query": query_value.format(location=location_match.group(1)),
            }
        return {
            "enabled": True,
            "reason": "direct_trigger",
            "rule_id": str(rule.get("rule_id", "structured_rule")),
            "query": query_value,
        }

    if any(fragment in lowered for fragment in trigger_fragments):
        return {"enabled": True, "reason": "direct_trigger", "rule_id": "generic_direct_trigger", "query": message}

    if ("qui est" in lowered or "qu'est ce que" in lowered or "qu est ce que" in lowered) and context_lower.strip() in {"", "aucun"}:
        return {"enabled": True, "reason": "open_fact_query", "rule_id": "open_fact_query", "query": message}

    return {"enabled": False, "reason": "no_match", "rule_id": "no_match", "query": ""}
