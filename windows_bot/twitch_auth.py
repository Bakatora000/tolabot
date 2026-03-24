import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests


REDIRECT_URI = "http://localhost:4343/oauth/callback"
SCOPES = "user:read:chat user:write:chat"


def update_env_value(env_path: str, key: str, value: str) -> None:
    line = f"{key}={value}"

    if not env_path:
        return

    try:
        with open(env_path, "r", encoding="utf-8") as file_obj:
            lines = file_obj.read().splitlines()
    except FileNotFoundError:
        lines = []

    updated = False
    new_lines = []
    for existing in lines:
        if existing.startswith(f"{key}="):
            new_lines.append(line)
            updated = True
        else:
            new_lines.append(existing)

    if not updated:
        new_lines.append(line)

    with open(env_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(new_lines).rstrip() + "\n")


def validate_access_token(access_token: str, timeout: int = 30) -> requests.Response:
    return requests.get(
        "https://id.twitch.tv/oauth2/validate",
        headers={"Authorization": f"OAuth {access_token}"},
        timeout=timeout,
    )


def persist_token_bundle(
    env_path: str | None,
    access_token: str,
    refresh_token: str,
    validation_data: dict | None = None,
) -> None:
    if not env_path:
        return

    if access_token:
        update_env_value(env_path, "TWITCH_TOKEN", f"oauth:{access_token}")
    if refresh_token:
        update_env_value(env_path, "TWITCH_REFRESH_TOKEN", refresh_token)

    if validation_data:
        bot_id = validation_data.get("user_id", "")
        if bot_id:
            update_env_value(env_path, "TWITCH_BOT_ID", bot_id)


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    env_path: str | None = None,
    timeout: int = 30,
) -> dict | None:
    if not client_id or not client_secret or not refresh_token:
        print("❌ Refresh Twitch impossible : client_id, client_secret ou refresh_token manquant.")
        return None

    response = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=timeout,
    )

    data = response.json()
    if not response.ok:
        print(f"❌ Échec du refresh Twitch ({response.status_code})")
        print(data)
        return None

    new_access_token = data.get("access_token", "")
    new_refresh_token = data.get("refresh_token", refresh_token)
    if not new_access_token:
        print("❌ Refresh Twitch invalide : access_token absent.")
        return None

    validation = validate_access_token(new_access_token, timeout=timeout)
    validation_data = validation.json() if validation.ok else None
    persist_token_bundle(env_path, new_access_token, new_refresh_token, validation_data=validation_data)

    print("✅ TWITCH_TOKEN rafraîchi automatiquement")
    if env_path:
        print(f"✅ TWITCH_TOKEN/TWITCH_REFRESH_TOKEN mis à jour dans {env_path}")

    if validation_data:
        print(f"🤖 Compte token     : {validation_data.get('login', '')}")
        print(f"🆔 TWITCH_BOT_ID    : {validation_data.get('user_id', '')}")
        print(f"📜 Scopes           : {validation_data.get('scopes', [])}")

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "validation_data": validation_data or {},
    }


def run_oauth_flow(client_id: str, client_secret: str, bot_username: str = "anneaunimouss", env_path: str | None = None) -> int:
    auth_code = {"value": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/oauth/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query_string = parse_qs(parsed.query)
            auth_code["value"] = query_string.get("code", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Autorisation recue. Vous pouvez fermer cette fenetre.</h1>")

        def log_message(self, format, *args):
            return

    def run_server():
        server = HTTPServer(("localhost", 4343), CallbackHandler)
        server.handle_request()

    if not client_id or not client_secret:
        print("TWITCH_CLIENT_ID ou TWITCH_CLIENT_SECRET manquant dans le .env")
        return 1

    authorize_url = (
        "https://id.twitch.tv/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        f"&scope={SCOPES.replace(' ', '%20')}"
        "&force_verify=true"
    )

    print(f"Lancement du serveur local sur {REDIRECT_URI}")
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    print("Ouverture du navigateur...")
    webbrowser.open(authorize_url)

    print(f"Connecte-toi avec le compte bot '{bot_username}' et accepte les permissions.")
    thread.join(timeout=300)

    if not auth_code["value"]:
        print("Aucun code OAuth recu.")
        return 1

    print("Code recu, echange contre un token...")

    response = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": auth_code["value"],
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )

    print("Status:", response.status_code)
    data = response.json()
    print(data)

    if not response.ok:
        return 1

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    if access_token:
        print(f"✅ Nouveau TWITCH_TOKEN obtenu pour le compte bot '{bot_username}'")

        validation = validate_access_token(access_token, timeout=30)
        validation_data = validation.json() if validation.ok else None
        persist_token_bundle(env_path, access_token, refresh_token, validation_data=validation_data)

        if env_path:
            print(f"✅ TWITCH_TOKEN mis à jour dans {env_path}")
            if refresh_token:
                print(f"✅ TWITCH_REFRESH_TOKEN mis à jour dans {env_path}")

        if validation_data:
            bot_id = validation_data.get("user_id", "")
            login = validation_data.get("login", "")
            scopes = validation_data.get("scopes", [])
            print(f"🤖 Compte token     : {login}")
            print(f"🆔 TWITCH_BOT_ID    : {bot_id}")
            print(f"📜 Scopes           : {scopes}")
            if env_path and bot_id:
                print(f"✅ TWITCH_BOT_ID mis à jour dans {env_path}")

    return 0
