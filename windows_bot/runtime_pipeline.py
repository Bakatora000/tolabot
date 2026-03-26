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
from context_sources import build_auxiliary_context_sources, make_context_source_result, merge_context_text
from memory_client import MemoryApiError, store_memory_turn
from ollama_client import ask_ollama
from runtime_types import RuntimeContextBundle
from web_search_client import build_web_search_context, build_web_search_query, search_searxng


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


async def dispatch_incoming_message(
    *,
    payload,
    recent_ids,
    queue_worker_task,
    enqueue_message_fn,
    process_queued_message_fn,
    queued_message_factory,
    now_fn,
    injection_checker=looks_like_prompt_injection,
) -> None:
    incoming = build_incoming_message_data(payload)
    log_incoming_message(payload, incoming)

    if should_ignore_incoming_message(
        incoming=incoming,
        recent_ids=recent_ids,
        injection_checker=injection_checker,
    ):
        return

    queued_message = queued_message_factory(
        payload=payload,
        text=incoming.text,
        clean_viewer_message=incoming.clean_viewer_message,
        author=incoming.author,
        msg_id=incoming.msg_id,
        received_at=now_fn(),
    )
    if queue_worker_task is None:
        await process_queued_message_fn(queued_message)
    else:
        await enqueue_message_fn(queued_message)


async def handle_non_model_decision(
    *,
    payload,
    author: str,
    channel_name: str,
    msg_id: str | None,
    decision,
    clean_viewer_message: str,
    event_type: str,
    related_viewer: str,
    related_message: str,
    reply_to_turn_id: str,
    related_turn_id: str,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    author_is_owner: bool,
    reply_about_channel_content_fn,
    send_chat_reply_fn,
    persist_local_turn_fn,
    persist_local_and_remote_turn_fn,
    remember_remote_turn_fn,
    mark_replied_fn,
) -> bool:
    if decision.decision == "channel_summary":
        await reply_about_channel_content_fn(payload, author)
        return True

    if decision.decision == "refuse_memory_instruction":
        refusal_reply = str(decision.meta.get("reply", "Je ne prends ce type de note mémoire que d'Expevay."))
        print("↪️ Demande de mémorisation refusée : auteur non propriétaire", flush=True)
        await send_chat_reply_fn(payload.broadcaster, author, refusal_reply)
        persist_local_turn_fn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            bot_reply=refusal_reply,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
            store_reported_facts=False,
        )
        mark_replied_fn(author)
        return True

    if decision.decision == "store_only":
        persist_local_turn_fn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
        )
        remember_remote_turn_fn(
            channel_name,
            author,
            clean_viewer_message,
            message_id=msg_id,
            allow_remote=False,
            author_is_owner=author_is_owner,
        )
        print("↪️ Indice partiel de charade mémorisé, sans appel au modèle", flush=True)
        return True

    if decision.decision == "social_reply":
        social_reply = str(decision.meta.get("reply", ""))
        if social_reply:
            await send_chat_reply_fn(payload.broadcaster, author, social_reply, log_prefix="📤 Réponse sociale")
        persist_local_turn_fn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            bot_reply=social_reply,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
        )
        if social_reply:
            mark_replied_fn(author)
        print("↪️ Salutation/clôture traitée localement, sans appel au modèle", flush=True)
        return True

    if decision.decision == "skip_reply":
        persist_local_turn_fn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
        )
        print("↪️ Acquiescement bref détecté, sans appel au modèle", flush=True)
        return True

    return False


def remember_remote_turn(
    *,
    config,
    should_use_remote_memory: bool,
    channel_name: str,
    author: str,
    user_message: str,
    bot_reply: str = "",
    message_id: str | None = None,
    allow_remote: bool = True,
    author_is_owner: bool = False,
    store_memory_turn_fn=store_memory_turn,
) -> bool:
    if not allow_remote or not should_use_remote_memory:
        return False

    metadata = {
        "source": "twitch_chat",
        "channel": channel_name,
        "viewer": author,
    }
    if message_id:
        metadata["message_id"] = str(message_id)

    try:
        store_memory_turn_fn(
            config,
            channel=channel_name,
            viewer=author,
            user_message=user_message,
            bot_reply=bot_reply,
            metadata=metadata,
            author_is_owner=author_is_owner,
        )
        return True
    except MemoryApiError as exc:
        print(f"⚠️ Échec écriture mémoire distante : {exc}", flush=True)
        return False


