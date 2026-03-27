from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from bot_config import AppConfig
from bot_logic import normalize_spaces, smart_truncate


DEFAULT_EMPTY_CONTEXT = {"viewer_context": "aucun", "global_context": "aucun", "items": []}
MIN_MEMORY_SCORE = 0.35
MIN_MEMORY_CHARS = 18
MAX_MEMORY_USER_MESSAGE_CHARS = 280
MAX_MEMORY_BOT_REPLY_CHARS = 280
MAX_MEMORY_TOTAL_CHARS = 560


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class MemoryApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemorySearchItem:
    id: str
    score: float
    memory: str


_LOCAL_MEMORY_BACKEND = None


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
    return bool(config.mem0_local_backend_enabled)


def _get_local_memory_backend():
    global _LOCAL_MEMORY_BACKEND
    if _LOCAL_MEMORY_BACKEND is None:
        from memory_service.backend import build_backend
        from memory_service.config import Settings

        _LOCAL_MEMORY_BACKEND = build_backend(Settings.load())
    return _LOCAL_MEMORY_BACKEND


def build_mem0_user_id(channel: str, viewer: str) -> str:
    clean_channel = normalize_spaces(channel).lower()
    clean_viewer = normalize_spaces(viewer).lower()
    return f"twitch:{clean_channel}:viewer:{clean_viewer}"


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


def healthcheck_memory_api(config: AppConfig) -> bool:
    if not is_mem0_enabled(config):
        return False
    try:
        _get_local_memory_backend().healthcheck()
    except Exception as exc:
        raise MemoryApiError(f"Erreur backend mémoire local: {exc}") from exc
    return True


def search_memory(
    config: AppConfig,
    channel: str,
    viewer: str,
    query: str,
    limit: int | None = None,
) -> list[MemorySearchItem]:
    try:
        records = _get_local_memory_backend().search(
            user_id=build_mem0_user_id(channel, viewer),
            query=normalize_spaces(query),
            limit=max(1, limit) if limit is not None else config.mem0_context_limit,
        )
    except Exception as exc:
        raise MemoryApiError(f"Erreur backend mémoire local: {exc}") from exc
    return [
        MemorySearchItem(
            id=str(item.id),
            score=float(item.score),
            memory=normalize_spaces(str(item.memory)),
        )
        for item in records
    ]


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

    try:
        memory_id = _get_local_memory_backend().remember(
            payload["user_id"],
            payload["text"],
            metadata=payload["metadata"],
        )
    except Exception as exc:
        raise MemoryApiError(f"Erreur backend mémoire local: {exc}") from exc
    return str(memory_id) if memory_id else None
