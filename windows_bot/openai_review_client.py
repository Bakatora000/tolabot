from __future__ import annotations

import json
import re
from typing import Any

import requests

from bot_config import AppConfig


class OpenAIReviewError(RuntimeError):
    pass


def is_openai_review_enabled(config: AppConfig) -> bool:
    return bool(config.openai_review_enabled and config.openai_api_key and config.openai_review_model)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def build_review_export(
    config: AppConfig,
    export_payload: dict[str, Any],
) -> dict[str, Any]:
    export_root = export_payload.get("export", export_payload)
    records = export_root.get("records", [])
    compact_records: list[dict[str, str]] = []

    for item in records[: config.openai_review_max_records]:
        compact_records.append(
            {
                "id": str(item.get("id", "")),
                "text": _compact_text(str(item.get("memory", ""))),
            }
        )

    return {
        "viewer": _extract_viewer_name(str(export_root.get("user_id", ""))),
        "user_id": str(export_root.get("user_id", "")),
        "count": int(export_root.get("count", len(compact_records))),
        "records": compact_records,
    }


def analyze_review_export(
    config: AppConfig,
    review_export: dict[str, Any],
    severity: str = "balanced",
    verbose: bool = False,
) -> dict[str, Any]:
    if not is_openai_review_enabled(config):
        raise OpenAIReviewError("OpenAI review is not enabled or configuration is incomplete.")

    schema = {
        "name": "memory_review_proposals",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "viewer": {"type": "string"},
                "summary": {"type": "string"},
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "memory_id": {"type": "string"},
                            "action": {
                                "type": "string",
                                "enum": ["keep", "delete", "rewrite", "review"],
                            },
                            "reason": {"type": "string"},
                            "proposed_text": {"type": "string"},
                            "target_memory_id": {"type": "string"},
                        },
                        "required": [
                            "memory_id",
                            "action",
                            "reason",
                            "proposed_text",
                            "target_memory_id",
                        ],
                    },
                },
            },
            "required": ["viewer", "summary", "proposals"],
        },
    }

    severity_rules = {
        "conservative": (
            "Mode de severite : conservateur. Supprime avec retenue. "
            "En cas de doute, prefere keep ou review. "
            "Supprime seulement les souvenirs clairement ephemeres, triviaux, hostiles, dupliques ou non durables."
        ),
        "balanced": (
            "Mode de severite : equilibre. En cas de doute, prefere review. "
            "Supprime le bruit evident, mais conserve ou reecris les faits plausiblement durables."
        ),
        "aggressive": (
            "Mode de severite : agressif. Prefere delete pour les souvenirs faibles, contextuels, conversationnels ou peu informatifs. "
            "Conserve seulement les faits clairement durables et reutilisables."
        ),
    }

    system_prompt = (
        "Tu analyses des souvenirs de long terme pour un bot de chat de livestream. "
        "Ton travail est de proposer des actions de nettoyage sures pour un viewer a la fois. "
        "Regles : conserve les faits durables et utiles, supprime les salutations, emotions, blagues, questions ephemeres et bruit conversationnel, "
        "reecris seulement quand une formulation plus courte, neutre et factuelle preserve bien le sens d'origine, "
        "n'invente jamais de faits, choisis review en cas d'incertitude. "
        "N'utilise pas merge dans cette tache. "
        "Ecris obligatoirement en francais pour summary, reason et proposed_text. "
        "Les valeurs action doivent rester exactement : keep, delete, rewrite ou review. "
        f"{severity_rules.get(severity, severity_rules['balanced'])} "
        "Le champ summary doit rester court et operationnel."
    )

    user_prompt = {
        "task": (
            "Analyse cet export memoire pour un viewer et propose des actions de nettoyage. "
            "Retourne les champs textuels en francais."
        ),
        "viewer_export": review_export,
    }

    parsed = _run_structured_openai_request(
        config,
        schema=schema,
        system_prompt=system_prompt,
        user_payload=user_prompt,
        verbose=verbose,
        request_label=(
            f"viewer={review_export.get('viewer', '')} "
            f"records={len(review_export.get('records', []))} severity={severity}"
        ),
    )
    if verbose:
        print(
            f"[openai-review] parsed proposals={len(parsed.get('proposals', []))}",
            flush=True,
        )
    return parsed