def persist_local_turn(
    *,
    config,
    facts_memory,
    chat_memory,
    conversation_graph,
    channel_name: str,
    author: str,
    clean_viewer_message: str,
    bot_reply: str = "",
    event_type: str,
    related_viewer: str,
    related_message: str,
    reply_to_turn_id: str,
    related_turn_id: str,
    riddle_thread_reset: bool = False,
    riddle_thread_close: bool = False,
    store_reported_facts: bool = True,
    append_reported_facts_fn,
    append_chat_turn_fn,
    append_conversation_turn_fn,
) -> None:
    if store_reported_facts:
        append_reported_facts_fn(
            facts_memory,
            channel_name,
            author,
            clean_viewer_message,
            ttl_hours=config.chat_memory_ttl_hours,
        )
    append_chat_turn_fn(
        chat_memory,
        channel_name,
        author,
        clean_viewer_message,
        bot_reply,
        ttl_hours=config.chat_memory_ttl_hours,
        thread_boundary="start" if riddle_thread_reset else ("end" if riddle_thread_close else ""),
        event_type=event_type,
        related_viewer=related_viewer,
        related_message=related_message,
    )
    append_conversation_turn_fn(
        conversation_graph,
        channel_name,
        author,
        clean_viewer_message,
        bot_reply,
        event_type=event_type,
        reply_to_turn_id=reply_to_turn_id,
        corrects_turn_id=related_turn_id,
        target_viewers=[related_viewer] if related_viewer else [],
        ttl_hours=config.chat_memory_ttl_hours,
    )


def persist_local_and_remote_turn(
    *,
    config,
    should_use_remote_memory: bool,
    facts_memory,
    chat_memory,
    conversation_graph,
    channel_name: str,
    author: str,
    clean_viewer_message: str,
    bot_reply: str = "",
    msg_id: str | None,
    allow_remote: bool,
    author_is_owner: bool,
    event_type: str,
    related_viewer: str,
    related_message: str,
    reply_to_turn_id: str,
    related_turn_id: str,
    riddle_thread_reset: bool = False,
    riddle_thread_close: bool = False,
    store_reported_facts: bool = True,
    append_reported_facts_fn,
    append_chat_turn_fn,
    append_conversation_turn_fn,
    store_memory_turn_fn=store_memory_turn,
) -> None:
    persist_local_turn(
        config=config,
        facts_memory=facts_memory,
        chat_memory=chat_memory,
        conversation_graph=conversation_graph,
        channel_name=channel_name,
        author=author,
        clean_viewer_message=clean_viewer_message,
        bot_reply=bot_reply,
        event_type=event_type,
        related_viewer=related_viewer,
        related_message=related_message,
        reply_to_turn_id=reply_to_turn_id,
        related_turn_id=related_turn_id,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        store_reported_facts=store_reported_facts,
        append_reported_facts_fn=append_reported_facts_fn,
        append_chat_turn_fn=append_chat_turn_fn,
        append_conversation_turn_fn=append_conversation_turn_fn,
    )
    remember_remote_turn(
        config=config,
        should_use_remote_memory=should_use_remote_memory,
        channel_name=channel_name,
        author=author,
        user_message=clean_viewer_message,
        bot_reply=bot_reply,
        message_id=msg_id,
        allow_remote=allow_remote,
        author_is_owner=author_is_owner,
        store_memory_turn_fn=store_memory_turn_fn,
    )


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


async def handle_model_decision_pipeline(
    *,
    payload,
    author: str,
    channel_name: str,
    clean_viewer_message: str,
    resolved_text: str,
    msg_id: str | None,
    author_is_owner: bool,
    event_type: str,
    related_viewer: str,
    related_message: str,
    reply_to_turn_id: str,
    related_turn_id: str,
    riddle_related: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    specialized_local_thread: bool,
    decision,
    alias_context: str,
    focus_context: str,
    facts_context: str,
    config,
    model,
    ask_fn,
    max_output_chars: int,
    suspicious_output_checker,
    partial_riddle_checker,
    riddle_refusal_checker,
    memory_context_checker,
    build_runtime_context_bundle_fn,
    handle_model_no_reply_fn,
    persist_local_and_remote_turn_fn,
    handle_model_reply_result_fn,
    increment_memory_helpful_fn,
    debug_chat_memory: bool,
) -> None:
    print("🤖 Mention détectée, appel à Ollama...", flush=True)
    prefer_active_thread = bool(
        decision.meta.get(
            "prefer_active_thread",
            specialized_local_thread or memory_context_checker(resolved_text),
        )
    )
    conversation_mode = str(decision.meta.get("conversation_mode", ""))
    context_bundle = build_runtime_context_bundle_fn(
        resolved_text=resolved_text,
        payload=payload,
        channel_name=channel_name,
        author=author,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        specialized_local_thread=specialized_local_thread,
        decision=decision,
        alias_context=alias_context,
        focus_context=focus_context,
        facts_context=facts_context,
        conversation_mode=conversation_mode,
    )
    log_runtime_context(
        config=config,
        context_bundle=context_bundle,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
    )
    reply = await generate_model_reply(
        payload=payload,
        resolved_text=resolved_text,
        context_bundle=context_bundle,
        config=config,
        model=model,
        ask_fn=ask_fn,
    )
    print(f"🧠 Réponse Ollama : {reply}", flush=True)
    await finalize_model_reply(
        payload=payload,
        author=author,
        channel_name=channel_name,
        clean_viewer_message=clean_viewer_message,
        resolved_text=resolved_text,
        reply=reply,
        msg_id=msg_id,
        allow_remote=not specialized_local_thread,
        author_is_owner=author_is_owner,
        event_type=event_type,
        related_viewer=related_viewer,
        related_message=related_message,
        reply_to_turn_id=reply_to_turn_id,
        related_turn_id=related_turn_id,
        riddle_related=riddle_related,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        context_bundle=context_bundle,
        max_output_chars=max_output_chars,
        suspicious_output_checker=suspicious_output_checker,
        partial_riddle_checker=partial_riddle_checker,
        riddle_refusal_checker=riddle_refusal_checker,
        memory_context_checker=memory_context_checker,
        handle_model_no_reply_fn=handle_model_no_reply_fn,
        persist_local_and_remote_turn_fn=persist_local_and_remote_turn_fn,
        handle_model_reply_result_fn=handle_model_reply_result_fn,
        increment_memory_helpful_fn=increment_memory_helpful_fn,
        debug_chat_memory=debug_chat_memory,
    )


