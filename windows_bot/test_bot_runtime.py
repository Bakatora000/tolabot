import asyncio
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot_ollama import Bot, QueuedMessage


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
        bot._bot_id = "bot-id"
        return bot

    async def test_enqueue_message_drops_oldest_when_queue_is_full(self):
        bot = self.make_bot()
        payload = SimpleNamespace(text="@AnneAuNimouss salut", chatter=SimpleNamespace(name="alice"), broadcaster=SimpleNamespace(name="expevay"), id="m1")
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
        payload = SimpleNamespace(text="@AnneAuNimouss salut", chatter=SimpleNamespace(name="alice"), broadcaster=SimpleNamespace(name="expevay"), id="m1")
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
            author="expevay",
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
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
        chatter = SimpleNamespace(name="expevay")
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
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
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
    @patch("bot_ollama.looks_like_prompt_injection", return_value=False)
    @patch("bot_ollama.asks_about_channel_content", return_value=False)
    async def test_event_message_uses_remote_memory_context_when_enabled(
        self,
        mock_channel_content,
        mock_injection,
        mock_ask_ollama,
        mock_get_memory_context,
        mock_mem0_enabled,
        mock_store_memory_turn,
    ):
        bot = self.make_bot()
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss tu te souviens de notre discussion ?",
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-2",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_called_once()
        self.assertEqual(mock_ask_ollama.call_args.args[5], "alice: ancien contexte")
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
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text="@AnneAuNimouss salut",
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
        self.assertEqual(kwargs["channel"], "expevay")
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
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
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
                "expevay": {
                    "global_turns": [],
                    "viewer_turns": {
                        "alice": [
                            {
                                "timestamp": "2026-03-23T12:00:00+00:00",
                                "channel": "expevay",
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
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
        chatter = SimpleNamespace(name="alice")
        payload = SimpleNamespace(
            text='@AnneAuNimouss "Mon tout est un mammifère qui vit dans l\'eau." Qui suis-je ?',
            chatter=chatter,
            broadcaster=broadcaster,
            id="msg-4",
        )

        await bot.event_message(payload)

        mock_get_memory_context.assert_not_called()
        self.assertEqual(mock_ask_ollama.call_args.args[7], "riddle_final")
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
                "expevay": {
                    "global_turns": [],
                    "viewer_turns": {
                        "expevay": [
                            {
                                "timestamp": "2026-03-23T12:00:00+00:00",
                                "channel": "expevay",
                                "viewer": "expevay",
                                "viewer_message": "Mon tout est un mammifère qui vit dans l'eau. Qui suis-je ?",
                                "bot_reply": "Baleine !",
                                "thread_boundary": "",
                            }
                        ]
                    },
                }
            }
        }
        broadcaster = SimpleNamespace(name="expevay", send_message=AsyncMock())
        chatter = SimpleNamespace(name="expevay")
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


if __name__ == "__main__":
    unittest.main()
