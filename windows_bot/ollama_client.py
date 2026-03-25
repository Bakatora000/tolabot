import subprocess

import requests

from bot_logic import MAX_INPUT_CHARS, build_messages, normalize_spaces, strip_trigger, sanitize_user_text
from web_search_client import should_enable_web_search


def get_installed_models() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.splitlines()
        models = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            model_name = line.split()[0].strip()
            if model_name:
                models.append(model_name)
        return models
    except FileNotFoundError:
        print("❌ La commande 'ollama' est introuvable dans le PATH.", flush=True)
        return []
    except subprocess.CalledProcessError as exc:
        print(f"❌ Erreur pendant 'ollama list' : {exc}", flush=True)
        return []


def install_model(model_name: str) -> bool:
    try:
        print(f"⏳ Installation du modèle '{model_name}'...", flush=True)
        result = subprocess.run(
            ["ollama", "pull", model_name],
            text=True,
            check=True,
        )
        print(f"✅ Modèle installé : {model_name}", flush=True)
        return result.returncode == 0
    except FileNotFoundError:
        print("❌ La commande 'ollama' est introuvable dans le PATH.", flush=True)
        return False
    except subprocess.CalledProcessError:
        print(f"❌ Échec de l'installation de '{model_name}'", flush=True)
        return False


def _extract_openai_output_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return ""


def choose_model(default_ollama_model: str, provider: str = "ollama", openai_chat_model: str = "gpt-5-mini") -> str:
    if provider == "openai":
        print("==================================================", flush=True)
        print("Choix du modèle OpenAI", flush=True)
        print(f"Modèle configuré (.env) : {openai_chat_model}", flush=True)
        print("==================================================", flush=True)
        return openai_chat_model

    while True:
        installed_models = get_installed_models()

        print("==================================================", flush=True)
        print("Choix du modèle Ollama", flush=True)
        print(f"Modèle par défaut (.env) : {default_ollama_model}", flush=True)

        if installed_models:
            print("Modèles installés :", flush=True)
            for model in installed_models:
                print(f" - {model}", flush=True)
        else:
            print("⚠️ Aucun modèle détecté ou lecture impossible.", flush=True)

        print("Appuie sur Entrée pour garder le modèle par défaut.", flush=True)
        model = input("Modèle à utiliser : ").strip()

        if not model:
            model = default_ollama_model

        if model in installed_models:
            print(f"✅ Modèle sélectionné : {model}", flush=True)
            print("==================================================", flush=True)
            return model

        print(f"⚠️ Le modèle '{model}' n'est pas installé localement.", flush=True)
        answer = input(f"Voulez-vous l'installer maintenant ? (o/n) : ").strip().lower()

        if answer in ("o", "oui", "y", "yes") and install_model(model):
            print(f"✅ Modèle sélectionné : {model}", flush=True)
            print("==================================================", flush=True)
            return model

        print("↪️ On recommence.", flush=True)


def summarize_channel_profile(
    profile: dict,
    ollama_url: str,
    ollama_model: str,
    request_timeout_seconds: int,
    provider: str = "ollama",
    openai_api_key: str = "",
) -> str:
    top_categories = profile.get("top_categories", [])
    recent_titles = profile.get("recent_titles", [])

    if not top_categories and not recent_titles:
        return "Je n'ai pas encore assez d'historique local pour résumer correctement la chaîne."

    categories_text = "\n".join([f"- {name}: {count} fois" for name, count in top_categories]) or "- aucune"
    titles_text = "\n".join([f"- {title}" for title in recent_titles]) or "- aucun"

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es anneaunimouss, un bot Twitch francophone. "
                "Tu reçois un historique local de la chaîne, avec des catégories de stream et des titres récents. "
                "Tu dois résumer le contenu habituel de la chaîne en 2 phrases maximum, de façon simple, factuelle et naturelle. "
                "Appuie-toi d'abord sur les catégories dominantes, puis sur les titres. "
                "N'invente rien au-delà de ce que suggèrent clairement les données."
            ),
        },
        {
            "role": "user",
            "content": (
                "Catégories dominantes observées :\n"
                f"{categories_text}\n\n"
                "Titres récents observés :\n"
                f"{titles_text}\n\n"
                "Résume le contenu habituel de cette chaîne."
            ),
        },
    ]

    if provider == "openai":
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": ollama_model,
                "input": messages,
            },
            timeout=request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return normalize_spaces(_extract_openai_output_text(data))

    payload = {
        "model": ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
    }

    response = requests.post(ollama_url, json=payload, timeout=request_timeout_seconds)
    response.raise_for_status()
    data = response.json()
    return normalize_spaces(data.get("message", {}).get("content", ""))


def ask_ollama(
    user_name: str,
    message: str,
    ollama_url: str,
    ollama_model: str,
    request_timeout_seconds: int,
    viewer_context: str = "",
    global_context: str = "",
    web_context: str = "",
    conversation_mode: str = "",
    provider: str = "ollama",
    openai_api_key: str = "",
    openai_web_search_enabled: bool = False,
    openai_web_search_mode: str = "auto",
) -> str:
    clean_message = sanitize_user_text(strip_trigger(message))
    clean_message = clean_message[:MAX_INPUT_CHARS]

    messages = build_messages(
        user_name,
        clean_message,
        viewer_context=viewer_context,
        global_context=global_context,
        web_context=web_context,
        conversation_mode=conversation_mode,
    )

    if provider == "openai":
        print(f"DEBUG OPENAI_MODEL = {ollama_model!r}", flush=True)
        use_web_search = openai_web_search_enabled and should_enable_web_search(
            clean_message,
            viewer_context=viewer_context,
            global_context=global_context,
            mode=openai_web_search_mode,
        )
        print(f"DEBUG OPENAI_WEB_SEARCH = {use_web_search!r}", flush=True)
        payload = {
            "model": ollama_model,
            "input": messages,
        }
        if use_web_search:
            payload["tools"] = [{"type": "web_search"}]
            payload["tool_choice"] = "auto"
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=request_timeout_seconds,
        )
        print(f"DEBUG STATUS = {response.status_code}", flush=True)
        if response.status_code >= 400:
            print(f"DEBUG BODY   = {response.text}", flush=True)
        response.raise_for_status()
        data = response.json()
        return normalize_spaces(_extract_openai_output_text(data))

    payload = {
        "model": ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
    }

    print(f"DEBUG OLLAMA_URL   = {ollama_url!r}", flush=True)
    print(f"DEBUG OLLAMA_MODEL = {ollama_model!r}", flush=True)

    response = requests.post(ollama_url, json=payload, timeout=request_timeout_seconds)

    print(f"DEBUG STATUS = {response.status_code}", flush=True)
    if response.status_code >= 400:
        print(f"DEBUG BODY   = {response.text}", flush=True)

    response.raise_for_status()
    data = response.json()
    return normalize_spaces(data.get("message", {}).get("content", ""))
