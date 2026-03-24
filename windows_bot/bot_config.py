import os
from dataclasses import dataclass

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
    request_timeout_seconds: int = 90
    chat_memory_ttl_hours: int = 10
    debug_chat_memory: bool = False
    global_cooldown_seconds: int = 2
    user_cooldown_seconds: int = 8
    mem0_enabled: bool = False
    mem0_api_base_url: str = ""
    mem0_api_key: str = ""
    mem0_timeout_seconds: int = 10
    mem0_verify_ssl: bool = True
    mem0_context_limit: int = 5
    mem0_fallback_local: bool = True
    message_queue_max_size: int = 6
    message_queue_max_age_seconds: int = 25
    admin_ui_enabled: bool = False
    admin_api_local_url: str = "http://127.0.0.1:9000"
    admin_api_key: str = ""
    admin_api_timeout_seconds: int = 10
    admin_ssh_host: str = ""
    admin_ssh_user: str = ""
    admin_ssh_local_port: int = 9000
    admin_ssh_remote_port: int = 8000
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
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat").strip(),
        default_ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:latest").strip(),
        chat_memory_ttl_hours=max(1, int(os.getenv("CHAT_MEMORY_TTL_HOURS", "10").strip() or "10")),
        debug_chat_memory=os.getenv("DEBUG_CHAT_MEMORY", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        global_cooldown_seconds=max(0, int(os.getenv("GLOBAL_COOLDOWN_SECONDS", "2").strip() or "2")),
        user_cooldown_seconds=max(0, int(os.getenv("USER_COOLDOWN_SECONDS", "8").strip() or "8")),
        mem0_enabled=os.getenv("MEM0_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        mem0_api_base_url=os.getenv("MEM0_API_BASE_URL", "").strip().rstrip("/"),
        mem0_api_key=os.getenv("MEM0_API_KEY", "").strip(),
        mem0_timeout_seconds=max(1, int(os.getenv("MEM0_TIMEOUT_SECONDS", "10").strip() or "10")),
        mem0_verify_ssl=os.getenv("MEM0_VERIFY_SSL", "true").strip().lower() in {"1", "true", "yes", "oui", "on"},
        mem0_context_limit=max(1, int(os.getenv("MEM0_CONTEXT_LIMIT", "5").strip() or "5")),
        mem0_fallback_local=os.getenv("MEM0_FALLBACK_LOCAL", "true").strip().lower() in {"1", "true", "yes", "oui", "on"},
        message_queue_max_size=max(1, int(os.getenv("MESSAGE_QUEUE_MAX_SIZE", "6").strip() or "6")),
        message_queue_max_age_seconds=max(5, int(os.getenv("MESSAGE_QUEUE_MAX_AGE_SECONDS", "25").strip() or "25")),
        admin_ui_enabled=os.getenv("ADMIN_UI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        admin_api_local_url=os.getenv("ADMIN_API_LOCAL_URL", "http://127.0.0.1:9000").strip().rstrip("/"),
        admin_api_key=os.getenv("MEM0_ADMIN_KEY", "").strip(),
        admin_api_timeout_seconds=max(1, int(os.getenv("ADMIN_API_TIMEOUT_SECONDS", "10").strip() or "10")),
        admin_ssh_host=os.getenv("ADMIN_SSH_HOST", "").strip(),
        admin_ssh_user=os.getenv("ADMIN_SSH_USER", "").strip(),
        admin_ssh_local_port=max(1, int(os.getenv("ADMIN_SSH_LOCAL_PORT", "9000").strip() or "9000")),
        admin_ssh_remote_port=max(1, int(os.getenv("ADMIN_SSH_REMOTE_PORT", "8000").strip() or "8000")),
        admin_ui_host=os.getenv("ADMIN_UI_HOST", "127.0.0.1").strip(),
        admin_ui_port=max(1, int(os.getenv("ADMIN_UI_PORT", "9100").strip() or "9100")),
        openai_review_enabled=os.getenv("OPENAI_REVIEW_ENABLED", "false").strip().lower() in {"1", "true", "yes", "oui", "on"},
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_review_model=os.getenv("OPENAI_REVIEW_MODEL", "gpt-5-mini").strip(),
        openai_review_timeout_seconds=max(5, int(os.getenv("OPENAI_REVIEW_TIMEOUT_SECONDS", "90").strip() or "90")),
        openai_review_max_records=max(1, int(os.getenv("OPENAI_REVIEW_MAX_RECORDS", "50").strip() or "50")),
    )
