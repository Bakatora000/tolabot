import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import requests

from admin_client import admin_healthcheck, is_admin_ui_enabled
from bot_config import AppConfig, load_config
from bot_logic import CHAT_MEMORY_FILE, clear_chat_memory, clear_chat_memory_viewer, get_chat_memory_stats
from memory_client import healthcheck_memory_api, is_mem0_enabled
from ollama_client import get_installed_models
from twitch_auth import refresh_access_token, run_oauth_flow

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
PID_FILE = LOGS_DIR / "bot.pid"
LOG_FILE = LOGS_DIR / "bot.log"
CHAT_MEMORY_PATH = BASE_DIR / CHAT_MEMORY_FILE
ENV_PATH = BASE_DIR / ".env"


def bool_label(value: bool) -> str:
    return "OK" if value else "MANQUANT"


def print_config_status(config: AppConfig) -> None:
    print("=== Configuration ===")
    print(f"TWITCH_CLIENT_ID     : {bool_label(bool(config.client_id))}")
    print(f"TWITCH_CLIENT_SECRET : {bool_label(bool(config.client_secret))}")
    print(f"TWITCH_BOT_ID        : {config.bot_id or '(vide)'}")
    print(f"TWITCH_OWNER_ID      : {config.owner_id or '(vide)'}")
    print(f"TWITCH_CHANNEL       : {config.channel_name or '(vide)'}")
    print(f"TWITCH_TOKEN         : {bool_label(bool(config.bot_token))}")
    print(f"TWITCH_REFRESH_TOKEN : {bool_label(bool(config.refresh_token))}")
    print(f"OLLAMA_URL           : {config.ollama_url}")
    print(f"OLLAMA_MODEL défaut  : {config.default_ollama_model}")
    print(f"GLOBAL_COOLDOWN      : {config.global_cooldown_seconds}s")
    print(f"USER_COOLDOWN        : {config.user_cooldown_seconds}s")
    print(f"CHAT_MEMORY_TTL_HOURS: {config.chat_memory_ttl_hours}")
    print(f"DEBUG_CHAT_MEMORY    : {bool_label(config.debug_chat_memory)}")
    print(f"MEM0_ENABLED         : {bool_label(config.mem0_enabled)}")
    print(f"MEM0_API_BASE_URL    : {config.mem0_api_base_url or '(vide)'}")
    print(f"MEM0_API_KEY         : {bool_label(bool(config.mem0_api_key))}")
    print(f"MEM0_TIMEOUT_SECONDS : {config.mem0_timeout_seconds}s")
    print(f"MEM0_VERIFY_SSL      : {bool_label(config.mem0_verify_ssl)}")
    print(f"MEM0_CONTEXT_LIMIT   : {config.mem0_context_limit}")
    print(f"MEM0_FALLBACK_LOCAL  : {bool_label(config.mem0_fallback_local)}")
    print(f"MESSAGE_QUEUE_SIZE   : {config.message_queue_max_size}")
    print(f"MESSAGE_QUEUE_MAX_AGE: {config.message_queue_max_age_seconds}s")
    print(f"ADMIN_UI_ENABLED     : {bool_label(config.admin_ui_enabled)}")
    print(f"ADMIN_API_LOCAL_URL  : {config.admin_api_local_url}")
    print(f"MEM0_ADMIN_KEY       : {bool_label(bool(config.admin_api_key))}")
    print(f"ADMIN_API_TIMEOUT    : {config.admin_api_timeout_seconds}s")
    print(f"ADMIN_SSH_HOST       : {config.admin_ssh_host or '(vide)'}")
    print(f"ADMIN_SSH_USER       : {config.admin_ssh_user or '(vide)'}")
    print(f"ADMIN_SSH_LOCAL_PORT : {config.admin_ssh_local_port}")
    print(f"ADMIN_SSH_REMOTE_PORT: {config.admin_ssh_remote_port}")
    print(f"ADMIN_UI_BIND        : {config.admin_ui_host}:{config.admin_ui_port}")
    print(f"OPENAI_REVIEW_ENABLED: {bool_label(config.openai_review_enabled)}")
    print(f"OPENAI_API_KEY       : {bool_label(bool(config.openai_api_key))}")
    print(f"OPENAI_REVIEW_MODEL  : {config.openai_review_model}")
    print(f"OPENAI_REVIEW_TIMEOUT: {config.openai_review_timeout_seconds}s")
    print(f"OPENAI_REVIEW_MAXREC : {config.openai_review_max_records}")


