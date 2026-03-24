from pathlib import Path

from bot_config import load_config
from twitch_auth import run_oauth_flow


def main() -> int:
    config = load_config()
    env_path = str(Path(__file__).resolve().parent / ".env")
    return run_oauth_flow(config.client_id, config.client_secret, env_path=env_path)


if __name__ == "__main__":
    raise SystemExit(main())
