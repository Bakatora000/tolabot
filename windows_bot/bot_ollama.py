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
    MAX_OUTPUT_CHARS,
    MAX_VIEWER_CHAT_TURNS,
    append_channel_update,
    append_chat_turn,
    build_channel_alias_index,
    asks_about_channel_content,
    build_chat_context,
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
from context_sources import build_context_source_results, make_context_source_result, merge_context_text
from decision_tree import build_web_search_decision
from facts_memory import (
    append_reported_facts,
    build_facts_context,
    load_facts_memory,
    prune_facts_memory,
)
from memory_client import MemoryApiError, get_memory_context, is_mem0_enabled, store_memory_turn
from ollama_client import ask_ollama, choose_model, summarize_channel_profile
from runtime_pipeline import (
    build_incoming_message_data,
    build_runtime_context_bundle,
    dispatch_incoming_message,
    enqueue_message as runtime_enqueue_message,
    handle_non_model_decision,
    handle_model_decision_pipeline,
    log_incoming_message,
    message_queue_worker as runtime_message_queue_worker,
    persist_local_and_remote_turn,
    persist_local_turn,
    reply_about_channel_content as runtime_reply_about_channel_content,
    remember_remote_turn,
    send_channel_summary_reply,
    should_ignore_incoming_message,
)
from runtime_types import MessagePreparation, QueuedMessageContext, RuntimePipelineDeps
from twitch_auth import run_oauth_flow
from web_search_client import build_web_search_context, search_searxng, should_enable_web_search

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
            persist_local_and_remote_turn(
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
                config=CONFIG,
                should_use_remote_memory=self.should_use_remote_memory(),
                facts_memory=self.facts_memory,
                chat_memory=self.chat_memory,
                conversation_graph=self.conversation_graph,
                append_reported_facts_fn=append_reported_facts,
                append_chat_turn_fn=append_chat_turn,
                append_conversation_turn_fn=append_conversation_turn,
                store_memory_turn_fn=store_memory_turn,
            )
            print("↪️ Pas de réponse envoyée", flush=True)
            return True

        await self.send_chat_reply(payload.broadcaster, author, fallback_reply, log_prefix="📤 Fallback NO_REPLY")
        persist_local_turn(
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
            config=CONFIG,
            facts_memory=self.facts_memory,
            chat_memory=self.chat_memory,
            conversation_graph=self.conversation_graph,
            append_reported_facts_fn=append_reported_facts,
            append_chat_turn_fn=append_chat_turn,
            append_conversation_turn_fn=append_conversation_turn,
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
        persist_local_and_remote_turn(
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
            config=CONFIG,
            should_use_remote_memory=self.should_use_remote_memory(),
            facts_memory=self.facts_memory,
            chat_memory=self.chat_memory,
            conversation_graph=self.conversation_graph,
            append_reported_facts_fn=append_reported_facts,
            append_chat_turn_fn=append_chat_turn,
            append_conversation_turn_fn=append_conversation_turn,
            store_memory_turn_fn=store_memory_turn,
        )
        self.mark_replied(author)

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

    def build_runtime_pipeline_deps(self) -> RuntimePipelineDeps:
        def persist_local_turn_bound(**kwargs) -> None:
            persist_local_turn(
                **kwargs,
                config=CONFIG,
                facts_memory=self.facts_memory,
                chat_memory=self.chat_memory,
                conversation_graph=self.conversation_graph,
                append_reported_facts_fn=append_reported_facts,
                append_chat_turn_fn=append_chat_turn,
                append_conversation_turn_fn=append_conversation_turn,
            )

        def persist_local_and_remote_turn_bound(**kwargs) -> None:
            persist_local_and_remote_turn(
                **kwargs,
                config=CONFIG,
                should_use_remote_memory=self.should_use_remote_memory(),
                facts_memory=self.facts_memory,
                chat_memory=self.chat_memory,
                conversation_graph=self.conversation_graph,
                append_reported_facts_fn=append_reported_facts,
                append_chat_turn_fn=append_chat_turn,
                append_conversation_turn_fn=append_conversation_turn,
                store_memory_turn_fn=store_memory_turn,
            )

        def remember_remote_turn_bound(*args, **kwargs) -> bool:
            return remember_remote_turn(
                channel_name=args[0],
                author=args[1],
                user_message=args[2],
                config=CONFIG,
                should_use_remote_memory=self.should_use_remote_memory(),
                bot_reply=kwargs.get("bot_reply", ""),
                message_id=kwargs.get("message_id"),
                allow_remote=kwargs.get("allow_remote", True),
                author_is_owner=kwargs.get("author_is_owner", False),
                store_memory_turn_fn=store_memory_turn,
            )

        def build_runtime_context_bundle_bound(**kwargs):
            return build_runtime_context_bundle(
                **kwargs,
                config=CONFIG,
                should_use_remote_memory=self.should_use_remote_memory_for_message(False),
                get_specialized_local_context_fn=self.get_specialized_local_context,
                get_context_with_fallback_fn=self.get_context_with_fallback,
                build_web_search_decision_fn=build_web_search_decision,
                build_web_search_context_fn=build_web_search_context,
                search_searxng_fn=search_searxng,
            )

        return RuntimePipelineDeps(
            persist_local_turn_fn=persist_local_turn_bound,
            persist_local_and_remote_turn_fn=persist_local_and_remote_turn_bound,
            remember_remote_turn_fn=remember_remote_turn_bound,
            build_runtime_context_bundle_fn=build_runtime_context_bundle_bound,
        )

    def build_queued_message_context(self, queued_message: QueuedMessage) -> QueuedMessageContext:
        channel_name = normalize_spaces(queued_message.payload.broadcaster.name).lower()
        prepared = self.prepare_message(
            text=queued_message.text,
            channel_name=channel_name,
            author=queued_message.author,
        )
        self.log_prepared_message_state(prepared)
        decision = self.build_runtime_decision(
            msg_id=queued_message.msg_id,
            channel_name=channel_name,
            author=queued_message.author,
            clean_viewer_message=queued_message.clean_viewer_message,
            prepared=prepared,
        )
        return QueuedMessageContext(
            queued_message=queued_message,
            channel_name=channel_name,
            prepared=prepared,
            decision=decision,
            pipeline_deps=self.build_runtime_pipeline_deps(),
        )

    async def enqueue_message(self, queued_message: QueuedMessage) -> bool:
        return await runtime_enqueue_message(
            queued_message=queued_message,
            message_queue=self.message_queue,
            max_queue_size=CONFIG.message_queue_max_size,
            is_owner_author_fn=self.is_owner_author,
            normalize_spaces_fn=normalize_spaces,
        )

    async def message_queue_worker(self) -> None:
        await runtime_message_queue_worker(
            message_queue=self.message_queue,
            process_queued_message_fn=self.process_queued_message,
            seconds_until_ready_fn=self.seconds_until_ready,
            now_fn=now_ts,
            max_age_seconds=CONFIG.message_queue_max_age_seconds,
        )

    async def process_queued_message(self, queued_message: QueuedMessage) -> None:
        context = self.build_queued_message_context(queued_message)
        payload = context.queued_message.payload
        clean_viewer_message = context.queued_message.clean_viewer_message
        author = context.queued_message.author
        msg_id = context.queued_message.msg_id
        channel_name = context.channel_name
        prepared = context.prepared
        decision = context.decision
        pipeline_deps = context.pipeline_deps

        async with self.generation_lock:
            print(f"🧭 Décision : {decision.decision} [{decision.rule_id}]", flush=True)

            if await handle_non_model_decision(
                payload=payload,
                author=author,
                channel_name=channel_name,
                msg_id=msg_id,
                decision=decision,
                clean_viewer_message=clean_viewer_message,
                event_type=prepared.event_type,
                related_viewer=prepared.related_viewer,
                related_message=prepared.related_message,
                reply_to_turn_id=prepared.reply_to_turn_id,
                related_turn_id=prepared.related_turn_id,
                riddle_thread_reset=prepared.riddle_thread_reset,
                riddle_thread_close=prepared.riddle_thread_close,
                author_is_owner=prepared.author_is_owner,
                reply_about_channel_content_fn=self.reply_about_channel_content,
                send_chat_reply_fn=self.send_chat_reply,
                persist_local_turn_fn=pipeline_deps.persist_local_turn_fn,
                persist_local_and_remote_turn_fn=pipeline_deps.persist_local_and_remote_turn_fn,
                remember_remote_turn_fn=pipeline_deps.remember_remote_turn_fn,
                mark_replied_fn=self.mark_replied,
            ):
                return

            await handle_model_decision_pipeline(
                payload=payload,
                author=author,
                channel_name=channel_name,
                clean_viewer_message=clean_viewer_message,
                resolved_text=prepared.resolved_text,
                msg_id=msg_id,
                author_is_owner=prepared.author_is_owner,
                event_type=prepared.event_type,
                related_viewer=prepared.related_viewer,
                related_message=prepared.related_message,
                reply_to_turn_id=prepared.reply_to_turn_id,
                related_turn_id=prepared.related_turn_id,
                riddle_related=prepared.riddle_related,
                riddle_thread_reset=prepared.riddle_thread_reset,
                riddle_thread_close=prepared.riddle_thread_close,
                specialized_local_thread=prepared.specialized_local_thread,
                decision=decision,
                alias_context=prepared.alias_context,
                focus_context=prepared.focus_context,
                facts_context=prepared.facts_context,
                config=CONFIG,
                model=OLLAMA_MODEL,
                ask_fn=ask_ollama,
                max_output_chars=MAX_OUTPUT_CHARS,
                suspicious_output_checker=output_is_suspicious,
                partial_riddle_checker=is_partial_riddle_message,
                riddle_refusal_checker=is_riddle_refusal_reply,
                memory_context_checker=likely_needs_memory_context,
                build_runtime_context_bundle_fn=pipeline_deps.build_runtime_context_bundle_fn,
                handle_model_no_reply_fn=self.handle_model_no_reply,
                persist_local_and_remote_turn_fn=pipeline_deps.persist_local_and_remote_turn_fn,
                handle_model_reply_result_fn=self.handle_model_reply_result,
                increment_memory_helpful_fn=lambda: increment_chat_memory_counter(
                    self.chat_memory,
                    "memory_helpful_replies",
                ),
                debug_chat_memory=CONFIG.debug_chat_memory,
            )
            return

    async def reply_about_channel_content(self, payload: twitchio.ChatMessage, author: str) -> None:
        await runtime_reply_about_channel_content(
            bot=self,
            payload=payload,
            author=author,
            history=self.history,
            ollama_url=CONFIG.ollama_url,
            model=OLLAMA_MODEL,
            request_timeout_seconds=CONFIG.request_timeout_seconds,
            llm_provider=CONFIG.llm_provider,
            openai_api_key=CONFIG.openai_api_key,
            max_output_chars=MAX_OUTPUT_CHARS,
            extract_channel_profile_fn=extract_channel_profile,
            summarize_channel_profile_fn=summarize_channel_profile,
            suspicious_output_checker=output_is_suspicious,
        )

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        try:
            await dispatch_incoming_message(
                payload=payload,
                recent_ids=self.recent_ids,
                queue_worker_task=self.queue_worker_task,
                enqueue_message_fn=self.enqueue_message,
                process_queued_message_fn=self.process_queued_message,
                queued_message_factory=QueuedMessage,
                now_fn=now_ts,
                injection_checker=looks_like_prompt_injection,
            )

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
