from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from bot_config import AppConfig
from bot_logic import normalize_spaces, smart_truncate


DEFAULT_EMPTY_CONTEXT = {"viewer_context": "aucun", "global_context": "aucun", "items": []}
MIN_MEMORY_SCORE = 0.35
MIN_MEMORY_CHARS = 18
MAX_MEMORY_USER_MESSAGE_CHARS = 280
MAX_MEMORY_BOT_REPLY_CHARS = 280
MAX_MEMORY_TOTAL_CHARS = 560


class MemoryApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemorySearchItem:
    id: str
    score: float
    memory: str


def is_useful_memory_item(item: MemorySearchItem) -> bool:
    memory = normalize_spaces(item.memory)
    lowered = memory.lower()
    if not memory or len(memory) < MIN_MEMORY_CHARS:
        return False
    if item.score < MIN_MEMORY_SCORE:
        return False

    low_value_fragments = [
        "bonjour",
        "salut",
        "hello",
        "merci",
        "bravo",
        "bien joue",
        "bien joué",
        "je vais bouder",
        "ah non",
        "de nouveau",
    ]
    if any(fragment in lowered for fragment in low_value_fragments) and "reponse du bot:" not in lowered:
        return False

    return True


def is_mem0_enabled(config: AppConfig) -> bool:
    return bool(config.mem0_enabled and config.mem0_api_base_url and config.mem0_api_key)


def build_mem0_user_id(channel: str, viewer: str) -> str:
    clean_channel = normalize_spaces(channel).lower()
    clean_viewer = normalize_spaces(viewer).lower()
    return f"twitch:{clean_channel}:viewer:{clean_viewer}"


