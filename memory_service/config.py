from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "oui"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    admin_key: str
    host: str = "127.0.0.1"
    port: int = 8000
    admin_host: str = "127.0.0.1"
    admin_port: int = 9000
    log_level: str = "INFO"
    default_limit: int = 5
    max_limit: int = 10
    admin_export_limit: int = 1000
    backend: str = "file"
    data_dir: Path = Path("./data")
    homegraph_db_path: Path = Path("./homegraph/data/homegraph.sqlite3")
    file_store_path: Path = Path("./data/memory_store.json")
    user_registry_path: Path = Path("./data/user_registry.json")
    mem0_qdrant_host: str = "127.0.0.1"
    mem0_qdrant_port: int = 6333
    mem0_qdrant_path: Path = Path("./data/qdrant")
    mem0_qdrant_url: str | None = None
    mem0_qdrant_api_key: str | None = None
    mem0_qdrant_collection: str = "mem0"
    mem0_qdrant_on_disk: bool = True
    mem0_history_db_path: Path = Path("./data/history.db")
    mem0_llm_provider: str = "lmstudio"
    mem0_llm_model: str = "dummy-local-model"
    mem0_lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    mem0_embedder_provider: str = "fastembed"
    mem0_embedder_model: str = "BAAI/bge-small-en-v1.5"
    mem0_embedder_dims: int = 384

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        file_store_path = Path(os.getenv("FILE_STORE_PATH", str(data_dir / "memory_store.json"))).resolve()
        homegraph_db_path = Path(
            os.getenv("HOMEGRAPH_DB_PATH", "./homegraph/data/homegraph.sqlite3")
        ).resolve()
        user_registry_path = Path(os.getenv("USER_REGISTRY_PATH", str(data_dir / "user_registry.json"))).resolve()
        mem0_history_db_path = Path(os.getenv("MEM0_HISTORY_DB_PATH", str(data_dir / "history.db"))).resolve()
        mem0_qdrant_path = Path(os.getenv("MEM0_QDRANT_PATH", str(data_dir / "qdrant"))).resolve()

        return cls(
            api_key=os.getenv("MEM0_API_KEY", "").strip(),
            admin_key=os.getenv("MEM0_ADMIN_KEY", "").strip(),
            host=os.getenv("MEM0_HOST", "127.0.0.1").strip(),
            port=max(1, int(os.getenv("MEM0_PORT", "8000").strip() or "8000")),
            admin_host=os.getenv("MEM0_ADMIN_HOST", "127.0.0.1").strip(),
            admin_port=max(1, int(os.getenv("MEM0_ADMIN_PORT", "9000").strip() or "9000")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            default_limit=max(1, int(os.getenv("MEM0_DEFAULT_LIMIT", "5").strip() or "5")),
            max_limit=max(1, int(os.getenv("MEM0_MAX_LIMIT", "10").strip() or "10")),
            admin_export_limit=max(1, int(os.getenv("MEM0_ADMIN_EXPORT_LIMIT", "1000").strip() or "1000")),
            backend=os.getenv("MEMORY_BACKEND", "file").strip().lower(),
            data_dir=data_dir,
            homegraph_db_path=homegraph_db_path,
            file_store_path=file_store_path,
            user_registry_path=user_registry_path,
            mem0_qdrant_host=os.getenv("MEM0_QDRANT_HOST", "127.0.0.1").strip(),
            mem0_qdrant_port=max(1, int(os.getenv("MEM0_QDRANT_PORT", "6333").strip() or "6333")),
            mem0_qdrant_path=mem0_qdrant_path,
            mem0_qdrant_url=(os.getenv("MEM0_QDRANT_URL", "").strip() or None),
            mem0_qdrant_api_key=(os.getenv("MEM0_QDRANT_API_KEY", "").strip() or None),
            mem0_qdrant_collection=os.getenv("MEM0_QDRANT_COLLECTION", "mem0").strip(),
            mem0_qdrant_on_disk=_as_bool(os.getenv("MEM0_QDRANT_ON_DISK"), True),
            mem0_history_db_path=mem0_history_db_path,
            mem0_llm_provider=os.getenv("MEM0_LLM_PROVIDER", "lmstudio").strip(),
            mem0_llm_model=os.getenv("MEM0_LLM_MODEL", "dummy-local-model").strip(),
            mem0_lmstudio_base_url=os.getenv("MEM0_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").strip(),
            mem0_embedder_provider=os.getenv("MEM0_EMBEDDER_PROVIDER", "fastembed").strip(),
            mem0_embedder_model=os.getenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-small-en-v1.5").strip(),
            mem0_embedder_dims=max(1, int(os.getenv("MEM0_EMBEDDER_DIMS", "384").strip() or "384")),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.homegraph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.mem0_history_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.mem0_qdrant_path.parent.mkdir(parents=True, exist_ok=True)