def validate_twitch_token(config: AppConfig, timeout: int = 15, allow_refresh: bool = True) -> int:
    print("=== Validation Twitch ===")
    expected_scopes = {"user:read:chat", "user:write:chat"}

    if not config.bot_token:
        print("❌ TWITCH_TOKEN manquant dans le .env")
        return 1

    headers = {"Authorization": f"OAuth {config.bot_token}"}

    try:
        response = requests.get("https://id.twitch.tv/oauth2/validate", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        print(f"❌ Impossible de valider le token Twitch : {exc}")
        return 1

    if response.status_code != 200:
        if response.status_code == 401 and allow_refresh and config.refresh_token:
            print("⚠️ Token Twitch expiré, tentative de refresh automatique...")
            refreshed = refresh_access_token(
                config.client_id,
                config.client_secret,
                config.refresh_token,
                env_path=str(ENV_PATH),
                timeout=timeout,
            )
            if refreshed:
                refreshed_config = load_config()
                return validate_twitch_token(refreshed_config, timeout=timeout, allow_refresh=False)

        print(f"❌ Token invalide ou expiré ({response.status_code})")
        return 1

    data = response.json()
    print(f"✅ Token valide pour le compte : {data.get('login', '?')}")
    print(f"🆔 Client ID du token         : {data.get('client_id', '?')}")
    print(f"🤖 User ID du bot             : {data.get('user_id', '?')}")
    print(f"📜 Scopes                     : {data.get('scopes', [])}")

    token_scopes = set(data.get("scopes", []))
    missing_scopes = expected_scopes - token_scopes
    if missing_scopes:
        print(f"❌ Scopes Twitch manquants pour EventSub WebSocket : {sorted(missing_scopes)}")
        return 1

    if config.client_id and data.get("client_id") != config.client_id:
        print("⚠️ Le Client ID du token ne correspond pas à celui du .env")
        return 1

    return 0


def check_ollama_api(config: AppConfig, timeout: int = 5) -> int:
    print("=== Ollama API ===")
    tags_url = config.ollama_url.rsplit("/api/chat", 1)[0] + "/api/tags"

    try:
        response = requests.get(tags_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"❌ Ollama inaccessible via {tags_url}: {exc}")
        return 1

    models = [model.get("name", "?") for model in response.json().get("models", [])]
    print(f"✅ Ollama répond sur {tags_url}")
    if models:
        print("Modèles exposés par l'API :")
        for model in models:
            print(f" - {model}")
    else:
        print("⚠️ Aucun modèle exposé par l'API")
    return 0


def print_local_models() -> int:
    print("=== Modèles Ollama locaux ===")
    models = get_installed_models()
    if not models:
        print("⚠️ Aucun modèle détecté via 'ollama list'")
        return 1

    for model in models:
        print(f" - {model}")
    return 0


def check_mem0_api(config: AppConfig) -> int:
    print("=== API mémoire mem0 ===")

    if not config.mem0_enabled:
        print("ℹ️ Mem0 désactivé dans le .env")
        return 0

    if not is_mem0_enabled(config):
        print("❌ Configuration mem0 incomplète")
        return 1

    try:
        if healthcheck_memory_api(config):
            print(f"✅ API mémoire joignable via {config.mem0_api_base_url}/health")
            return 0
    except Exception as exc:
        print(f"❌ API mémoire inaccessible : {exc}")
        return 1

    print("❌ Healthcheck mem0 inattendu")
    return 1


def check_admin_api(config: AppConfig) -> int:
    print("=== API admin mem0 ===")

    if not config.admin_ui_enabled:
        print("ℹ️ Admin UI désactivée dans le .env")
        return 0

    if not is_admin_ui_enabled(config):
        print("❌ Configuration admin incomplète")
        return 1

    try:
        if admin_healthcheck(config):
            print(f"✅ API admin joignable via {config.admin_api_local_url}/admin/health")
            return 0
    except Exception as exc:
        print(f"❌ API admin inaccessible : {exc}")
        return 1

    print("❌ Healthcheck admin inattendu")
    return 1


def run_diagnose(config: AppConfig) -> int:
    print_config_status(config)
    print()

    exit_codes = [validate_twitch_token(config), check_ollama_api(config), print_local_models(), check_mem0_api(config), check_admin_api(config)]
    return 0 if all(code == 0 for code in exit_codes) else 1


async def run_bot() -> int:
    from bot_ollama import main

    await main()
    return 0


async def run_bot_ollama_only(config: AppConfig) -> int:
    from bot_ollama import run_with_model

    await run_with_model(config.default_ollama_model)
    return 0


def run_admin_ui_command(config: AppConfig) -> int:
    from admin_ui import run_admin_ui

    return run_admin_ui(config=config)


def ensure_runtime_config(config: AppConfig) -> AppConfig | None:
    validation_code = validate_twitch_token(config)
    if validation_code != 0:
        return None
    return load_config()


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False

        output = result.stdout.strip()
        if not output or output.startswith("INFO:"):
            return False
        return f'"{pid}"' in output

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None

    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def run_ollama_in_background(config: AppConfig) -> int:
    LOGS_DIR.mkdir(exist_ok=True)

    existing_pid = read_pid()
    if existing_pid and is_process_running(existing_pid):
        print(f"⚠️ Le bot semble déjà lancé en arrière-plan (PID {existing_pid}).")
        print(f"Logs : {LOG_FILE}")
        return 1

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    command = [sys.executable, str(BASE_DIR / "manage_bot.py"), "run-ollama"]

    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
        )

    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    print(f"✅ Bot Ollama lancé en arrière-plan (PID {process.pid})")
    print(f"Provider/modèle utilisés sans prompt : ollama / {config.default_ollama_model}")
    print(f"Logs : {LOG_FILE}")
    print(f"PID  : {PID_FILE}")
    return 0


