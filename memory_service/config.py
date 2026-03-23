from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "oui"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    default_limit: int = 5
    max_limit: int = 10
    backend: str = "file"
    data_dir: Path = Path("./data")
    file_store_path: Path = Path("./data/memory_store.json")
    mem0_qdrant_host: str = "127.0.0.1"
    mem0_qdrant_port: int = 6333
    mem0_qdrant_collection: str = "mem0"
    mem0_qdrant_on_disk: bool = True
    mem0_history_db_path: Path = Path("./data/history.db")
    mem0_llm_provider: str = "openai"
    mem0_llm_model: str = "gpt-4.1-mini"
    mem0_embedder_provider: str = "openai"
    mem0_embedder_model: str = "text-embedding-3-small"

    @classmethod
    def load(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        file_store_path = Path(os.getenv("FILE_STORE_PATH", str(data_dir / "memory_store.json"))).resolve()
        mem0_history_db_path = Path(os.getenv("MEM0_HISTORY_DB_PATH", str(data_dir / "history.db"))).resolve()

        return cls(
            api_key=os.getenv("MEM0_API_KEY", "").strip(),
            host=os.getenv("MEM0_HOST", "127.0.0.1").strip(),
            port=max(1, int(os.getenv("MEM0_PORT", "8000").strip() or "8000")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            default_limit=max(1, int(os.getenv("MEM0_DEFAULT_LIMIT", "5").strip() or "5")),
            max_limit=max(1, int(os.getenv("MEM0_MAX_LIMIT", "10").strip() or "10")),
            backend=os.getenv("MEMORY_BACKEND", "file").strip().lower(),
            data_dir=data_dir,
            file_store_path=file_store_path,
            mem0_qdrant_host=os.getenv("MEM0_QDRANT_HOST", "127.0.0.1").strip(),
            mem0_qdrant_port=max(1, int(os.getenv("MEM0_QDRANT_PORT", "6333").strip() or "6333")),
            mem0_qdrant_collection=os.getenv("MEM0_QDRANT_COLLECTION", "mem0").strip(),
            mem0_qdrant_on_disk=_as_bool(os.getenv("MEM0_QDRANT_ON_DISK"), True),
            mem0_history_db_path=mem0_history_db_path,
            mem0_llm_provider=os.getenv("MEM0_LLM_PROVIDER", "openai").strip(),
            mem0_llm_model=os.getenv("MEM0_LLM_MODEL", "gpt-4.1-mini").strip(),
            mem0_embedder_provider=os.getenv("MEM0_EMBEDDER_PROVIDER", "openai").strip(),
            mem0_embedder_model=os.getenv("MEM0_EMBEDDER_MODEL", "text-embedding-3-small").strip(),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.mem0_history_db_path.parent.mkdir(parents=True, exist_ok=True)