def maybe_refresh_context_for_web(
    *,
    resolved_text: str,
    channel_name: str,
    author: str,
    prefer_active_thread: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    specialized_local_thread: bool,
    context_source: str,
    chat_context: dict,
    context_sources: list,
    alias_context: str,
    focus_context: str,
    facts_context: str,
    get_context_with_fallback_fn,
) -> tuple[dict, str, list]:
    if specialized_local_thread or not any(source.source_id == "mem0" for source in context_sources):
        return chat_context, context_source, context_sources

    chat_context, context_source, context_sources = get_context_with_fallback_fn(
        text=resolved_text,
        channel_name=channel_name,
        author=author,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        use_remote_memory=False,
    )
    chat_context["global_context"] = merge_context_text(
        alias_context,
        focus_context,
        facts_context,
        chat_context.get("global_context", "aucun"),
    )
    return chat_context, context_source, context_sources


def resolve_web_context(
    *,
    resolved_text: str,
    prefer_active_thread: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    specialized_local_thread: bool,
    channel_name: str,
    author: str,
    chat_context: dict,
    context_source: str,
    context_sources: list,
    alias_context: str,
    focus_context: str,
    facts_context: str,
    prefetch_web_decision,
    config,
    get_context_with_fallback_fn,
    build_web_search_decision_fn,
    build_web_search_context_fn=build_web_search_context,
    search_searxng_fn=search_searxng,
) -> tuple[str, dict, str, list]:
    web_context = "aucun"
    if not (config.web_search_enabled and config.web_search_provider == "searxng"):
        return web_context, chat_context, context_source, context_sources

    web_decision = prefetch_web_decision
    if not web_decision or not web_decision.needs_web:
        web_decision = build_web_search_decision_fn(
            sanitize_user_text(strip_trigger(resolved_text)),
            f"{chat_context.get('viewer_context', 'aucun')}\n{chat_context.get('global_context', 'aucun')}",
            mode=config.web_search_mode,
        )
    if not web_decision.needs_web:
        return web_context, chat_context, context_source, context_sources

    chat_context, context_source, context_sources = maybe_refresh_context_for_web(
        resolved_text=resolved_text,
        channel_name=channel_name,
        author=author,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        specialized_local_thread=specialized_local_thread,
        context_source=context_source,
        chat_context=chat_context,
        context_sources=context_sources,
        alias_context=alias_context,
        focus_context=focus_context,
        facts_context=facts_context,
        get_context_with_fallback_fn=get_context_with_fallback_fn,
    )
    print(f"🌐 Règle web matchée : {web_decision.rule_id} ({web_decision.reason})", flush=True)
    try:
        web_query = str(web_decision.query).strip() or build_web_search_query(
            resolved_text,
            viewer_context=chat_context.get("viewer_context", "aucun"),
            global_context=chat_context.get("global_context", "aucun"),
        )
        web_results = search_searxng_fn(
            query=web_query,
            base_url=config.searxng_base_url,
            timeout_seconds=config.web_search_timeout_seconds,
            max_results=config.web_search_max_results,
        )
        web_context = build_web_search_context_fn(web_results)
        if web_context != "aucun":
            print("🌐 Contexte web injecté via SearXNG", flush=True)
    except Exception as exc:
        print(f"⚠️ Recherche web SearXNG indisponible : {exc}", flush=True)
    return web_context, chat_context, context_source, context_sources


