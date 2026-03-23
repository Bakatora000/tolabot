from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from memory_service.config import Settings
from memory_service.models import MemoryRecord

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_spaces(text: str) -> str:
    return " ".join((text or "").split()).strip()


def tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in (text or ""))
    return [token for token in cleaned.split() if token]


def similarity_score(query: str, memory: str) -> float:
    query_tokens = tokenize(query)
    memory_tokens = tokenize(memory)
    if not query_tokens or not memory_tokens:
        return 0.0

    query_counts = Counter(query_tokens)
    memory_counts = Counter(memory_tokens)
    common = sum(min(query_counts[token], memory_counts[token]) for token in query_counts)
    query_norm = math.sqrt(sum(value * value for value in query_counts.values()))
    memory_norm = math.sqrt(sum(value * value for value in memory_counts.values()))
    if query_norm == 0.0 or memory_norm == 0.0:
        return 0.0
    return round(common / (query_norm * memory_norm), 4)


class MemoryBackendError(RuntimeError):
    """Raised when the underlying memory backend is unavailable."""


class MemoryBackend(Protocol):
    def healthcheck(self) -> None:
        ...

    def search(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]:
        ...

    def remember(self, user_id: str, text: str, metadata: dict[str, Any] | None = None) -> str | None:
        ...

    def forget(self, user_id: str, memory_id: str) -> bool:
        ...

    def recent(self, user_id: str, limit: int) -> list[MemoryRecord]:
        ...


@dataclass
class FileStore:
    items: list[dict[str, Any]]