def build_mem0_headers(config: AppConfig) -> dict[str, str]:
    return {
        "X-API-Key": config.mem0_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def truncate_memory_text(text: str, limit: int) -> str:
    normalized = normalize_spaces(text)
    if not normalized:
        return ""
    return smart_truncate(normalized, limit)


def should_store_in_mem0(user_message: str, bot_reply: str = "", author_is_owner: bool = False) -> bool:
    user_text = normalize_spaces(user_message)
    reply_text = normalize_spaces(bot_reply)
    combined = f"{user_text} {reply_text}".strip().lower()

    if not user_text:
        return False

    low_value_exact = {
        "bonjour",
        "salut",
        "hello",
        "merci",
        "bravo",
        "bien joue",
        "bien joué",
        "ok",
        "oui",
        "non",
    }
    if user_text.lower() in low_value_exact:
        return False

    ephemeral_fragments = [
        "charade",
        "devinette",
        "mon premier",
        "mon second",
        "mon troisieme",
        "mon troisième",
        "mon tout",
        "qui suis-je",
        "qui suis je",
        "bien joue",
        "bien joué",
        "bravo",
        "perdu",
        "rate",
        "raté",
        "tu ne m'aime pas",
        "pourquoi tu ne veux pas parler",
    ]
    if any(fragment in combined for fragment in ephemeral_fragments):
        return False

    memory_instruction_markers = [
        "note que",
        "note bien que",
        "garde en tete que",
        "garde en tête que",
        "souviens toi que",
        "souviens-toi que",
        "n'oublie pas que",
        "n oublie pas que",
        "retiens que",
        "memorise que",
        "mémorise que",
    ]
    if any(marker in combined for marker in memory_instruction_markers) and not author_is_owner:
        return False

    durable_markers = [
        "je joue",
        "je joue aussi",
        "je stream",
        "je streame",
        "je prefere",
        "je préfère",
        "j'aime",
        "j adore",
        "j'adore",
        "mon jeu prefere",
        "mon jeu préféré",
        "je suis sur",
        "je suis dans",
        "je travaille",
        "j'utilise",
        "j utilise",
        "mon setup",
        "mon pc",
        "ma config",
        "mon chien",
        "mon chat",
        "ma chienne",
        "mon bouledogue",
        "n'oublie pas",
        "n oublie pas",
        "pour info",
    ]

    question_markers = [
        "tu joues a quoi",
        "tu joues à quoi",
        "dit moi le meilleur jeu",
        "dis moi le meilleur jeu",
        "c'est quoi le meilleur jeu",
    ]

    if any(marker in combined for marker in durable_markers):
        return True
    if any(marker in combined for marker in question_markers):
        return False

    return len(user_text) >= 8 and bool(reply_text)


def _request(
    config: AppConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    if not is_mem0_enabled(config):
        raise MemoryApiError("Mem0 n'est pas activé ou sa configuration est incomplète.")

    url = f"{config.mem0_api_base_url}{path}"

    try:
        response = requests.request(
            method,
            url,
            headers=build_mem0_headers(config),
            json=payload,
            timeout=config.mem0_timeout_seconds,
            verify=config.mem0_verify_ssl,
        )
    except requests.RequestException as exc:
        raise MemoryApiError(f"Erreur réseau mem0: {exc}") from exc

    if response.status_code >= 400:
        detail = None
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip() or None
        raise MemoryApiError(f"Erreur mem0 HTTP {response.status_code}: {detail}")

    return response


def healthcheck_memory_api(config: AppConfig) -> bool:
    if not is_mem0_enabled(config):
        return False

    response = _request(config, "GET", "/health")
    data = response.json()
    return data.get("status") == "ok"


def search_memory(
    config: AppConfig,
    channel: str,
    viewer: str,
    query: str,
    limit: int | None = None,
) -> list[MemorySearchItem]:
    payload: dict[str, Any] = {
        "user_id": build_mem0_user_id(channel, viewer),
        "query": normalize_spaces(query),
    }
    if limit is not None:
        payload["limit"] = max(1, limit)

    response = _request(config, "POST", "/search", payload=payload)
    data = response.json()
    results = data.get("results", [])

    items: list[MemorySearchItem] = []
    for item in results:
        items.append(
            MemorySearchItem(
                id=str(item.get("id", "")),
                score=float(item.get("score", 0.0) or 0.0),
                memory=normalize_spaces(str(item.get("memory", ""))),
            )
        )
    return items


def get_memory_context(
    config: AppConfig,
    channel: str,
    viewer: str,
    message: str,
    limit: int | None = None,
) -> dict[str, Any]:
    items = search_memory(
        config,
        channel=channel,
        viewer=viewer,
        query=message,
        limit=limit or config.mem0_context_limit,
    )
    if not items:
        return dict(DEFAULT_EMPTY_CONTEXT)

    useful_items = [item for item in items if is_useful_memory_item(item)]
    if not useful_items:
        return dict(DEFAULT_EMPTY_CONTEXT)

    viewer_context = "\n".join(f"{viewer.lower()}: {item.memory}" for item in useful_items if item.memory)
    return {
        "viewer_context": viewer_context or "aucun",
        "global_context": "aucun",
        "items": [{"id": item.id, "score": item.score, "memory": item.memory} for item in useful_items],
    }


def store_memory_turn(
    config: AppConfig,
    channel: str,
    viewer: str,
    user_message: str,
    bot_reply: str | None,
    metadata: dict[str, Any] | None = None,
    author_is_owner: bool = False,
) -> str | None:
    if not should_store_in_mem0(user_message, bot_reply or "", author_is_owner=author_is_owner):
        return None

    memory_parts = [truncate_memory_text(user_message, MAX_MEMORY_USER_MESSAGE_CHARS)]
    if bot_reply:
        truncated_reply = truncate_memory_text(bot_reply, MAX_MEMORY_BOT_REPLY_CHARS)
        if truncated_reply:
            memory_parts.append(f"Réponse du bot: {truncated_reply}")

    memory_text = "\n".join(part for part in memory_parts if part)
    memory_text = truncate_memory_text(memory_text, MAX_MEMORY_TOTAL_CHARS)

    payload = {
        "user_id": build_mem0_user_id(channel, viewer),
        "text": memory_text,
        "metadata": {
            "channel": normalize_spaces(channel).lower(),
            "viewer": normalize_spaces(viewer).lower(),
            **(metadata or {}),
        },
    }

    response = _request(config, "POST", "/remember", payload=payload)
    data = response.json()
    memory_id = data.get("id")
    return str(memory_id) if memory_id else None