def prepare_runtime_context(
    *,
    resolved_text: str,
    payload,
    channel_name: str,
    author: str,
    prefer_active_thread: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    specialized_local_thread: bool,
    decision,
    alias_context: str,
    focus_context: str,
    facts_context: str,
    config,
    should_use_remote_memory: bool,
    get_specialized_local_context_fn,
    get_context_with_fallback_fn,
    build_web_search_decision_fn,
) -> tuple[dict, str, list, object | None]:
    prefetch_web_decision = None
    if config.web_search_enabled and config.web_search_provider == "searxng":
        prefetch_web_decision = build_web_search_decision_fn(
            sanitize_user_text(strip_trigger(resolved_text)),
            f"{alias_context}\n{focus_context}\n{facts_context}",
            mode=config.web_search_mode,
        )

    if specialized_local_thread:
        chat_context, context_sources = get_specialized_local_context_fn(
            payload.broadcaster.name,
            author,
            use_active_thread=not riddle_thread_close,
        )
        if chat_context["viewer_context"] == "aucun" and not riddle_thread_close:
            chat_context, context_sources = get_specialized_local_context_fn(
                payload.broadcaster.name,
                author,
                use_active_thread=False,
            )
        context_source = "local-specialized"
    else:
        use_remote_memory = should_use_remote_memory and decision.needs_long_memory
        if prefetch_web_decision and prefetch_web_decision.needs_web:
            use_remote_memory = False
        chat_context, context_source, context_sources = get_context_with_fallback_fn(
            text=resolved_text,
            channel_name=channel_name,
            author=author,
            prefer_active_thread=prefer_active_thread,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
            use_remote_memory=use_remote_memory,
        )

    chat_context["global_context"] = merge_context_text(
        alias_context,
        focus_context,
        facts_context,
        chat_context.get("global_context", "aucun"),
    )
    context_sources = context_sources + build_auxiliary_context_sources(
        alias_context=alias_context,
        focus_context=focus_context,
        facts_context=facts_context,
    )
    return chat_context, context_source, context_sources, prefetch_web_decision


def build_runtime_context_bundle(
    *,
    resolved_text: str,
    payload,
    channel_name: str,
    author: str,
    prefer_active_thread: bool,
    riddle_thread_reset: bool,
    riddle_thread_close: bool,
    specialized_local_thread: bool,
    decision,
    alias_context: str,
    focus_context: str,
    facts_context: str,
    conversation_mode: str,
    config,
    should_use_remote_memory: bool,
    get_specialized_local_context_fn,
    get_context_with_fallback_fn,
    build_web_search_decision_fn,
    build_web_search_context_fn=build_web_search_context,
    search_searxng_fn=search_searxng,
) -> RuntimeContextBundle:
    chat_context, context_source, context_sources, prefetch_web_decision = prepare_runtime_context(
        resolved_text=resolved_text,
        payload=payload,
        channel_name=channel_name,
        author=author,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        specialized_local_thread=specialized_local_thread,
        decision=decision,
        alias_context=alias_context,
        focus_context=focus_context,
        facts_context=facts_context,
        config=config,
        should_use_remote_memory=should_use_remote_memory,
        get_specialized_local_context_fn=get_specialized_local_context_fn,
        get_context_with_fallback_fn=get_context_with_fallback_fn,
        build_web_search_decision_fn=build_web_search_decision_fn,
    )
    web_context, chat_context, context_source, context_sources = resolve_web_context(
        resolved_text=resolved_text,
        prefer_active_thread=prefer_active_thread,
        riddle_thread_reset=riddle_thread_reset,
        riddle_thread_close=riddle_thread_close,
        specialized_local_thread=specialized_local_thread,
        channel_name=channel_name,
        author=author,
        chat_context=chat_context,
        context_source=context_source,
        context_sources=context_sources,
        alias_context=alias_context,
        focus_context=focus_context,
        facts_context=facts_context,
        prefetch_web_decision=prefetch_web_decision,
        config=config,
        get_context_with_fallback_fn=get_context_with_fallback_fn,
        build_web_search_decision_fn=build_web_search_decision_fn,
        build_web_search_context_fn=build_web_search_context_fn,
        search_searxng_fn=search_searxng_fn,
    )
    web_source = make_context_source_result(
        "web",
        web_context,
        priority=95,
        confidence=0.7,
        meta={"context_label": "web"},
    )
    if web_source:
        context_sources.append(web_source)
    return RuntimeContextBundle(
        viewer_context=chat_context.get("viewer_context", "aucun"),
        global_context=chat_context.get("global_context", "aucun"),
        web_context=web_context,
        context_source="local" if web_context != "aucun" else context_source,
        sources=context_sources,
        conversation_mode=conversation_mode,
    )