class FileMemoryBackend:
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.lock = threading.Lock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write(FileStore(items=[]))

    def healthcheck(self) -> None:
        if not self.store_path.exists():
            raise MemoryBackendError("File store is missing.")

    def _read(self) -> FileStore:
        try:
            with self.store_path.open("r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except FileNotFoundError as exc:
            raise MemoryBackendError("File store is missing.") from exc
        except json.JSONDecodeError as exc:
            raise MemoryBackendError("File store is corrupted.") from exc
        return FileStore(items=list(data.get("items", [])))

    def _write(self, store: FileStore) -> None:
        with self.store_path.open("w", encoding="utf-8") as file_obj:
            json.dump({"items": store.items}, file_obj, ensure_ascii=False, indent=2)

    def search(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]:
        with self.lock:
            store = self._read()
        matches: list[MemoryRecord] = []
        for item in store.items:
            if item.get("user_id") != user_id:
                continue
            score = similarity_score(query, item.get("memory", ""))
            if score <= 0:
                continue
            record = MemoryRecord(**item)
            record.score = score
            matches.append(record)
        matches.sort(key=lambda record: (record.score, record.updated_at), reverse=True)
        return matches[:limit]

    def remember(self, user_id: str, text: str, metadata: dict[str, Any] | None = None) -> str | None:
        metadata = dict(metadata or {})
        message_id = normalize_spaces(str(metadata.get("message_id", "")))
        now = utc_now_iso()

        with self.lock:
            store = self._read()

            if message_id:
                for item in store.items:
                    if item.get("user_id") != user_id:
                        continue
                    item_message_id = normalize_spaces(str(item.get("metadata", {}).get("message_id", "")))
                    if item_message_id and item_message_id == message_id:
                        return str(item.get("id"))

            memory_id = f"mem_{uuid.uuid4().hex[:12]}"
            store.items.append(
                {
                    "id": memory_id,
                    "user_id": user_id,
                    "memory": normalize_spaces(text),
                    "metadata": metadata,
                    "created_at": now,
                    "updated_at": now,
                    "score": 1.0,
                }
            )
            self._write(store)
            return memory_id

    def forget(self, user_id: str, memory_id: str) -> bool:
        with self.lock:
            store = self._read()
            original_len = len(store.items)
            store.items = [
                item for item in store.items
                if not (item.get("user_id") == user_id and item.get("id") == memory_id)
            ]
            deleted = len(store.items) != original_len
            if deleted:
                self._write(store)
            return deleted

    def recent(self, user_id: str, limit: int) -> list[MemoryRecord]:
        with self.lock:
            store = self._read()
        records = [MemoryRecord(**item) for item in store.items if item.get("user_id") == user_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[:limit]


class Mem0MemoryBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise MemoryBackendError("mem0ai is not installed.") from exc

        self._memory_class = Memory
        self._memory = self._build_memory()

    def _build_memory(self):
        vector_config: dict[str, Any] = {
            "collection_name": self.settings.mem0_qdrant_collection,
            "on_disk": self.settings.mem0_qdrant_on_disk,
            "embedding_model_dims": self.settings.mem0_embedder_dims,
        }
        if self.settings.mem0_qdrant_url and self.settings.mem0_qdrant_api_key:
            vector_config["url"] = self.settings.mem0_qdrant_url
            vector_config["api_key"] = self.settings.mem0_qdrant_api_key
        elif self.settings.mem0_qdrant_path:
            vector_config["path"] = str(self.settings.mem0_qdrant_path)
        elif self.settings.mem0_qdrant_host and self.settings.mem0_qdrant_port:
            vector_config["host"] = self.settings.mem0_qdrant_host
            vector_config["port"] = self.settings.mem0_qdrant_port

        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": vector_config,
            },
            "history_db_path": str(self.settings.mem0_history_db_path),
            "llm": {
                "provider": self.settings.mem0_llm_provider,
                "config": self._build_llm_config(),
            },
            "embedder": {
                "provider": self.settings.mem0_embedder_provider,
                "config": self._build_embedder_config(),
            },
        }
        return self._memory_class.from_config(config)

    def _build_llm_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "model": self.settings.mem0_llm_model,
            "temperature": 0.1,
        }
        if self.settings.mem0_llm_provider == "lmstudio":
            config["lmstudio_base_url"] = self.settings.mem0_lmstudio_base_url
        return config

    def _build_embedder_config(self) -> dict[str, Any]:
        return {
            "model": self.settings.mem0_embedder_model,
            "embedding_dims": self.settings.mem0_embedder_dims,
        }

    def healthcheck(self) -> None:
        if self._memory is None:
            raise MemoryBackendError("Mem0 backend is not initialized.")

    def search(self, user_id: str, query: str, limit: int) -> list[MemoryRecord]:
        try:
            payload = self._memory.search(query=query, user_id=user_id, limit=limit, rerank=False)
        except Exception as exc:
            raise MemoryBackendError(str(exc)) from exc

        results = payload.get("results", payload) if isinstance(payload, dict) else payload
        normalized: list[MemoryRecord] = []
        for item in results or []:
            normalized.append(
                MemoryRecord(
                    id=str(item.get("id", "")),
                    user_id=str(item.get("user_id", user_id)),
                    memory=normalize_spaces(str(item.get("memory", ""))),
                    metadata=dict(item.get("metadata", {}) or {}),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at", item.get("created_at", ""))),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
        return normalized[:limit]

    def remember(self, user_id: str, text: str, metadata: dict[str, Any] | None = None) -> str | None:
        try:
            result = self._memory.add(
                messages=[{"role": "user", "content": normalize_spaces(text)}],
                user_id=user_id,
                metadata=metadata or {},
                infer=False,
            )
        except Exception as exc:
            raise MemoryBackendError(str(exc)) from exc

        if isinstance(result, dict):
            for key in ("id", "memory_id"):
                if result.get(key):
                    return str(result[key])
            records = result.get("results") or []
            if records and isinstance(records, list) and records[0].get("id"):
                return str(records[0]["id"])
        if isinstance(result, list) and result and isinstance(result[0], dict) and result[0].get("id"):
            return str(result[0]["id"])
        return None

    def forget(self, user_id: str, memory_id: str) -> bool:
        try:
            self._memory.delete(memory_id=memory_id)
            return True
        except Exception as exc:
            logger.warning("mem0 delete failed for user_id=%s memory_id=%s: %s", user_id, memory_id, exc)
            return False

    def recent(self, user_id: str, limit: int) -> list[MemoryRecord]:
        try:
            payload = self._memory.get_all(user_id=user_id, limit=limit) or []
        except Exception as exc:
            raise MemoryBackendError(str(exc)) from exc

        records = payload.get("results", payload) if isinstance(payload, dict) else payload
        normalized: list[MemoryRecord] = []
        for item in records:
            normalized.append(
                MemoryRecord(
                    id=str(item.get("id", "")),
                    user_id=str(item.get("user_id", user_id)),
                    memory=normalize_spaces(str(item.get("memory", ""))),
                    metadata=dict(item.get("metadata", {}) or {}),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at", item.get("created_at", ""))),
                    score=float(item.get("score", 1.0) or 1.0),
                )
            )
        normalized.sort(key=lambda record: record.created_at, reverse=True)
        return normalized[:limit]


def build_backend(settings: Settings) -> MemoryBackend:
    settings.ensure_directories()
    if settings.backend == "mem0":
        return Mem0MemoryBackend(settings)
    return FileMemoryBackend(settings.file_store_path)
