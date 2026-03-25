import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import requests
import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from bot_config import load_config
from arbitrator import arbitrate_chat_message, build_normalized_event
from bot_logic import (
    BOT_TRIGGER,
    BOT_USERNAME,
    MAX_OUTPUT_CHARS,
    MAX_VIEWER_CHAT_TURNS,
    append_channel_update,
    append_chat_turn,
    build_channel_alias_index,
    asks_about_channel_content,
    build_chat_context,
    build_no_reply_fallback,
    classify_conversation_event,
    closes_riddle_thread,
    find_related_global_turn,
    increment_chat_memory_counter,
    is_partial_riddle_message,
    is_riddle_refusal_reply,
    likely_needs_memory_context,
    looks_like_riddle_message,
    prune_chat_memory,
    infer_recent_focus,
    resolve_known_aliases,
    resolve_recent_reference_subjects,
    starts_new_riddle_thread,
    end_stream_session,
    extract_active_viewer_thread,
    extract_channel_profile,
    format_chat_turns,
    is_no_reply_signal,
    load_chat_memory,
    load_history,
    looks_like_prompt_injection,
    looks_like_memory_instruction,
    normalize_spaces,
    now_ts,
    output_is_suspicious,
    normalize_web_sourced_reply,
    sanitize_user_text,
    smart_truncate,
    start_stream_session,
    strip_trigger,
    viewer_recent_social_redundancy,
)
from conversation_graph import (
    append_conversation_turn,
    build_conversation_graph_context,
    find_related_conversation_turn,
    find_reply_target_turn,
    load_conversation_graph,
    prune_conversation_graph,
)
from context_sources import (
    build_auxiliary_context_sources,
    build_context_source_results,
    make_context_source_result,
    merge_context_text,
)
from decision_tree import build_web_search_decision
from facts_memory import (
    append_reported_facts,
    build_facts_context,
    load_facts_memory,
    prune_facts_memory,
)
from memory_client import MemoryApiError, get_memory_context, is_mem0_enabled, store_memory_turn
from ollama_client import ask_ollama, choose_model, summarize_channel_profile
from runtime_types import MessagePreparation, RuntimeContextBundle
from twitch_auth import run_oauth_flow
from web_search_client import build_web_search_context, build_web_search_query, search_searxng, should_enable_web_search

CONFIG = load_config()
OLLAMA_MODEL = None


