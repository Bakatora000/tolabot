import asyncio
import unittest
from collections import deque
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot_ollama
from bot_ollama import Bot, QueuedMessage
from runtime_types import DecisionResult


class BotRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def make_bot(self):
        bot = object.__new__(Bot)
        bot.last_global_reply_at = 0.0
        bot.last_user_reply_at = {}
        bot.generation_lock = asyncio.Lock()
        bot.message_queue = asyncio.Queue(maxsize=6)
        bot.queue_worker_task = None
        bot.recent_ids = deque(maxlen=200)
        bot.history = {"sessions": [], "current_session": None}
        bot.chat_memory = {"channels": {}}
        bot.conversation_graph = {"channels": {}}
        bot.facts_memory = {"channels": {}}
        bot._bot_id = "bot-id"
        return bot

    async def test_enqueue_message_drops_oldest_when_queue_is_full(self):
        bot = self.make_bot()
        payload = SimpleNamespace(text="@AnneAuNimouss salut", chatter=SimpleNamespace(name="alice"), broadcaster=SimpleNamespace(name="streamer"), id="m1")
        for idx in range(6):
            bot_queued_message = QueuedMessage(
                payload=payload,
                text=f"msg-{idx}",
                clean_viewer_message=f"msg-{idx}",
                author="alice",
                msg_id=f"m{idx}",
                received_at=100.0 + idx,
            )
            await bot.enqueue_message(bot_queued_message)

        newest = QueuedMessage(
            payload=payload,
            text="msg-6",
            clean_viewer_message="msg-6",
            author="alice",
            msg_id="m6",
            received_at=106.0,
        )
        await bot.enqueue_message(newest)

        self.assertEqual(bot.message_queue.qsize(), 6)
        first_remaining = bot.message_queue.get_nowait()
        self.assertEqual(first_remaining.msg_id, "m1")

    async def test_enqueue_message_prioritizes_streamer_messages(self):
        bot = self.make_bot()
        payload = SimpleNamespace(text="@AnneAuNimouss salut", chatter=SimpleNamespace(name="alice"), broadcaster=SimpleNamespace(name="streamer"), id="m1")
        viewer_message = QueuedMessage(
            payload=payload,
            text="viewer-msg",
            clean_viewer_message="viewer-msg",
            author="alice",
            msg_id="viewer-1",
            received_at=100.0,
        )
        owner_message = QueuedMessage(
            payload=payload,
            text="owner-msg",
            clean_viewer_message="owner-msg",
            author="streamer",
            msg_id="owner-1",
            received_at=101.0,
        )

        await bot.enqueue_message(viewer_message)
        await bot.enqueue_message(owner_message)

        first_message = bot.message_queue.get_nowait()
        self.assertEqual(first_message.msg_id, "owner-1")

    @patch("bot_ollama.now_ts", return_value=100.0)
    def test_mark_replied_updates_global_and_user_timestamps(self, mock_now):
        bot = self.make_bot()

        bot.mark_replied("alice")

        self.assertEqual(bot.last_global_reply_at, 100.0)
        self.assertEqual(bot.last_user_reply_at["alice"], 100.0)

    @patch("bot_ollama.now_ts", side_effect=[100.0, 101.0, 103.0])
    def test_cooldowns_follow_marked_timestamp(self, mock_now):
        bot = self.make_bot()
        bot.mark_replied("alice")

        self.assertTrue(bot.global_in_cooldown())
        self.assertFalse(bot.global_in_cooldown())

    @patch("bot_ollama.output_is_suspicious", return_value=False)
    @patch("bot_ollama.normalize_spaces", side_effect=lambda text: text.strip())
    @patch("bot_ollama.summarize_channel_profile", return_value="Résumé propre")
    @patch("bot_ollama.extract_channel_profile", return_value={"top_categories": [("Valheim", 2)], "recent_titles": ["Live"], "has_live_history": True})
    async def test_reply_about_channel_content_sends_message_and_marks_author(
        self,
        mock_extract,
        mock_summarize,
        mock_normalize,
        mock_suspicious,
    ):
        bot = self.make_bot()
        bot.mark_replied = unittest.mock.Mock()

        broadcaster = SimpleNamespace(send_message=AsyncMock())
        payload = SimpleNamespace(broadcaster=broadcaster)

        await bot.reply_about_channel_content(payload, "alice")

        broadcaster.send_message.assert_awaited_once_with(
            "@alice Résumé propre",
            sender="bot-id",
            token_for="bot-id",
        )
        bot.mark_replied.assert_called_once_with("alice")

    @patch("bot_ollama.append_chat_turn")
    @patch("bot_ollama.ask_ollama")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_partial_riddle_message_skips_model_call(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_append_chat_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="streamer")
        payload = SimpleNamespace(
            text='@AnneAuNimouss "Mon second est absent"',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-1",
        )

        await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        mock_append_chat_turn.assert_called_once()
        broadcaster.send_message.assert_not_awaited()

    @patch("bot_ollama.append_chat_turn")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_non_owner_memory_instruction_is_refused_without_model_or_remote_store(
        self,
        mock_channel_content,
        mock_injection,
        mock_append_chat_turn,
    ):
        bot = self.make_bot()
        bot.mark_replied = unittest.mock.Mock()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text='@AnneAuNimouss note que je joue à wow',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-memory-1",
        )

        with patch("bot_ollama.ask_ollama") as mock_ask_ollama, patch("bot_ollama.store_memory_turn") as mock_store_memory_turn:
            await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        mock_store_memory_turn.assert_not_called()
        broadcaster.send_message.assert_awaited_once_with(
            "@alice Je ne prends ce type de note mémoire que d'Expevay.",
            sender="bot-id",
            token_for="bot-id",
        )
        mock_append_chat_turn.assert_called_once()
        bot.mark_replied.assert_called_once_with("alice")

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "alice: ancien contexte", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="Salut Alice")
    @patch("bot_ollama.search_searxng")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_event_message_uses_remote_memory_context_when_enabled(
        self,
        mock_channel_content,
        mock_injection,
        mock_search_searxng,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss tu te souviens de notre discussion ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-2",
        )

        await bot.event_message(payload)

        mock_search_searxng.assert_not_called()
        mock_get_memory_context.assert_called_once()
        self.assertEqual(mock_ask_ollama.call_args.args[5], "alice: ancien contexte")
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=False)
    @patch("bot_ollama.build_web_search_context", return_value="[1] Météo Paris - Temps doux.")
    @patch("bot_ollama.search_searxng", return_value=[{"title": "Météo Paris", "content": "Temps doux.", "url": "https://example.com"}])
    @patch("bot_ollama.ask_ollama", return_value="Il fait doux aujourd'hui.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_ollama_can_receive_web_context_from_searxng(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_search_searxng,
        mock_build_web_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss quelle est la météo aujourd'hui ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-web-1",
        )

        web_config = replace(
            bot_ollama.CONFIG,
            web_search_enabled=True,
            web_search_provider="searxng",
            web_search_mode="auto",
            searxng_base_url="http://127.0.0.1:8888",
            web_search_timeout_seconds=8,
            web_search_max_results=5,
        )
        with patch("bot_ollama.CONFIG", web_config):
            await bot.event_message(payload)

        mock_search_searxng.assert_called_once()
        self.assertEqual(mock_ask_ollama.call_args.args[7], "[1] Météo Paris - Temps doux.")
        broadcaster.send_message.assert_awaited_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=False)
    @patch("bot_ollama.build_web_search_context", return_value="[1] Météo Lyon - Vendredi éclaircies.")
    @patch("bot_ollama.search_searxng", return_value=[{"title": "Météo Lyon", "content": "Vendredi éclaircies.", "url": "https://example.com"}])
    @patch("bot_ollama.ask_ollama", return_value="Selon les sources web, vendredi à Lyon il devrait y avoir des éclaircies.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_runtime_recomputes_web_decision_when_prefetch_does_not_match(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_search_searxng,
        mock_build_web_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "viewer_turns": {
                        "alice": [
                            {"role": "viewer", "text": "quel temps fera t il demain sur Lyon ?", "ts": "2026-03-25T10:00:00Z"},
                            {"role": "bot", "text": "Selon les sources web, demain à Lyon les températures varient entre 6 et 15°C.", "ts": "2026-03-25T10:00:01Z"},
                        ]
                    },
                    "global_turns": [],
                    "counters": {},
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss et vendredi?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-web-followup-1",
        )

        decision_side_effects = [
            DecisionResult(decision="skip", rule_id="no_match", reason="no_match", needs_web=False),
            DecisionResult(decision="web_search", rule_id="context_followup", reason="context_followup", needs_web=True, query="météo vendredi à Lyon"),
        ]

        web_config = replace(
            bot_ollama.CONFIG,
            web_search_enabled=True,
            web_search_provider="searxng",
            web_search_mode="auto",
            searxng_base_url="http://127.0.0.1:8888",
            web_search_timeout_seconds=8,
            web_search_max_results=5,
        )
        with patch("bot_ollama.CONFIG", web_config), patch("bot_ollama.build_web_search_decision", side_effect=decision_side_effects) as mock_decision:
            await bot.event_message(payload)

        self.assertEqual(mock_decision.call_count, 2)
        mock_search_searxng.assert_called_once_with(
            query="météo vendredi à Lyon",
            base_url="http://127.0.0.1:8888",
            timeout_seconds=8,
            max_results=5,
        )
        broadcaster.send_message.assert_awaited_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "alice: vieux souvenir mem0", "global_context": "aucun", "items": []})
    @patch("bot_ollama.build_web_search_context", return_value="[1] Météo Lyon - Vendredi éclaircies.")
    @patch("bot_ollama.search_searxng", return_value=[{"title": "Météo Lyon", "content": "Vendredi éclaircies.", "url": "https://example.com"}])
    @patch("bot_ollama.ask_ollama", return_value="Selon les sources web, vendredi à Lyon il devrait y avoir des éclaircies.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_runtime_drops_mem0_from_model_context_when_web_search_is_used(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_search_searxng,
        mock_build_web_context,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "viewer_turns": {
                        "alice": [
                            {"role": "viewer", "text": "quel temps fera t il demain sur Lyon ?", "ts": "2026-03-25T10:00:00Z"},
                            {"role": "bot", "text": "Selon les sources web, demain à Lyon les températures varient entre 6 et 15°C.", "ts": "2026-03-25T10:00:01Z"},
                        ]
                    },
                    "global_turns": [],
                    "counters": {},
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss et vendredi?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-web-followup-2",
        )

        decision_side_effects = [
            DecisionResult(decision="skip", rule_id="no_match", reason="no_match", needs_web=False),
            DecisionResult(decision="web_search", rule_id="context_followup", reason="context_followup", needs_web=True, query="météo vendredi à Lyon"),
        ]

        web_config = replace(
            bot_ollama.CONFIG,
            web_search_enabled=True,
            web_search_provider="searxng",
            web_search_mode="auto",
            searxng_base_url="http://127.0.0.1:8888",
            web_search_timeout_seconds=8,
            web_search_max_results=5,
        )
        with patch("bot_ollama.CONFIG", web_config), patch("bot_ollama.build_web_search_decision", side_effect=decision_side_effects):
            await bot.event_message(payload)

        self.assertEqual(mock_ask_ollama.call_args.args[5], "alice: quel temps fera t il demain sur Lyon ?\nbot: Selon les sources web, demain à Lyon les températures varient entre 6 et 15°C.")
        self.assertNotIn("vieux souvenir mem0", mock_ask_ollama.call_args.args[5])
        mock_search_searxng.assert_called_once()
        mock_store_memory_turn.assert_not_called()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context")
    @patch("bot_ollama.build_web_search_context", return_value="[1] Météo Paris - Temps doux.")
    @patch("bot_ollama.search_searxng", return_value=[{"title": "Météo Paris", "content": "Temps doux.", "url": "https://example.com"}])
    @patch("bot_ollama.ask_ollama", return_value="Il fait doux aujourd'hui.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_external_web_query_skips_mem0_context_lookup(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_search_searxng,
        mock_build_web_context,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss quelle est la météo aujourd'hui à Paris ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-web-no-mem0-1",
        )

        web_config = replace(
            bot_ollama.CONFIG,
            web_search_enabled=True,
            web_search_provider="searxng",
            web_search_mode="auto",
            searxng_base_url="http://127.0.0.1:8888",
            web_search_timeout_seconds=8,
            web_search_max_results=5,
        )
        with patch("bot_ollama.CONFIG", web_config):
            await bot.event_message(payload)

        mock_get_memory_context.assert_not_called()
        mock_search_searxng.assert_called_once()
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context")
    @patch("bot_ollama.ask_ollama", return_value="Oui, ca se rafraichit deja ce soir.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_reaction_followup_skips_mem0_lookup(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "alice",
                            "viewer_message": "que dit la météo pour demain soir à Lyon?",
                            "bot_reply": "Selon les prévisions disponibles, la température à Lyon ce soir devrait être d'environ 13°C.",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {
                        "alice": [
                            {
                                "timestamp": "2026-03-25T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "alice",
                                "viewer_message": "que dit la météo pour demain soir à Lyon?",
                                "bot_reply": "Selon les prévisions disponibles, la température à Lyon ce soir devrait être d'environ 13°C.",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss il fait deja froid des ce soir??",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-reaction-followup-1",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_not_called()
        self.assertIn("13°C", mock_ask_ollama.call_args.args[5])
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="MissCouette76 joue à Valheim.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_alias_is_resolved_before_memory_lookup_and_model_call(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "dame_gaby",
                            "viewer_message": "MissCouette76 est le plus souvent appelait MissCouette ou Caouette",
                            "bot_reply": "C'est noté !",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {},
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="dame_gaby")
        payload = SimpleNamespace(
            text="@AnneAuNimouss que peux tu me dire sur Caouette ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-alias-1",
        )

        await bot.event_message(payload)

        self.assertIn("MissCouette76", mock_get_memory_context.call_args.kwargs["message"])
        self.assertIn("MissCouette76", mock_ask_ollama.call_args.args[1])
        self.assertIn("alias local: caouette = MissCouette76", mock_ask_ollama.call_args.args[6])
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="Dame_Gaby fait partie des Valkyrottes.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_recent_subject_is_resolved_before_memory_lookup_and_model_call(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "expevay",
                            "viewer_message": "qui est Dame_Gaby ?",
                            "bot_reply": "Dame_Gaby joue à Valheim.",
                            "thread_boundary": "",
                            "event_type": "message",
                            "related_viewer": "",
                            "related_message": "",
                        }
                    ],
                    "viewer_turns": {
                        "expevay": [
                            {
                                "timestamp": "2026-03-25T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "expevay",
                                "viewer_message": "qui est Dame_Gaby ?",
                                "bot_reply": "Dame_Gaby joue à Valheim.",
                                "thread_boundary": "",
                                "event_type": "message",
                                "related_viewer": "",
                                "related_message": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="expevay")
        payload = SimpleNamespace(
            text="@AnneAuNimouss elle fait partie de quel groupe avec 2 autres personnes ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-focus-1",
        )

        await bot.event_message(payload)

        self.assertIn("Dame_Gaby", mock_get_memory_context.call_args.kwargs["message"])
        self.assertIn("Dame_Gaby", mock_ask_ollama.call_args.args[1])
        self.assertIn("sujet recent: Dame_Gaby", mock_ask_ollama.call_args.args[6])
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="Je ne sais pas. Tu confirmes ?")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_uncertain_third_party_fact_is_flagged_when_talking_to_subject(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.facts_memory = {
            "channels": {
                "streamer": {
                    "facts": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "subject": "misscouette76",
                            "predicate": "description",
                            "value": "aussi appelée MissCouette",
                            "source_speaker": "dame_gaby",
                            "verification_state": "third_party_reported",
                        }
                    ]
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="misscouette76")
        payload = SimpleNamespace(
            text="@AnneAuNimouss que sais tu sur moi ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-fact-1",
        )

        await bot.event_message(payload)

        self.assertIn("fait incertain rapporte par dame_gaby sur toi", mock_ask_ollama.call_args.args[6].lower())
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch(
        "bot_ollama.get_memory_context",
        return_value={
            "viewer_context": "aucun",
            "global_context": "bob: hors sujet\nbot: réponse hors sujet",
            "items": [],
        },
    )
    @patch("bot_ollama.ask_ollama", return_value="Bien vu, on reste sur MissCouette.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_local_graph_context_is_prioritized_over_remote_global_context(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-23T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "viewer1",
                            "viewer_message": "que penses tu de MissCouette ?",
                            "bot_reply": "Elle joue à Enshrouded.",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {},
                }
            }
        }
        bot.conversation_graph = {
            "channels": {
                "streamer": {
                    "turns": [
                        {
                            "turn_id": "t1",
                            "timestamp": "2026-03-23T12:00:00+00:00",
                            "channel": "streamer",
                            "speaker": "viewer1",
                            "message_text": "que penses tu de MissCouette ?",
                            "bot_reply": "Elle joue à Enshrouded.",
                            "event_type": "message",
                            "target_viewers": [],
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "",
                        },
                        {
                            "turn_id": "t2",
                            "timestamp": "2026-03-23T12:01:00+00:00",
                            "channel": "streamer",
                            "speaker": "streamer",
                            "message_text": "je parlais effectivement de MissCouette. MrAdel779 est hors sujet",
                            "bot_reply": "Tu as raison, on reste sur MissCouette.",
                            "event_type": "owner_correction",
                            "target_viewers": ["viewer1"],
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "t1",
                        },
                    ]
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="streamer")
        payload = SimpleNamespace(
            text="@AnneAuNimouss du coup que penses tu d'elle ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-local-priority-1",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_called_once()
        global_context = mock_ask_ollama.call_args.args[6]
        self.assertIn("MissCouette", global_context)
        self.assertNotIn("bob: hors sujet", global_context.lower())
        self.assertNotIn("réponse hors sujet", global_context.lower())
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch(
        "bot_ollama.get_memory_context",
        return_value={
            "viewer_context": "alice: vieux souvenir distant",
            "global_context": "aucun",
            "items": [],
        },
    )
    @patch("bot_ollama.ask_ollama", return_value="Salut Alice")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_local_viewer_thread_is_not_merged_with_mem0_viewer_context(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "alice",
                            "viewer_message": "tu te souviens de notre discussion ?",
                            "bot_reply": "On parlait de Valheim.",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {
                        "alice": [
                            {
                                "timestamp": "2026-03-25T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "alice",
                                "viewer_message": "tu te souviens de notre discussion ?",
                                "bot_reply": "On parlait de Valheim.",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss tu te souviens de notre discussion ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-local-viewer-priority-1",
        )

        await bot.event_message(payload)

        self.assertNotIn("vieux souvenir distant", mock_ask_ollama.call_args.args[5])
        self.assertIn("On parlait de Valheim.", mock_ask_ollama.call_args.args[5])
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="Bien vu, il parlait sans doute de Dame_Gaby.")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_owner_correction_keeps_recent_local_global_context_when_mem0_enabled(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-23T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "viewer1",
                            "viewer_message": "que penses tu de @Dame_Gaby ?",
                            "bot_reply": "Gaby est une présentatrice TV.",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {
                        "viewer1": [
                            {
                                "timestamp": "2026-03-23T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "viewer1",
                                "viewer_message": "que penses tu de @Dame_Gaby ?",
                                "bot_reply": "Gaby est une présentatrice TV.",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="streamer")
        payload = SimpleNamespace(
            text="@AnneAuNimouss je pense qu'il parlait de Dame_Gaby et pas Gaby",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-correction-1",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_called_once()
        self.assertIn("viewer1: que penses tu de @Dame_Gaby ?", mock_ask_ollama.call_args.args[6])
        self.assertIn("bot: Gaby est une présentatrice TV.", mock_ask_ollama.call_args.args[6])
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_called_once()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="Réponse finale")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_event_message_stores_remote_memory_after_successful_reply(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss tu es la ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-3",
        )

        await bot.event_message(payload)

        mock_store_memory_turn.assert_called_once()
        broadcaster.send_message.assert_awaited_once_with(
            "@alice Réponse finale",
            sender="bot-id",
            token_for="bot-id",
        )
        _, kwargs = mock_store_memory_turn.call_args
        self.assertEqual(kwargs["channel"], "streamer")
        self.assertEqual(kwargs["viewer"], "alice")
        self.assertEqual(kwargs["bot_reply"], "Réponse finale")
        self.assertEqual(kwargs["metadata"]["message_id"], "msg-3")

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context", return_value={"viewer_context": "aucun", "global_context": "aucun", "items": []})
    @patch("bot_ollama.ask_ollama", return_value="NO_REPLY")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_no_reply_sends_generic_fallback(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.mark_replied = unittest.mock.Mock()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss pourquoi tu ne veux pas parler ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-no-reply-1",
        )

        await bot.event_message(payload)

        broadcaster.send_message.assert_awaited_once()
        sent_message = broadcaster.send_message.await_args.args[0]
        self.assertIn("@alice", sent_message)
        self.assertIn("J'ai lu ton message", sent_message)
        mock_store_memory_turn.assert_not_called()
        bot.mark_replied.assert_called_once_with("alice")

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context")
    @patch("bot_ollama.ask_ollama", return_value="Réponse finale")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_riddle_final_stays_on_local_memory_and_skips_remote_storage(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [],
                    "viewer_turns": {
                        "alice": [
                            {
                                "timestamp": "2026-03-23T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "alice",
                                "viewer_message": "Mon premier n'est pas haut.",
                                "bot_reply": "",
                                "thread_boundary": "start",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text='@AnneAuNimouss "Mon tout est un mammifère qui vit dans l\'eau." Qui suis-je ?',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-4",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_not_called()
        self.assertEqual(mock_ask_ollama.call_args.args[8], "riddle_final")
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_not_called()

    @patch("bot_ollama.store_memory_turn")
    @patch("bot_ollama.is_mem0_enabled", return_value=True)
    @patch("bot_ollama.get_memory_context")
    @patch("bot_ollama.ask_ollama", return_value="Merci !")
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_riddle_closure_message_uses_local_thread_not_remote_memory(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [],
                    "viewer_turns": {
                        "streamer": [
                            {
                                "timestamp": "2026-03-23T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "streamer",
                                "viewer_message": "Mon tout est un mammifère qui vit dans l'eau. Qui suis-je ?",
                                "bot_reply": "Baleine !",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="streamer")
        payload = SimpleNamespace(
            text='@AnneAuNimouss Bravo! Bien joué.',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-5",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_not_called()
        broadcaster.send_message.assert_awaited_once()
        mock_store_memory_turn.assert_not_called()

    @patch("bot_ollama.ask_ollama")
    async def test_short_acknowledgment_skips_model_and_chat_reply(self, mock_ask_ollama):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="streamer")
        payload = SimpleNamespace(
            text='@AnneAuNimouss très bien!',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-ack-1",
        )

        await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        broadcaster.send_message.assert_not_awaited()
        channel_data = bot.chat_memory["channels"]["streamer"]
        self.assertEqual(channel_data["global_turns"][-1]["viewer_message"], "très bien!")
        self.assertEqual(channel_data["global_turns"][-1]["bot_reply"], "")

    @patch("bot_ollama.ask_ollama")
    async def test_passive_closing_gets_local_goodbye_reply(self, mock_ask_ollama):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="dame_gaby")
        payload = SimpleNamespace(
            text='@AnneAuNimouss aurevoir',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-bye-1",
        )

        await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        broadcaster.send_message.assert_awaited_once_with(
            "@dame_gaby Au revoir !",
            sender="bot-id",
            token_for="bot-id",
        )
        channel_data = bot.chat_memory["channels"]["streamer"]
        self.assertEqual(channel_data["global_turns"][-1]["viewer_message"], "aurevoir")
        self.assertEqual(channel_data["global_turns"][-1]["bot_reply"], "Au revoir !")

    @patch("bot_ollama.ask_ollama")
    async def test_greeting_gets_local_hello_reply(self, mock_ask_ollama):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text='@AnneAuNimouss bonjour',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-hello-1",
        )

        await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        broadcaster.send_message.assert_awaited_once_with(
            "@alice Bonjour !",
            sender="bot-id",
            token_for="bot-id",
        )

    @patch("bot_ollama.viewer_recent_social_redundancy", return_value=1)
    @patch("bot_ollama.ask_ollama")
    async def test_repeated_greeting_gets_redundancy_reply(self, mock_ask_ollama, mock_redundancy):
        bot = self.make_bot()
        bot.chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "alice",
                            "viewer_message": "bonjour",
                            "bot_reply": "Bonjour !",
                            "thread_boundary": "",
                        }
                    ],
                    "viewer_turns": {
                        "alice": [
                            {
                                "timestamp": "2026-03-25T12:00:00+00:00",
                                "channel": "streamer",
                                "viewer": "alice",
                                "viewer_message": "bonjour",
                                "bot_reply": "Bonjour !",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="streamer", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text='@AnneAuNimouss salut',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-hello-2",
        )

        await bot.event_message(payload)

        mock_ask_ollama.assert_not_called()
        mock_redundancy.assert_called_once()
        broadcaster.send_message.assert_awaited_once_with(
            "@alice Bonjour, mais tu m'as deja salue je crois.",
            sender="bot-id",
            token_for="bot-id",
        )


if __name__ == "__main__":
    unittest.main()
