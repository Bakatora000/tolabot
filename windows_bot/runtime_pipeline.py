from __future__ import annotations

from dataclasses import dataclass

from bot_logic import (
    BOT_TRIGGER,
    BOT_USERNAME,
    build_no_reply_fallback,
    is_no_reply_signal,
    looks_like_prompt_injection,
    sanitize_user_text,
    smart_truncate,
    strip_trigger,
)
from ollama_client import ask_ollama
from runtime_types import RuntimeContextBundle


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


async def send_channel_summary_reply(bot, payload, author: str, summary: str) -> None:
    outgoing_summary = bot.format_chat_reply(author, summary)
    print(f"📤 Envoi résumé chaîne : {outgoing_summary}", flush=True)
    await payload.broadcaster.send_message(
        outgoing_summary,
        sender=bot.bot_id,
        token_for=bot.bot_id,
    )
    bot.mark_replied(author)


def log_runtime_context(*, config, context_bundle: RuntimeContextBundle, prefer_active_thread: bool, riddle_thread_reset: bool) -> None:
    if not config.debug_chat_memory:
        return
    if (
        context_bundle.viewer_context == "aucun"
        and context_bundle.global_context == "aucun"
        and context_bundle.web_context == "aucun"
    ):
        return
    print("🧠 Contexte mémoire injecté", flush=True)
    if context_bundle.context_source == "local" and prefer_active_thread and not riddle_thread_reset:
        print("   Mode   : fil actif", flush=True)
    print(f"   Source : {context_bundle.context_source}", flush=True)
    if context_bundle.sources:
        print(
            f"   Trace  : {', '.join(source.source_id for source in context_bundle.sources)}",
            flush=True,
        )
    if context_bundle.viewer_context != "aucun":
        print(f"   Viewer : {context_bundle.viewer_context}", flush=True)
    if context_bundle.global_context != "aucun":
        print(f"   Global : {context_bundle.global_context}", flush=True)
    if context_bundle.web_context != "aucun":
        print(f"   Web    : {context_bundle.web_context}", flush=True)


async def generate_model_reply(*, payload, resolved_text: str, context_bundle: RuntimeContextBundle, config, model, ask_fn=ask_ollama) -> str:
    import asyncio

    return await asyncio.to_thread(
        ask_fn,
        payload.chatter.name,
        resolved_text,
        config.ollama_url,
        model,
        config.request_timeout_seconds,
        context_bundle.viewer_context,
        context_bundle.global_context,
        context_bundle.web_context,
        context_bundle.conversation_mode,
        config.llm_provider,
        config.openai_api_key,
        config.openai_web_search_enabled,
        config.openai_web_search_mode,
    )


def should_mark_memory_helpful(*, context_bundle: RuntimeContextBundle, resolved_text: str, memory_context_checker) -> bool:
    return context_bundle.viewer_context != "aucun" and memory_context_checker(resolved_text)


async def finalize_model_reply(
    *,
    payload,
    author: str,
    channel_name: str,
    clean_viewer_message: str,
    resolved_text: str,
    reply: str,
    msg_id: str | None,
    allow_remote: bool,
    author_is_owner: bool,
    event_type: str,
    related_viewer: str,
    related_message: str,
    reply_to_turn_id: str,
    related_turn_id: str,
    riddle_related: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    context_bundle: RuntimeContextBundle,
    max_output_chars: int,
    suspicious_output_checker,
    partial_riddle_checker,
    riddle_refusal_checker,
    memory_context_checker,
    handle_model_no_reply_fn,
    persist_local_and_remote_turn_fn,
    handle_model_reply_result_fn,
    increment_memory_helpful_fn,
    debug_chat_memory: bool,
) -> bool:
    if not reply or is_no_reply_signal(reply):
        fallback_reply = build_no_reply_fallback(resolved_text, riddle_related=riddle_related)
        await handle_model_no_reply_fn(
            payload=payload,
            author=author,
            channel_name=channel_name,
            clean_viewer_message=clean_viewer_message,
            fallback_reply=fallback_reply,
            msg_id=msg_id,
            allow_remote=allow_remote,
            author_is_owner=author_is_owner,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
        )
        return True

    if riddle_related and (partial_riddle_checker(resolved_text) or riddle_refusal_checker(reply)):
        persist_local_and_remote_turn_fn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            msg_id=msg_id,
            allow_remote=False,
            author_is_owner=author_is_owner,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
        )
        print("↪️ Réponse de refus/indice partiel supprimée pour la charade", flush=True)
        return True

    final_reply = smart_truncate(reply.replace("\n", " "), max_output_chars)
    if not final_reply:
        print("↪️ Réponse vide après nettoyage", flush=True)
        return True

    if suspicious_output_checker(final_reply):
        print("↪️ Réponse suspecte bloquée", flush=True)
        return True

    await handle_model_reply_result_fn(
        payload=payload,
        author=author,
        channel_name=channel_name,
        clean_viewer_message=clean_viewer_message,
        final_reply=final_reply,
        msg_id=msg_id,
        allow_remote=allow_remote,
        author_is_owner=author_is_owner,
        event_type=event_type,
        related_viewer=related_viewer,
        related_message=related_message,
        reply_to_turn_id=reply_to_turn_id,
        related_turn_id=related_turn_id,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
    )
    if should_mark_memory_helpful(
        context_bundle=context_bundle,
        resolved_text=resolved_text,
        memory_context_checker=memory_context_checker,
    ):
        increment_memory_helpful_fn()
        if debug_chat_memory:
            print("📌 Réponse marquée comme aide probable de la mémoire", flush=True)
    return True