def build_homegraph_enrichment(
    config: AppConfig,
    review_export: dict[str, Any],
    analysis: dict[str, Any],
    *,
    display_name: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    if not is_openai_review_enabled(config):
        raise OpenAIReviewError("OpenAI review is not enabled or configuration is incomplete.")

    schema = {
        "name": "homegraph_enrichment_v1",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary_short": {"type": "string"},
                "summary_long": {"type": "string"},
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"type": "string"},
                            "value": {"type": "string"},
                            "confidence": {"type": "number"},
                            "status": {"type": "string"},
                            "source_memory_ids": {"type": "array", "items": {"type": "string"}},
                            "source_excerpt": {"type": "string"},
                        },
                        "required": ["kind", "value", "confidence", "status", "source_memory_ids", "source_excerpt"],
                    },
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "target_type": {"type": "string"},
                            "target_id_or_value": {"type": "string"},
                            "relation_type": {"type": "string"},
                            "confidence": {"type": "number"},
                            "source_memory_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["target_type", "target_id_or_value", "relation_type", "confidence", "source_memory_ids"],
                    },
                },
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "target_type": {"type": "string"},
                            "target_value": {"type": "string"},
                            "relation_type": {"type": "string"},
                            "strength": {"type": "number"},
                            "confidence": {"type": "number"},
                            "status": {"type": "string"},
                            "polarity": {"type": "string"},
                            "source_memory_ids": {"type": "array", "items": {"type": "string"}},
                            "source_excerpt": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "entity_status": {"type": "string"},
                        },
                        "required": [
                            "target_type",
                            "target_value",
                            "relation_type",
                            "strength",
                            "confidence",
                            "status",
                            "polarity",
                            "source_memory_ids",
                            "source_excerpt",
                            "aliases",
                            "entity_status",
                        ],
                    },
                },
                "conflicts": {"type": "array", "items": {"type": "string"}},
                "needs_human_review": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "summary_short",
                "summary_long",
                "facts",
                "relations",
                "links",
                "conflicts",
                "needs_human_review",
            ],
        },
    }

    user_id = str(review_export.get("user_id", "")).strip()
    channel, viewer_login = _parse_viewer_identity(user_id)
    viewer_name = display_name or review_export.get("viewer") or viewer_login or user_id

    system_prompt = (
        "Tu produis un enrichissement Homegraph structure a partir d'un export memoire viewer. "
        "Objectif : extraire peu d'items, mais utiles et directement mergeables dans Homegraph. "
        "N'invente aucun fait. Si une information n'est pas soutenue par les souvenirs fournis, ne la produis pas. "
        "Utilise des valeurs courtes, concretes et reutilisables. "
        "Quand tu hesites, utilise un confidence plus bas et status=uncertain. "
        "Evite de dupliquer la meme information dans facts, relations et links sans raison. "
        "Pour source_memory_ids, utilise seulement des ids presents dans les records. "
        "Pour source_excerpt, cite un extrait court et factuel des records fournis. "
        "Relations privilegiees : plays, likes, dislikes, talks_about, returns_to, knows, compliments, jokes_about, interacts_with, plays_in_mode. "
        "Target_type doit rester simple : viewer, game, topic, running_gag, stream_mode, trait, object. "
        "Retourne les champs textuels en francais quand c'est naturel."
    )

    user_prompt = {
        "task": "Propose un enrichissement Homegraph V1 structure pour ce viewer.",
        "viewer": {
            "viewer_id": user_id,
            "channel": channel,
            "viewer_login": viewer_login,
            "display_name": viewer_name,
        },
        "review_export": review_export,
        "review_analysis": analysis,
    }

    parsed = _run_structured_openai_request(
        config,
        schema=schema,
        system_prompt=system_prompt,
        user_payload=user_prompt,
        verbose=verbose,
        request_label=(
            f"homegraph viewer={viewer_name} "
            f"records={len(review_export.get('records', []))}"
        ),
    )
    return {
        "viewer_id": user_id,
        "channel": channel,
        "viewer_login": viewer_login,
        "display_name": viewer_name,
        "summary_short": str(parsed.get("summary_short", "")).strip(),
        "summary_long": str(parsed.get("summary_long", "")).strip(),
        "facts": list(parsed.get("facts", [])),
        "relations": list(parsed.get("relations", [])),
        "links": list(parsed.get("links", [])),
        "conflicts": list(parsed.get("conflicts", [])),
        "needs_human_review": list(parsed.get("needs_human_review", [])),
        "model_name": config.openai_review_model,
        "source_ref": f"openai-review:{viewer_login or viewer_name}:{review_export.get('count', 0)}",
    }


def _extract_viewer_name(user_id: str) -> str:
    marker = ":viewer:"
    if marker in user_id:
        return user_id.split(marker, 1)[1]
    return user_id


def _parse_viewer_identity(user_id: str) -> tuple[str | None, str | None]:
    parts = user_id.split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[1] or None, parts[3] or None
    return None, None


def _run_structured_openai_request(
    config: AppConfig,
    *,
    schema: dict[str, Any],
    system_prompt: str,
    user_payload: dict[str, Any],
    verbose: bool = False,
    request_label: str = "",
) -> dict[str, Any]:
    if verbose:
        print(f"[openai-review] request model={config.openai_review_model} {request_label}".strip(), flush=True)
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openai_review_model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema["name"],
                        "strict": schema["strict"],
                        "schema": schema["schema"],
                    }
                },
            },
            timeout=config.openai_review_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise OpenAIReviewError(
            f"OpenAI request timed out after {config.openai_review_timeout_seconds}s."
        ) from exc
    except requests.RequestException as exc:
        raise OpenAIReviewError(f"OpenAI network error: {exc}") from exc
    if verbose:
        print(f"[openai-review] response status={response.status_code}", flush=True)

    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip() or None
        raise OpenAIReviewError(f"OpenAI HTTP {response.status_code}: {detail}")

    data = response.json()
    text_output = _extract_response_output_text(data)
    if not text_output:
        raise OpenAIReviewError("OpenAI response did not contain structured output text.")

    try:
        return json.loads(text_output)
    except json.JSONDecodeError as exc:
        raise OpenAIReviewError(f"OpenAI returned invalid JSON: {exc}") from exc


def _extract_response_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return ""