@dataclass
class QueuedMessage:
    payload: twitchio.ChatMessage
    text: str
    clean_viewer_message: str
    author: str
    msg_id: str | None
    received_at: float


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            client_id=CONFIG.client_id,
            client_secret=CONFIG.client_secret,
            bot_id=CONFIG.bot_id,
            owner_id=CONFIG.owner_id,
            prefix="!",
        )

        self.last_global_reply_at = 0.0
        self.last_user_reply_at: dict[str, float] = {}
        self.generation_lock = asyncio.Lock()
        self.recent_ids = deque(maxlen=200)
        self.message_queue: asyncio.Queue[QueuedMessage] = asyncio.Queue(maxsize=CONFIG.message_queue_max_size)
        self.queue_worker_task: asyncio.Task | None = None
        self.history = load_history()
        self.chat_memory = prune_chat_memory(
            load_chat_memory(),
            ttl_hours=CONFIG.chat_memory_ttl_hours,
        )
        self.conversation_graph = prune_conversation_graph(
            load_conversation_graph(),
            ttl_hours=CONFIG.chat_memory_ttl_hours,
        )
        self.facts_memory = prune_facts_memory(
            load_facts_memory(),
            ttl_hours=CONFIG.chat_memory_ttl_hours,
        )

    def should_use_remote_memory(self) -> bool:
        return is_mem0_enabled(CONFIG)

    def should_use_remote_memory_for_message(self, riddle_related: bool) -> bool:
        return self.should_use_remote_memory() and not riddle_related

    def get_specialized_local_context(
        self,
        channel_name: str,
        author: str,
        use_active_thread: bool,
    ) -> tuple[dict, list]:
        normalized_channel = normalize_spaces(channel_name).lower()
        normalized_author = normalize_spaces(author).lower()
        channel_data = self.chat_memory.get("channels", {}).get(normalized_channel, {})
        viewer_turns = list(channel_data.get("viewer_turns", {}).get(normalized_author, []))[-MAX_VIEWER_CHAT_TURNS:]
        if use_active_thread:
            active_turns = extract_active_viewer_thread(viewer_turns)
            viewer_turns = active_turns or viewer_turns

        context = {
            "viewer_context": format_chat_turns(viewer_turns),
            "global_context": build_conversation_graph_context(
                self.conversation_graph,
                normalized_channel,
                normalized_author,
            ),
            "items": [],
        }
        sources = build_context_source_results(
            viewer_context=context["viewer_context"],
            conversation_context=context["global_context"],
            context_label="local-specialized",
        )
        return context, sources

    def get_context_with_fallback(
        self,
        text: str,
        channel_name: str,
        author: str,
        prefer_active_thread: bool,
        riddle_thread_reset: bool,
        riddle_thread_close: bool,
        use_remote_memory: bool,
    ) -> tuple[dict, str, list]:
        if use_remote_memory:
            local_context = build_chat_context(
                self.chat_memory,
                channel_name,
                author,
                prefer_active_thread=prefer_active_thread and not riddle_thread_reset and not riddle_thread_close,
            )
            graph_context = build_conversation_graph_context(
                self.conversation_graph,
                channel_name,
                author,
                current_message=text,
            )
            local_context["global_context"] = merge_context_text(local_context.get("global_context", "aucun"), graph_context)
            source_results = []
            local_viewer_source = make_context_source_result(
                "local_viewer_thread",
                local_context.get("viewer_context", "aucun"),
                priority=90,
                confidence=0.82,
                meta={"context_label": "local"},
            )
            if local_viewer_source:
                source_results.append(local_viewer_source)
            graph_source = make_context_source_result(
                "conversation_graph",
                graph_context,
                priority=88,
                confidence=0.8,
                meta={"context_label": "local"},
            )
            if graph_source:
                source_results.append(graph_source)
            if (
                local_context["viewer_context"] == "aucun"
                and prefer_active_thread
                and not riddle_thread_reset
            ):
                local_context = build_chat_context(
                    self.chat_memory,
                    channel_name,
                    author,
                    prefer_active_thread=False,
                )
                local_context["global_context"] = merge_context_text(local_context.get("global_context", "aucun"), graph_context)
            try:
                remote_context = get_memory_context(
                    CONFIG,
                    channel=channel_name,
                    viewer=author,
                    message=text,
                )
                favor_local_context = local_context.get("global_context", "aucun") != "aucun"
                merged_viewer_context = local_context.get("viewer_context", "aucun")
                if merged_viewer_context == "aucun":
                    merged_viewer_context = remote_context.get("viewer_context", "aucun")
                merged_global_context = local_context.get("global_context", "aucun")
                if not favor_local_context:
                    merged_global_context = merge_context_text(
                        local_context.get("global_context", "aucun"),
                        remote_context.get("global_context", "aucun"),
                    )
                elif merged_global_context == "aucun":
                    merged_global_context = remote_context.get("global_context", "aucun")
                merged_context = {
                    "viewer_context": merged_viewer_context,
                    "global_context": merged_global_context,
                    "items": list(remote_context.get("items", [])),
                }
                mem0_source = make_context_source_result(
                    "mem0",
                    remote_context.get("viewer_context", "aucun"),
                    priority=80,
                    confidence=0.7,
                    meta={"context_label": "mem0"},
                )
                if mem0_source:
                    source_results.append(mem0_source)
                return merged_context, "local-priority+mem0" if favor_local_context else "local+mem0", source_results
            except MemoryApiError as exc:
                print(f"⚠️ Mémoire distante indisponible, fallback local : {exc}", flush=True)
                if not CONFIG.mem0_fallback_local:
                    return {"viewer_context": "aucun", "global_context": "aucun", "items": []}, "mem0-error", []

        local_context = build_chat_context(
            self.chat_memory,
            channel_name,
            author,
            prefer_active_thread=prefer_active_thread and not riddle_thread_reset and not riddle_thread_close,
        )
        graph_context = build_conversation_graph_context(
            self.conversation_graph,
            channel_name,
            author,
            current_message=text,
        )
        local_context["global_context"] = merge_context_text(local_context.get("global_context", "aucun"), graph_context)
        if (
            local_context["viewer_context"] == "aucun"
            and prefer_active_thread
            and not riddle_thread_reset
        ):
            local_context = build_chat_context(
                self.chat_memory,
                channel_name,
                author,
                prefer_active_thread=False,
            )
            local_context["global_context"] = merge_context_text(local_context.get("global_context", "aucun"), graph_context)
        return local_context, "local", build_context_source_results(
            viewer_context=local_context["viewer_context"],
            conversation_context=graph_context,
            context_label="local",
        )

    def remember_remote_turn(
        self,
        channel_name: str,
        author: str,
        user_message: str,
        bot_reply: str = "",
        message_id: str | None = None,
        allow_remote: bool = True,
        author_is_owner: bool = False,
    ) -> bool:
        if not allow_remote or not self.should_use_remote_memory():
            return False

        metadata = {
            "source": "twitch_chat",
            "channel": channel_name,
            "viewer": author,
        }
        if message_id:
            metadata["message_id"] = str(message_id)

        try:
            store_memory_turn(
                CONFIG,
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

    async def setup_hook(self) -> None:
        print("🔧 setup_hook démarré", flush=True)
        print("⏳ Création des souscriptions EventSub...", flush=True)

        subs = [
            eventsub.ChatMessageSubscription(
                broadcaster_user_id=self.owner_id,
                user_id=self.bot_id,
            ),
            eventsub.ChannelUpdateSubscription(
                broadcaster_user_id=self.owner_id,
            ),
            eventsub.StreamOnlineSubscription(
                broadcaster_user_id=self.owner_id,
            ),
            eventsub.StreamOfflineSubscription(
                broadcaster_user_id=self.owner_id,
            ),
        ]

        for sub in subs:
            await self.subscribe_websocket(payload=sub)

        if self.queue_worker_task is None:
            self.queue_worker_task = asyncio.create_task(self.message_queue_worker())

        print("✅ Souscriptions chat + historique chaîne OK", flush=True)

    async def event_ready(self):
        print("==================================================", flush=True)
        print("✅ BOT PRÊT", flush=True)
        print(f"Compte connecté : {self.user.name}", flush=True)
        print(f"Bot ID          : {self.bot_id}", flush=True)
        print(f"Owner ID        : {self.owner_id}", flush=True)
        print(f"Chaîne cible    : #{CONFIG.channel_name}", flush=True)
        print("🟢 En écoute du chat...", flush=True)
        print("==================================================", flush=True)

    async def event_stream_online(self, payload):
        print("🔴 Stream online détecté", flush=True)
        start_stream_session(self.history)

    async def event_stream_offline(self, payload):
        print("⚫ Stream offline détecté", flush=True)
        end_stream_session(self.history)

    async def event_channel_update(self, payload):
        title = getattr(payload, "title", "") or ""
        category_name = getattr(payload, "category_name", "") or ""

        print("📝 Channel update détecté", flush=True)
        print(f"   Titre     : {title}", flush=True)
        print(f"   Catégorie : {category_name}", flush=True)

        append_channel_update(self.history, title, category_name)

    def user_in_cooldown(self, author: str) -> bool:
        last = self.last_user_reply_at.get(author, 0.0)
        return (now_ts() - last) < CONFIG.user_cooldown_seconds

    def global_in_cooldown(self) -> bool:
        return (now_ts() - self.last_global_reply_at) < CONFIG.global_cooldown_seconds

    def seconds_until_ready(self, author: str) -> float:
        global_wait = max(0.0, CONFIG.global_cooldown_seconds - (now_ts() - self.last_global_reply_at))
        user_wait = max(0.0, CONFIG.user_cooldown_seconds - (now_ts() - self.last_user_reply_at.get(author, 0.0)))
        return max(global_wait, user_wait)

    def mark_replied(self, author: str) -> None:
        ts = now_ts()
        self.last_global_reply_at = ts
        self.last_user_reply_at[author] = ts

    def format_chat_reply(self, author: str, message: str) -> str:
        prefix = f"@{normalize_spaces(author).lstrip('@')} "
        available_chars = max(1, MAX_OUTPUT_CHARS - len(prefix))
        return f"{prefix}{smart_truncate(message, available_chars)}"

    def is_owner_author(self, author: str) -> bool:
        return normalize_spaces(author).lower() == normalize_spaces(CONFIG.channel_name).lower()

    async def send_chat_reply(self, broadcaster, author: str, message: str, log_prefix: str = "📤 Envoi dans le chat") -> None:
        outgoing_reply = self.format_chat_reply(author, message)
        print(f"{log_prefix} : {outgoing_reply}", flush=True)
        await broadcaster.send_message(
            outgoing_reply,
            sender=self.bot_id,
            token_for=self.bot_id,
        )

    async def send_channel_summary_reply(self, payload: twitchio.ChatMessage, author: str, summary: str) -> None:
        outgoing_summary = self.format_chat_reply(author, summary)
        print(f"📤 Envoi résumé chaîne : {outgoing_summary}", flush=True)
        await payload.broadcaster.send_message(
            outgoing_summary,
            sender=self.bot_id,
            token_for=self.bot_id,
        )
        self.mark_replied(author)

    def persist_local_turn(
        self,
        *,
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
    ) -> None:
        if store_reported_facts:
            append_reported_facts(
                self.facts_memory,
                channel_name,
                author,
                clean_viewer_message,
                ttl_hours=CONFIG.chat_memory_ttl_hours,
            )
        append_chat_turn(
            self.chat_memory,
            channel_name,
            author,
            clean_viewer_message,
            bot_reply,
            ttl_hours=CONFIG.chat_memory_ttl_hours,
            thread_boundary="start" if riddle_thread_reset else ("end" if riddle_thread_close else ""),
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
        )
        append_conversation_turn(
            self.conversation_graph,
            channel_name,
            author,
            clean_viewer_message,
            bot_reply,
            event_type=event_type,
            reply_to_turn_id=reply_to_turn_id,
            corrects_turn_id=related_turn_id,
            target_viewers=[related_viewer] if related_viewer else [],
            ttl_hours=CONFIG.chat_memory_ttl_hours,
        )

    async def handle_non_model_decision(
        self,
        *,
        payload: twitchio.ChatMessage,
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
    ) -> bool:
        if decision.decision == "channel_summary":
            await self.reply_about_channel_content(payload, author)
            return True

        if decision.decision == "refuse_memory_instruction":
            refusal_reply = str(decision.meta.get("reply", "Je ne prends ce type de note mémoire que d'Expevay."))
            print("↪️ Demande de mémorisation refusée : auteur non propriétaire", flush=True)
            await self.send_chat_reply(payload.broadcaster, author, refusal_reply)
            self.persist_local_turn(
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
            self.mark_replied(author)
            return True

        if decision.decision == "store_only":
            self.persist_local_turn(
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
            self.remember_remote_turn(
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
                await self.send_chat_reply(payload.broadcaster, author, social_reply, log_prefix="📤 Réponse sociale")
            self.persist_local_turn(
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
                self.mark_replied(author)
            print("↪️ Salutation/clôture traitée localement, sans appel au modèle", flush=True)
            return True

        if decision.decision == "skip_reply":
            self.persist_local_turn(
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

    def persist_local_and_remote_turn(
        self,
        *,
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
    ) -> None:
        self.persist_local_turn(
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
        )
        self.remember_remote_turn(
            channel_name,
            author,
            clean_viewer_message,
            bot_reply,
            message_id=msg_id,
            allow_remote=allow_remote,
            author_is_owner=author_is_owner,
        )

    async def handle_model_no_reply(
        self,
        *,
        payload: twitchio.ChatMessage,
        author: str,
        channel_name: str,
        clean_viewer_message: str,
        fallback_reply: str,
        msg_id: str | None,
        allow_remote: bool,
        author_is_owner: bool,
        event_type: str,
        related_viewer: str,
        related_message: str,
        reply_to_turn_id: str,
        related_turn_id: str,
        riddle_thread_reset: bool,
        riddle_thread_close: bool,
    ) -> bool:
        if not fallback_reply:
            self.persist_local_and_remote_turn(
                channel_name=channel_name,
                author=author,
                clean_viewer_message=clean_viewer_message,
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
            print("↪️ Pas de réponse envoyée", flush=True)
            return True

        await self.send_chat_reply(payload.broadcaster, author, fallback_reply, log_prefix="📤 Fallback NO_REPLY")
        self.persist_local_turn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            bot_reply=fallback_reply,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            reply_to_turn_id=reply_to_turn_id,
            related_turn_id=related_turn_id,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
        )
        self.mark_replied(author)
        return True

    async def handle_model_reply_result(
        self,
        *,
        payload: twitchio.ChatMessage,
        author: str,
        channel_name: str,
        clean_viewer_message: str,
        final_reply: str,
        msg_id: str | None,
        allow_remote: bool,
        author_is_owner: bool,
        event_type: str,
        related_viewer: str,
        related_message: str,
        reply_to_turn_id: str,
        related_turn_id: str,
        riddle_thread_reset: bool,
        riddle_thread_close: bool,
    ) -> None:
        await self.send_chat_reply(payload.broadcaster, author, final_reply)
        self.persist_local_and_remote_turn(
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            bot_reply=final_reply,
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
        self.mark_replied(author)

    def should_mark_memory_helpful(
        self,
        *,
        context_bundle: RuntimeContextBundle,
        resolved_text: str,
    ) -> bool:
        return context_bundle.viewer_context != "aucun" and likely_needs_memory_context(resolved_text)

    async def finalize_model_reply(
        self,
        *,
        payload: twitchio.ChatMessage,
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
    ) -> bool:
        if not reply or is_no_reply_signal(reply):
            fallback_reply = build_no_reply_fallback(resolved_text, riddle_related=riddle_related)
            await self.handle_model_no_reply(
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

        if riddle_related and (
            is_partial_riddle_message(resolved_text) or is_riddle_refusal_reply(reply)
        ):
            self.persist_local_and_remote_turn(
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

        final_reply = smart_truncate(reply.replace("\n", " "), MAX_OUTPUT_CHARS)
        if not final_reply:
            print("↪️ Réponse vide après nettoyage", flush=True)
            return True

        if output_is_suspicious(final_reply):
            print("↪️ Réponse suspecte bloquée", flush=True)
            return True

        await self.handle_model_reply_result(
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
        if self.should_mark_memory_helpful(
            context_bundle=context_bundle,
            resolved_text=resolved_text,
        ):
            increment_chat_memory_counter(
                self.chat_memory,
                "memory_helpful_replies",
            )
            if CONFIG.debug_chat_memory:
                print("📌 Réponse marquée comme aide probable de la mémoire", flush=True)
        return True

    async def handle_model_decision_pipeline(
        self,
        *,
        payload: twitchio.ChatMessage,
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
    ) -> None:
        print("🤖 Mention détectée, appel à Ollama...", flush=True)
        prefer_active_thread = bool(
            decision.meta.get(
                "prefer_active_thread",
                specialized_local_thread or likely_needs_memory_context(resolved_text),
            )
        )
        conversation_mode = str(decision.meta.get("conversation_mode", ""))
        context_bundle = self.build_runtime_context_bundle(
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
        self.log_runtime_context(
            context_bundle=context_bundle,
            prefer_active_thread=prefer_active_thread,
            riddle_thread_reset=riddle_thread_reset,
        )
        reply = await self.generate_model_reply(
            payload=payload,
            resolved_text=resolved_text,
            context_bundle=context_bundle,
        )
        reply = normalize_web_sourced_reply(reply, web_context=context_bundle.web_context)

        print(f"🧠 Réponse Ollama : {reply}", flush=True)

        await self.finalize_model_reply(
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
        )

    def maybe_refresh_context_for_web(
        self,
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
    ) -> tuple[dict, str, list]:
        if specialized_local_thread or not any(source.source_id == "mem0" for source in context_sources):
            return chat_context, context_source, context_sources

        chat_context, context_source, context_sources = self.get_context_with_fallback(
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
        self,
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
    ) -> tuple[str, dict, str, list]:
        web_context = "aucun"
        if not (CONFIG.web_search_enabled and CONFIG.web_search_provider == "searxng"):
            return web_context, chat_context, context_source, context_sources

        web_decision = prefetch_web_decision
        if not web_decision or not web_decision.needs_web:
            web_decision = build_web_search_decision(
                sanitize_user_text(strip_trigger(resolved_text)),
                f"{chat_context.get('viewer_context', 'aucun')}\n{chat_context.get('global_context', 'aucun')}",
                mode=CONFIG.web_search_mode,
            )
        if not web_decision.needs_web:
            return web_context, chat_context, context_source, context_sources

        chat_context, context_source, context_sources = self.maybe_refresh_context_for_web(
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
        )
        print(
            f"🌐 Règle web matchée : {web_decision.rule_id} ({web_decision.reason})",
            flush=True,
        )
        try:
            web_query = str(web_decision.query).strip() or build_web_search_query(
                resolved_text,
                viewer_context=chat_context.get("viewer_context", "aucun"),
                global_context=chat_context.get("global_context", "aucun"),
            )
            web_results = search_searxng(
                query=web_query,
                base_url=CONFIG.searxng_base_url,
                timeout_seconds=CONFIG.web_search_timeout_seconds,
                max_results=CONFIG.web_search_max_results,
            )
            web_context = build_web_search_context(web_results)
            if web_context != "aucun":
                print("🌐 Contexte web injecté via SearXNG", flush=True)
        except Exception as exc:
            print(f"⚠️ Recherche web SearXNG indisponible : {exc}", flush=True)
        return web_context, chat_context, context_source, context_sources

    def prepare_runtime_context(
        self,
        *,
        resolved_text: str,
        payload: twitchio.ChatMessage,
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
    ) -> tuple[dict, str, list, object | None]:
        prefetch_web_decision = None
        if CONFIG.web_search_enabled and CONFIG.web_search_provider == "searxng":
            prefetch_web_decision = build_web_search_decision(
                sanitize_user_text(strip_trigger(resolved_text)),
                f"{alias_context}\n{focus_context}\n{facts_context}",
                mode=CONFIG.web_search_mode,
            )

        if specialized_local_thread:
            chat_context, context_sources = self.get_specialized_local_context(
                payload.broadcaster.name,
                author,
                use_active_thread=not riddle_thread_close,
            )
            if chat_context["viewer_context"] == "aucun" and not riddle_thread_close:
                chat_context, context_sources = self.get_specialized_local_context(
                    payload.broadcaster.name,
                    author,
                    use_active_thread=False,
                )
            context_source = "local-specialized"
        else:
            use_remote_memory = self.should_use_remote_memory_for_message(False) and decision.needs_long_memory
            if prefetch_web_decision and prefetch_web_decision.needs_web:
                use_remote_memory = False
            chat_context, context_source, context_sources = self.get_context_with_fallback(
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
        self,
        *,
        resolved_text: str,
        payload: twitchio.ChatMessage,
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
    ) -> RuntimeContextBundle:
        chat_context, context_source, context_sources, prefetch_web_decision = self.prepare_runtime_context(
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
        )
        web_context, chat_context, context_source, context_sources = self.resolve_web_context(
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
            viewer_context=chat_context["viewer_context"],
            global_context=chat_context["global_context"],
            web_context=web_context,
            context_source=context_source,
            sources=context_sources,
            conversation_mode=conversation_mode,
        )

    def log_runtime_context(
        self,
        *,
        context_bundle: RuntimeContextBundle,
        prefer_active_thread: bool,
        riddle_thread_reset: bool,
    ) -> None:
        if not CONFIG.debug_chat_memory:
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

    async def generate_model_reply(
        self,
        *,
        payload: twitchio.ChatMessage,
        resolved_text: str,
        context_bundle: RuntimeContextBundle,
    ) -> str:
        return await asyncio.to_thread(
            ask_ollama,
            payload.chatter.name,
            resolved_text,
            CONFIG.ollama_url,
            OLLAMA_MODEL,
            CONFIG.request_timeout_seconds,
            context_bundle.viewer_context,
            context_bundle.global_context,
            context_bundle.web_context,
            context_bundle.conversation_mode,
            CONFIG.llm_provider,
            CONFIG.openai_api_key,
            CONFIG.openai_web_search_enabled,
            CONFIG.openai_web_search_mode,
        )

    def prepare_message(
        self,
        *,
        text: str,
        channel_name: str,
        author: str,
    ) -> MessagePreparation:
        alias_index = build_channel_alias_index(self.chat_memory, channel_name)
        resolved_text, alias_replacements = resolve_known_aliases(text, alias_index)
        alias_context = "aucun"
        if alias_replacements:
            alias_context = "\n".join(
                f"alias local: {alias} = {canonical}" for alias, canonical in alias_replacements
            )

        focus = infer_recent_focus(self.chat_memory, channel_name, author)
        resolved_text, focus_notes = resolve_recent_reference_subjects(resolved_text, focus)
        focus_context = "\n".join(focus_notes) if focus_notes else "aucun"
        facts_context = build_facts_context(
            self.facts_memory,
            channel_name,
            author,
            resolved_text,
        )
        author_is_owner = author == channel_name
        event_type = classify_conversation_event(resolved_text, author_is_owner=author_is_owner)

        related_viewer = ""
        related_message = ""
        related_turn_id = ""
        reply_to_turn_id = ""
        if likely_needs_memory_context(resolved_text):
            reply_target_turn = find_reply_target_turn(
                self.conversation_graph,
                channel_name=channel_name,
                author_name=author,
            )
            if reply_target_turn:
                reply_to_turn_id = normalize_spaces(reply_target_turn.get("turn_id", ""))

        if event_type in {"correction", "owner_correction"}:
            related_turn = find_related_conversation_turn(
                self.conversation_graph,
                channel_name=channel_name,
                author_name=author,
                message_text=resolved_text,
            )
            if related_turn is None:
                related_turn = find_related_global_turn(
                    self.chat_memory,
                    channel_name=channel_name,
                    message_text=resolved_text,
                    author_name=author,
                )
            if related_turn:
                related_viewer = normalize_spaces(related_turn.get("viewer", related_turn.get("speaker", "")))
                related_message = sanitize_user_text(
                    related_turn.get("viewer_message", related_turn.get("message_text", ""))
                )
                related_turn_id = normalize_spaces(related_turn.get("turn_id", ""))

        riddle_related = looks_like_riddle_message(resolved_text)
        riddle_thread_reset = starts_new_riddle_thread(resolved_text)
        riddle_thread_close = closes_riddle_thread(resolved_text)
        specialized_local_thread = riddle_related or riddle_thread_reset or riddle_thread_close

        return MessagePreparation(
            resolved_text=resolved_text,
            alias_context=alias_context,
            focus_context=focus_context,
            facts_context=facts_context,
            author_is_owner=author_is_owner,
            event_type=event_type,
            related_viewer=related_viewer,
            related_message=related_message,
            related_turn_id=related_turn_id,
            reply_to_turn_id=reply_to_turn_id,
            riddle_related=riddle_related,
            riddle_thread_reset=riddle_thread_reset,
            riddle_thread_close=riddle_thread_close,
            specialized_local_thread=specialized_local_thread,
        )

    def log_prepared_message_state(self, prepared: MessagePreparation) -> None:
        if not prepared.specialized_local_thread:
            return
        print("🧩 Charade/devinette détectée", flush=True)
        increment_chat_memory_counter(
            self.chat_memory,
            "riddle_messages_seen",
        )
        if prepared.riddle_thread_reset:
            print("🧹 Nouveau fil de charade détecté", flush=True)
        elif prepared.riddle_thread_close:
            print("✅ Clôture de charade détectée", flush=True)

    def build_runtime_decision(
        self,
        *,
        msg_id: str | None,
        channel_name: str,
        author: str,
        clean_viewer_message: str,
        prepared: MessagePreparation,
    ):
        repeated_social_count = viewer_recent_social_redundancy(
            self.chat_memory,
            channel_name,
            author,
            clean_viewer_message,
        )
        normalized_event = build_normalized_event(
            event_id=msg_id or "",
            channel=channel_name,
            author=author,
            timestamp="",
            text=prepared.resolved_text,
            metadata={"message_id": msg_id or ""},
        )
        return arbitrate_chat_message(
            event=normalized_event,
            clean_viewer_message=clean_viewer_message,
            author_is_owner=prepared.author_is_owner,
            riddle_related=prepared.riddle_related,
            riddle_thread_reset=prepared.riddle_thread_reset,
            riddle_thread_close=prepared.riddle_thread_close,
            asks_channel_content=asks_about_channel_content(prepared.resolved_text),
            repeated_social_count=repeated_social_count,
        )

    async def enqueue_message(self, queued_message: QueuedMessage) -> bool:
        broadcaster_name = normalize_spaces(getattr(queued_message.payload.broadcaster, "name", "")).lower()
        is_owner_message = (
            normalize_spaces(queued_message.author).lower() == broadcaster_name
            or self.is_owner_author(queued_message.author)
        )

        if self.message_queue.full():
            try:
                dropped = self.message_queue.get_nowait()
                print(f"↪️ File pleine, ancien message supprimé : {dropped.author}", flush=True)
            except asyncio.QueueEmpty:
                pass

        try:
            self.message_queue.put_nowait(queued_message)
            if is_owner_message and self.message_queue.qsize() > 1:
                self.message_queue._queue.rotate(1)
            print(
                f"🧾 Message mis en file ({self.message_queue.qsize()}/{CONFIG.message_queue_max_size})"
                + (" [priorité streamer]" if is_owner_message else ""),
                flush=True,
            )
            return True
        except asyncio.QueueFull:
            print("↪️ File pleine, message ignoré", flush=True)
            return False

    async def message_queue_worker(self) -> None:
        while True:
            queued_message = await self.message_queue.get()
            try:
                age_seconds = now_ts() - queued_message.received_at
                if age_seconds > CONFIG.message_queue_max_age_seconds:
                    print(f"↪️ Message expiré dans la file ({int(age_seconds)}s), ignoré", flush=True)
                    continue

                wait_seconds = self.seconds_until_ready(queued_message.author)
                if wait_seconds > 0:
                    print(f"⏳ Attente file avant traitement : {wait_seconds:.1f}s", flush=True)
                    await asyncio.sleep(wait_seconds)

                await self.process_queued_message(queued_message)
            finally:
                self.message_queue.task_done()

    async def process_queued_message(self, queued_message: QueuedMessage) -> None:
        payload = queued_message.payload
        text = queued_message.text
        clean_viewer_message = queued_message.clean_viewer_message
        author = queued_message.author
        msg_id = queued_message.msg_id
        channel_name = normalize_spaces(payload.broadcaster.name).lower()
        prepared = self.prepare_message(
            text=text,
            channel_name=channel_name,
            author=author,
        )
        resolved_text = prepared.resolved_text
        alias_context = prepared.alias_context
        focus_context = prepared.focus_context
        facts_context = prepared.facts_context
        author_is_owner = prepared.author_is_owner
        event_type = prepared.event_type
        related_viewer = prepared.related_viewer
        related_message = prepared.related_message
        related_turn_id = prepared.related_turn_id
        reply_to_turn_id = prepared.reply_to_turn_id
        riddle_related = prepared.riddle_related
        riddle_thread_reset = prepared.riddle_thread_reset
        riddle_thread_close = prepared.riddle_thread_close
        specialized_local_thread = prepared.specialized_local_thread
        self.log_prepared_message_state(prepared)
        decision = self.build_runtime_decision(
            msg_id=msg_id,
            channel_name=channel_name,
            author=author,
            clean_viewer_message=clean_viewer_message,
            prepared=prepared,
        )

        async with self.generation_lock:
            print(f"🧭 Décision : {decision.decision} [{decision.rule_id}]", flush=True)

            if await self.handle_non_model_decision(
                payload=payload,
                author=author,
                channel_name=channel_name,
                msg_id=msg_id,
                decision=decision,
                clean_viewer_message=clean_viewer_message,
                event_type=event_type,
                related_viewer=related_viewer,
                related_message=related_message,
                reply_to_turn_id=reply_to_turn_id,
                related_turn_id=related_turn_id,
                riddle_thread_reset=riddle_thread_reset,
                riddle_thread_close=riddle_thread_close,
                author_is_owner=author_is_owner,
            ):
                return

            await self.handle_model_decision_pipeline(
                payload=payload,
                author=author,
                channel_name=channel_name,
                clean_viewer_message=clean_viewer_message,
                resolved_text=resolved_text,
                msg_id=msg_id,
                author_is_owner=author_is_owner,
                event_type=event_type,
                related_viewer=related_viewer,
                related_message=related_message,
                reply_to_turn_id=reply_to_turn_id,
                related_turn_id=related_turn_id,
                riddle_related=riddle_related,
                riddle_thread_reset=riddle_thread_reset,
                riddle_thread_close=riddle_thread_close,
                specialized_local_thread=specialized_local_thread,
                decision=decision,
                alias_context=alias_context,
                focus_context=focus_context,
                facts_context=facts_context,
            )
            return

    async def reply_about_channel_content(self, payload: twitchio.ChatMessage, author: str) -> None:
        print("📺 Question sur le contenu de la chaîne", flush=True)

        profile = extract_channel_profile(self.history)
        summary = await asyncio.to_thread(
            summarize_channel_profile,
            profile,
            CONFIG.ollama_url,
            OLLAMA_MODEL,
            CONFIG.request_timeout_seconds,
            CONFIG.llm_provider,
            CONFIG.openai_api_key,
        )

        summary = smart_truncate(summary, MAX_OUTPUT_CHARS)
        if not summary or is_no_reply_signal(summary):
            print("↪️ Pas de résumé envoyé", flush=True)
            return

        if output_is_suspicious(summary):
            print("↪️ Résumé suspect bloqué", flush=True)
            return

        await self.send_channel_summary_reply(payload, author, summary)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        try:
            raw_text = payload.text or ""
            text = sanitize_user_text(raw_text)
            clean_viewer_message = sanitize_user_text(strip_trigger(text))
            author = (payload.chatter.name or "").lower()
            msg_id = getattr(payload, "id", None)

            print("--------------------------------------------------", flush=True)
            print("💬 MESSAGE REÇU", flush=True)
            print(f"Chaîne : {payload.broadcaster.name}", flush=True)
            print(f"Auteur : {payload.chatter.name}", flush=True)
            print(f"Texte brut : {raw_text}", flush=True)
            print(f"Texte  : {text}", flush=True)

            if msg_id and msg_id in self.recent_ids:
                print("↪️ Message déjà traité, ignoré", flush=True)
                return

            if msg_id:
                self.recent_ids.append(msg_id)

            if not author:
                print("↪️ Auteur vide, ignoré", flush=True)
                return

            if author == BOT_USERNAME:
                print("↪️ Message ignoré : envoyé par le bot", flush=True)
                return

            if BOT_TRIGGER not in text.lower():
                print("↪️ Pas de mention du bot, ignoré", flush=True)
                return

            if looks_like_prompt_injection(text):
                print("↪️ Tentative probable de prompt injection, ignorée", flush=True)
                return
            queued_message = QueuedMessage(
                payload=payload,
                text=text,
                clean_viewer_message=clean_viewer_message,
                author=author,
                msg_id=msg_id,
                received_at=now_ts(),
            )
            if self.queue_worker_task is None:
                await self.process_queued_message(queued_message)
            else:
                await self.enqueue_message(queued_message)

        except requests.HTTPError as exc:
            print(f"❌ Erreur HTTP : {type(exc).__name__}: {exc}", flush=True)
        except requests.RequestException as exc:
            print(f"❌ Erreur réseau : {type(exc).__name__}: {exc}", flush=True)
        except Exception as exc:
            print(f"❌ Erreur dans event_message : {type(exc).__name__}: {exc}", flush=True)

    async def event_error(self, payload):
        print(f"❌ event_error : {payload}", flush=True)

    async def close(self):
        if self.queue_worker_task is not None:
            self.queue_worker_task.cancel()
            try:
                await self.queue_worker_task
            except asyncio.CancelledError:
                pass
            self.queue_worker_task = None
        await super().close()


async def main():
    global OLLAMA_MODEL

    OLLAMA_MODEL = choose_model(
        CONFIG.default_ollama_model,
        provider=CONFIG.llm_provider,
        openai_chat_model=CONFIG.openai_chat_model,
    )
    await run_with_model(OLLAMA_MODEL)


async def run_with_model(model_name: str):
    global OLLAMA_MODEL

    OLLAMA_MODEL = model_name

    print("==================================================", flush=True)
    print("🚀 DÉMARRAGE BOT TWITCH + LLM", flush=True)
    print("==================================================", flush=True)
    print(f"CLIENT_ID OK      : {bool(CONFIG.client_id)}", flush=True)
    print(f"CLIENT_SECRET OK  : {bool(CONFIG.client_secret)}", flush=True)
    print(f"BOT_ID            : {CONFIG.bot_id}", flush=True)
    print(f"OWNER_ID          : {CONFIG.owner_id}", flush=True)
    print(f"CHANNEL           : {CONFIG.channel_name}", flush=True)
    print(f"BOT_TOKEN OK      : {bool(CONFIG.bot_token)}", flush=True)
    print(f"LLM_PROVIDER      : {CONFIG.llm_provider}", flush=True)
    print(f"LLM_MODEL         : {OLLAMA_MODEL}", flush=True)
    print(f"GLOBAL_COOLDOWN   : {CONFIG.global_cooldown_seconds}s", flush=True)
    print(f"USER_COOLDOWN     : {CONFIG.user_cooldown_seconds}s", flush=True)
    print(f"QUEUE_SIZE        : {CONFIG.message_queue_max_size}", flush=True)
    print(f"QUEUE_MAX_AGE     : {CONFIG.message_queue_max_age_seconds}s", flush=True)
    print("==================================================", flush=True)

    bot = Bot()

    try:
        async with bot:
            print("⏳ Login Twitch...", flush=True)
            await bot.login(token=CONFIG.bot_token)
            print("✅ Login OK", flush=True)

            print("⏳ Démarrage du bot...", flush=True)
            await bot.start()

    except KeyboardInterrupt:
        print("🛑 Arrêt demandé par l'utilisateur", flush=True)
    except Exception as exc:
        print(f"❌ Erreur critique : {type(exc).__name__}: {exc}", flush=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot Twitch + Ollama")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Lance le bot Twitch")
    subparsers.add_parser("get-token", help="Génère et enregistre un token Twitch pour le bot")

    return parser.parse_args()


def cli() -> int:
    args = parse_args()
    command = args.command or "run"

    if command == "get-token":
        env_path = str(Path(__file__).resolve().parent / ".env")
        return run_oauth_flow(CONFIG.client_id, CONFIG.client_secret, env_path=env_path)

    try:
        asyncio.run(main())
        return 0
    except KeyboardInterrupt:
        print("🛑 Arrêt demandé par l'utilisateur", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(cli())
