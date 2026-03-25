from __future__ import annotations

from dataclasses import dataclass

from bot_logic import BOT_TRIGGER, BOT_USERNAME, looks_like_prompt_injection, sanitize_user_text, strip_trigger


@dataclass
class IncomingMessageData:
    raw_text: str
    text: str
    clean_viewer_message: str
    author: str
    msg_id: str | None


def build_incoming_message_data(payload) -> IncomingMessageData:
    raw_text = payload.text or ""
    text = sanitize_user_text(raw_text)
    return IncomingMessageData(
        raw_text=raw_text,
        text=text,
        clean_viewer_message=sanitize_user_text(strip_trigger(text)),
        author=(payload.chatter.name or "").lower(),
        msg_id=getattr(payload, "id", None),
    )


def log_incoming_message(payload, incoming: IncomingMessageData) -> None:
    print("--------------------------------------------------", flush=True)
    print("💬 MESSAGE REÇU", flush=True)
    print(f"Chaîne : {payload.broadcaster.name}", flush=True)
    print(f"Auteur : {payload.chatter.name}", flush=True)
    print(f"Texte brut : {incoming.raw_text}", flush=True)
    print(f"Texte  : {incoming.text}", flush=True)


def should_ignore_incoming_message(*, incoming: IncomingMessageData, recent_ids, injection_checker=looks_like_prompt_injection) -> bool:
    if incoming.msg_id and incoming.msg_id in recent_ids:
        print("↪️ Message déjà traité, ignoré", flush=True)
        return True

    if incoming.msg_id:
        recent_ids.append(incoming.msg_id)

    if not incoming.author:
        print("↪️ Auteur vide, ignoré", flush=True)
        return True

    if incoming.author == BOT_USERNAME:
        print("↪️ Message ignoré : envoyé par le bot", flush=True)
        return True

    if BOT_TRIGGER not in incoming.text.lower():
        print("↪️ Pas de mention du bot, ignoré", flush=True)
        return True

    if injection_checker(incoming.text):
        print("↪️ Tentative probable de prompt injection, ignorée", flush=True)
        return True

    return False
