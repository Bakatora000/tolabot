import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    client_secret: str
    bot_id: str
    owner_id: str
    bot_token: str
    refresh_token: str
    channel_name: str
    ollama_url: str
    default_ollama_model: str
    llm_provider: str = "ollama"
    openai_chat_model: str = "gpt-5-mini"
    openai_web_search_enabled: bool = False
    openai_web_search_mode: str = "auto"
    web_search_enabled: bool = False
    web_search_provider: str = "searxng"
    web_search_mode: str = "auto"
    web_search_timeout_seconds: int = 8
    web_search_max_results: int = 5
    searxng_base_url: str = "http://127.0.0.1:8888"
    request_timeout_seconds: int = 90
    chat_memory_ttl_hours: int = 10
    debug_chat_memory: bool = False
    global_cooldown_seconds: int = 2
    user_cooldown_seconds: int = 8
    mem0_context_limit: int = 5
    mem0_local_backend_enabled: bool = True
    message_queue_max_size: int = 6
    message_queue_max_age_seconds: int = 25
    admin_ui_enabled: bool = False
    homegraph_local_enabled: bool = False
    homegraph_db_path: str = str((Path(__file__).resolve().parent.parent / "homegraph" / "data" / "homegraph.sqlite3"))
    admin_ui_host: str = "127.0.0.1"
    admin_ui_port: int = 9100
    openai_review_enabled: bool = False
    openai_api_key: str = ""
    openai_review_model: str = "gpt-5-mini"
    openai_review_timeout_seconds: int = 90
    openai_review_max_records: int = 50


def load_config() -> AppConfig:
    load_dotenv(override=True)

    return AppConfig(
        client_id=os.getenv("TWITCH_CLIENT_ID", "").strip(),
        client_secret=os.getenv("TWITCH_CLIENT_SECRET", "").strip(),
        bot_id=os.getenv("TWITCH_BOT_ID", "").strip(),
        owner_id=os.getenv("TWITCH_OWNER_ID", "").strip(),
        bot_token=os.getenv("TWITCH_TOKEN", "").strip().replace("oauth:", "", 1),
        refresh_token=os.getenv("TWITCH_REFRESH_TOKEN", "").strip(),
        channel_name=os.getenv("TWITCH_CHANNEL", "").strip().lower(),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama",
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat").strip(),
        default_ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:latest").strip(),
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini").strip(),
        openai_web_search_enabled=os.getenv("OPENAI_WEB_SEARCH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        openai_web_search_mode=os.getenv("OPENAI_WEB_SEARCH_MODE", "auto").strip().lower() or "auto",
        web_search_enabled=os.getenv("WEB_SEARCH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "searxng").strip().lower() or "searxng",
        web_search_mode=os.getenv("WEB_SEARCH_MODE", "auto").strip().lower() or "auto",
        web_search_timeout_seconds=max(1, int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "8").strip() or "8")),
        web_search_max_results=max(1, int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5").strip() or "5")),
        searxng_base_url=os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888").strip().rstrip("/"),
        chat_memory_ttl_hours=max(1, int(os.getenv("CHAT_MEMORY_TTL_HOURS", "10").strip() or "10")),
        debug_chat_memory=os.getenv("DEBUG_CHAT_MEMORY", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        global_cooldown_seconds=max(0, int(os.getenv("GLOBAL_COOLDOWN_SECONDS", "2").strip() or "2")),
        user_cooldown_seconds=max(0, int(os.getenv("USER_COOLDOWN_SECONDS", "8").strip() or "8")),
        mem0_context_limit=max(1, int(os.getenv("MEM0_CONTEXT_LIMIT", "5").strip() or "5")),
        mem0_local_backend_enabled=os.getenv("MEM0_LOCAL_BACKEND_ENABLED", "true").strip().lower() in {"1", "true", "yes", "oui", "on"},
        message_queue_max_size=max(1, int(os.getenv("MESSAGE_QUEUE_MAX_SIZE", "6").strip() or "6")),
        message_queue_max_age_seconds=max(5, int(os.getenv("MESSAGE_QUEUE_MAX_AGE_SECONDS", "25").strip() or "25")),
        admin_ui_enabled=os.getenv("ADMIN_UI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        homegraph_local_enabled=os.getenv("HOMEGRAPH_LOCAL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        homegraph_db_path=str(Path(os.getenv("HOMEGRAPH_DB_PATH", str(Path(__file__).resolve().parent.parent / "homegraph" / "data" / "homegraph.sqlite3"))).resolve()),
        admin_ui_host=os.getenv("ADMIN_UI_HOST", "127.0.0.1").strip(),
        admin_ui_port=max(1, int(os.getenv("ADMIN_UI_PORT", "9100").strip() or "9100")),
        openai_review_enabled=os.getenv("OPENAI_REVIEW_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_review_model=os.getenv("OPENAI_REVIEW_MODEL", "gpt-5-mini").strip(),
        openai_review_timeout_seconds=max(5, int(os.getenv("OPENAI_REVIEW_TIMEOUT_SECONDS", "90").strip() or "90")),
        openai_review_max_records=max(1, int(os.getenv("OPENAI_REVIEW_MAX_RECORDS", "50").strip() or "50")),
    )