def print_background_status() -> int:
    pid = read_pid()
    if not pid:
        print("ℹ️ Aucun PID enregistré pour le bot en arrière-plan.")
        print(f"PID  : {PID_FILE}")
        return 1

    running = is_process_running(pid)
    if running:
        print(f"✅ Bot actif en arrière-plan (PID {pid})")
        print(f"Logs : {LOG_FILE}")
        return 0

    print(f"⚠️ PID enregistré mais process absent (PID {pid})")
    print(f"PID  : {PID_FILE}")
    print(f"Logs : {LOG_FILE}")
    if confirm_cleanup_stale_pid(pid):
        return clean_background_state()
    return 1


def stop_background_process() -> int:
    pid = read_pid()
    if not pid:
        print("ℹ️ Aucun bot en arrière-plan à arrêter.")
        return 1

    if not is_process_running(pid):
        print(f"⚠️ Le process {pid} n'est déjà plus actif.")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 1

    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                print(f"❌ Impossible d'arrêter le bot (PID {pid}).")
                if result.stdout.strip():
                    print(result.stdout.strip())
                if result.stderr.strip():
                    print(result.stderr.strip())
                return 1
        else:
            os.kill(pid, 15)
    except OSError as exc:
        print(f"❌ Impossible d'arrêter le bot (PID {pid}) : {exc}")
        return 1

    try:
        PID_FILE.unlink()
    except OSError:
        pass

    print(f"✅ Bot arrêté (PID {pid})")
    return 0


def restart_background_process(config: AppConfig) -> int:
    existing_pid = read_pid()
    if existing_pid and is_process_running(existing_pid):
        stop_code = stop_background_process()
        if stop_code != 0:
            return stop_code
    return run_ollama_in_background(config)


def clean_background_state() -> int:
    removed = []

    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
            removed.append(str(PID_FILE))
        except OSError as exc:
            print(f"❌ Impossible de supprimer {PID_FILE} : {exc}")
            return 1

    if not removed:
        print("ℹ️ Aucun état background à nettoyer.")
        return 0

    print("✅ État background nettoyé :")
    for path in removed:
        print(f" - {path}")
    return 0


