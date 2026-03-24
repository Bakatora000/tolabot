from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
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

    def list_user_ids(self) -> list[str]:
        ...

    def export_user(self, user_id: str, limit: int) -> list[MemoryRecord]:
        ...

    def delete_memory(self, memory_id: str) -> bool:
        ...

    def purge_user(self, user_id: str, limit: int) -> tuple[int, bool]:
        ...

    def import_records(self, user_id: str, records: list[dict[str, Any]]) -> int:
        ...


@dataclass
class FileStore:
    items: list[dict[str, Any]]


@dataclass
class UserRegistryStore:
    user_ids: list[str]


class UserRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.lock = threading.Lock()
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write(UserRegistryStore(user_ids=[]))

    def _read(self) -> UserRegistryStore:
        try:
            with self.registry_path.open("r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except FileNotFoundError:
            return UserRegistryStore(user_ids=[])
        except json.JSONDecodeError as exc:
            raise MemoryBackendError("User registry is corrupted.") from exc
        return UserRegistryStore(user_ids=sorted({normalize_spaces(str(item)) for item in data.get("user_ids", []) if normalize_spaces(str(item))}))

    def _write(self, store: UserRegistryStore) -> None:
        payload = {"user_ids": sorted({normalize_spaces(user_id) for user_id in store.user_ids if normalize_spaces(user_id)})}
        with self.registry_path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)

    def list_user_ids(self) -> list[str]:
        with self.lock:
            return list(self._read().user_ids)

    def add(self, user_id: str) -> None:
        normalized = normalize_spaces(user_id)
        if not normalized:
            return
        with self.lock:
            store = self._read()
            if normalized not in store.user_ids:
                store.user_ids.append(normalized)
                self._write(store)

    def remove(self, user_id: str) -> None:
        normalized = normalize_spaces(user_id)
        if not normalized:
            return
        with self.lock:
            store = self._read()
            updated = [item for item in store.user_ids if item != normalized]
            if len(updated) != len(store.user_ids):
                self._write(UserRegistryStore(user_ids=updated))


class FileMemoryBackend:
    def __init__(self, store_path: Path, registry_path: Path):
        self.store_path = store_path
        self.lock = threading.Lock()
        self.registry = UserRegistry(registry_path)
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
            self.registry.add(user_id)
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
                if not any(item.get("user_id") == user_id for item in store.items):
                    self.registry.remove(user_id)
            return deleted

    def recent(self, user_id: str, limit: int) -> list[MemoryRecord]:
        with self.lock:
            store = self._read()
        records = [MemoryRecord(**item) for item in store.items if item.get("user_id") == user_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[:limit]

    def list_user_ids(self) -> list[str]:
        with self.lock:
            store = self._read()
        discovered = {normalize_spaces(str(item.get("user_id", ""))) for item in store.items if normalize_spaces(str(item.get("user_id", "")))}
        for user_id in discovered:
            self.registry.add(user_id)
        return sorted(set(self.registry.list_user_ids()) | discovered)

    def export_user(self, user_id: str, limit: int) -> list[MemoryRecord]:
        with self.lock:
            store = self._read()
        records = [MemoryRecord(**item) for item in store.items if item.get("user_id") == user_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[:limit]

    def delete_memory(self, memory_id: str) -> bool:
        with self.lock:
            store = self._read()
            deleted_item = next((item for item in store.items if item.get("id") == memory_id), None)
            if not deleted_item:
                return False
            user_id = str(deleted_item.get("user_id", ""))
            store.items = [item for item in store.items if item.get("id") != memory_id]
            self._write(store)
            if user_id and not any(item.get("user_id") == user_id for item in store.items):
                self.registry.remove(user_id)
            return True

    def purge_user(self, user_id: str, limit: int) -> tuple[int, bool]:
        with self.lock:
            store = self._read()
            matching_ids = [item.get("id") for item in store.items if item.get("user_id") == user_id]
            store.items = [item for item in store.items if item.get("user_id") != user_id]
            deleted_count = len(matching_ids)
            if deleted_count:
                self._write(store)
                self.registry.remove(user_id)
            return deleted_count, False

    def import_records(self, user_id: str, records: list[dict[str, Any]]) -> int:
        imported = 0
        for item in records:
            text = normalize_spaces(str(item.get("memory", item.get("text", ""))))
            if not text:
                continue
            metadata = dict(item.get("metadata", {}) or {})
            memory_id = self.remember(user_id, text, metadata=metadata)
            if memory_id:
                imported += 1
        return imported


class Mem0MemoryBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.registry = UserRegistry(settings.user_registry_path)
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
        self.registry.add(user_id)

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

    def list_user_ids(self) -> list[str]:
        discovered = set(self.registry.list_user_ids())
        discovered.update(self._extract_user_ids_from_qdrant_storage())
        for user_id in discovered:
            self.registry.add(user_id)
        return sorted(discovered)

    def _extract_user_ids_from_qdrant_storage(self) -> set[str]:
        qdrant_path = self.settings.mem0_qdrant_path
        if not qdrant_path:
            return set()

        storage_path = qdrant_path / "collection" / self.settings.mem0_qdrant_collection / "storage.sqlite"
        if not storage_path.exists():
            return set()

        try:
            connection = sqlite3.connect(f"file:{storage_path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            logger.warning("Cannot open Qdrant storage for admin user listing: %s", exc)
            return set()

        try:
            cursor = connection.cursor()
            cursor.execute("SELECT point FROM points")
            discovered: set[str] = set()
            pattern = re.compile(rb"twitch:[A-Za-z0-9_]+:viewer:[A-Za-z0-9_]+")
            for (blob,) in cursor.fetchall():
                raw = blob.tobytes() if isinstance(blob, memoryview) else blob
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", "ignore")
                for match in pattern.findall(raw or b""):
                    user_id = normalize_spaces(match.decode("utf-8", "ignore"))
                    if user_id:
                        discovered.add(user_id)
            return discovered
        except sqlite3.Error as exc:
            logger.warning("Cannot scan Qdrant storage for admin user listing: %s", exc)
            return set()
        finally:
            connection.close()

    def export_user(self, user_id: str, limit: int) -> list[MemoryRecord]:
        return self.recent(user_id, limit)

    def delete_memory(self, memory_id: str) -> bool:
        try:
            self._memory.delete(memory_id=memory_id)
            return True
        except Exception as exc:
            logger.warning("mem0 delete failed for memory_id=%s: %s", memory_id, exc)
            return False

    def purge_user(self, user_id: str, limit: int) -> tuple[int, bool]:
        records = self.export_user(user_id, limit)
        deleted_count = 0
        for record in records:
            if self.delete_memory(record.id):
                deleted_count += 1
        truncated = len(records) >= limit
        remaining = self.export_user(user_id, 1)
        if not remaining:
            self.registry.remove(user_id)
        return deleted_count, truncated

    def import_records(self, user_id: str, records: list[dict[str, Any]]) -> int:
        imported = 0
        for item in records:
            text = normalize_spaces(str(item.get("memory", item.get("text", ""))))
            if not text:
                continue
            metadata = dict(item.get("metadata", {}) or {})
            memory_id = self.remember(user_id, text, metadata=metadata)
            if memory_id:
                imported += 1
        return imported


def build_backend(settings: Settings) -> MemoryBackend:
    settings.ensure_directories()
    if settings.backend == "mem0":
        return Mem0MemoryBackend(settings)
    return FileMemoryBackend(settings.file_store_path, settings.user_registry_path)