def clear_chat_memory_command(config: AppConfig, viewer_name: str | None = None) -> int:
    if viewer_name:
        cleared = clear_chat_memory_viewer(
            config.channel_name,
            viewer_name,
            chat_memory_file=str(CHAT_MEMORY_PATH),
            ttl_hours=config.chat_memory_ttl_hours,
        )
        if not cleared:
            print(f"ℹ️ Aucun historique trouvé pour le viewer '{viewer_name}' sur la chaîne '{config.channel_name}'.")
            return 1
        print(
            f"✅ Mémoire du viewer '{viewer_name}' vidée pour la chaîne '{config.channel_name}' : {CHAT_MEMORY_PATH}"
        )
        return 0

    clear_chat_memory(str(CHAT_MEMORY_PATH))
    print(f"✅ Mémoire de conversation vidée : {CHAT_MEMORY_PATH}")
    return 0


def print_chat_memory_status(config: AppConfig) -> int:
    stats = get_chat_memory_stats(
        chat_memory_file=str(CHAT_MEMORY_PATH),
        ttl_hours=config.chat_memory_ttl_hours,
    )

    print("=== Mémoire de conversation ===")
    print(f"Fichier            : {CHAT_MEMORY_PATH}")
    print(f"TTL actif          : {stats['ttl_hours']} heure(s)")
    print(f"Chaînes en mémoire : {stats['channel_count']}")
    print(f"Tours globaux      : {stats['total_turns']}")
    print(f"Charades vues      : {stats['riddle_messages_seen']}")
    print(f"Aides mémoire      : {stats['memory_helpful_replies']}")

    if not stats["channels"]:
        print("ℹ️ Aucune conversation mémorisée.")
        return 0

    for channel in stats["channels"]:
        print(f"- Chaîne #{channel['channel']}: {channel['global_turns']} tour(s), {channel['viewer_count']} viewer(s)")
        if channel["per_viewer_counts"]:
            viewers = ", ".join(
                f"{viewer} ({count})"
                for viewer, count in channel["per_viewer_counts"].items()
            )
            print(f"  Viewers : {viewers}")

    return 0


def confirm_cleanup_stale_pid(pid: int) -> bool:
    prompt = f"Supprimer l'entrée stale du bot en arrière-plan (PID {pid}) ? [o/N] : "
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in {"o", "oui", "y", "yes"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outils de lancement et de diagnostic du bot Twitch/Ollama.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in (
        "status",
        "diagnose",
        "validate-token",
        "ollama-models",
        "get-token",
        "memory-health",
        "admin-health",
        "run-admin-ui",
        "run-ollama",
        "run-bg-ollama",
        "status-bg",
        "stop-bg",
        "restart-bg",
        "clean-bg",
        "chat-memory-status",
    ):
        subparsers.add_parser(name)

    clear_chat_memory_parser = subparsers.add_parser("clear-chat-memory")
    clear_chat_memory_parser.add_argument("--viewer", dest="viewer_name", default=None)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    try:
        if args.command == "status":
            print_config_status(config)
            return 0
        if args.command == "diagnose":
            return run_diagnose(config)
        if args.command == "validate-token":
            return validate_twitch_token(config)
        if args.command == "ollama-models":
            return print_local_models()
        if args.command == "get-token":
            return run_oauth_flow(config.client_id, config.client_secret, env_path=str(ENV_PATH))
        if args.command == "memory-health":
            return check_mem0_api(config)
        if args.command == "admin-health":
            return check_admin_api(config)
        if args.command == "run-admin-ui":
            return run_admin_ui_command(config)
        if args.command == "run-ollama":
            runtime_config = ensure_runtime_config(config)
            if not runtime_config:
                return 1
            return asyncio.run(run_bot_ollama_only(runtime_config))
        if args.command == "run-bg-ollama":
            runtime_config = ensure_runtime_config(config)
            if not runtime_config:
                return 1
            return run_ollama_in_background(runtime_config)
        if args.command == "status-bg":
            return print_background_status()
        if args.command == "stop-bg":
            return stop_background_process()
        if args.command == "restart-bg":
            return restart_background_process(config)
        if args.command == "clean-bg":
            return clean_background_state()
        if args.command == "chat-memory-status":
            return print_chat_memory_status(config)
        if args.command == "clear-chat-memory":
            return clear_chat_memory_command(config, viewer_name=args.viewer_name)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur")
        return 130

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
