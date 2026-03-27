import asyncio
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from runtime_types import DecisionResult
from runtime_pipeline import (
    build_runtime_context_bundle,
    dispatch_incoming_message,
    handle_non_model_decision,
    message_queue_worker,
)


class RuntimePipelineTests(unittest.IsolatedAsyncioTestCase):
    @patch("runtime_pipeline.build_homegraph_context_source")
    def test_build_runtime_context_bundle_appends_local_homegraph_context(self, mock_homegraph_source):
        decision = DecisionResult(
            decision="reply",
            rule_id="reply_when_addressed",
            reason="addressed",
            needs_long_memory=False,
        )
        mock_homegraph_source.return_value = SimpleNamespace(
            source_id="homegraph_local",
            available=True,
            priority=87,
            confidence=0.84,
            stale=False,
            text_block="Contexte viewer:\n- joue souvent a Valheim",
            meta={},
        )
        config = SimpleNamespace(
            web_search_enabled=False,
            web_search_provider="searxng",
            web_search_mode="auto",
            homegraph_local_enabled=True,
            homegraph_db_path="C:/tmp/homegraph.sqlite3",
        )

        bundle = build_runtime_context_bundle(
            resolved_text="tu joues a quoi",
            payload=SimpleNamespace(broadcaster=SimpleNamespace(name="streamer")),
            channel_name="streamer",
            author="alice",
            prefer_active_thread=True,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            specialized_local_thread=False,
            decision=decision,
            alias_context="aucun",
            focus_context="aucun",
            facts_context="aucun",
            conversation_mode="",
            config=config,
            should_use_remote_memory=False,
            get_specialized_local_context_fn=lambda *args, **kwargs: ({"viewer_context": "aucun", "global_context": "aucun", "items": []}, []),
            get_context_with_fallback_fn=lambda **kwargs: (
                {"viewer_context": "alice: salut", "global_context": "discussion recente", "items": []},
                "local",
                [],
            ),
            build_web_search_decision_fn=lambda *_args, **_kwargs: DecisionResult(
                decision="skip_reply",
                rule_id="no_web",
                reason="no_web",
                needs_web=False,
            ),
            build_web_search_context_fn=lambda *_args, **_kwargs: "aucun",
            search_searxng_fn=lambda **_kwargs: [],
        )

        self.assertEqual(bundle.viewer_context, "alice: salut")
        self.assertIn("discussion recente", bundle.global_context)
        self.assertIn("Contexte viewer:", bundle.global_context)
        self.assertTrue(any(source.source_id == "homegraph_local" for source in bundle.sources))

    async def test_dispatch_incoming_message_processes_immediately_without_queue_worker(self):
        payload = SimpleNamespace(
            text="@AnneAuNimouss salut",
            chatter=SimpleNamespace(name="alice"),
            broadcaster=SimpleNamespace(name="streamer"),
            id="msg-1",
        )
        process_queued_message = AsyncMock()
        enqueue_message = AsyncMock()

        await dispatch_incoming_message(
            payload=payload,
            recent_ids=deque(maxlen=10),
            queue_worker_task=None,
            enqueue_message_fn=enqueue_message,
            process_queued_message_fn=process_queued_message,
            queued_message_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            now_fn=lambda: 42.0,
            injection_checker=lambda _text: False,
        )

        process_queued_message.assert_awaited_once()
        enqueue_message.assert_not_awaited()
        queued = process_queued_message.await_args.args[0]
        self.assertEqual(queued.author, "alice")
        self.assertEqual(queued.clean_viewer_message, "salut")
        self.assertEqual(queued.received_at, 42.0)

    async def test_dispatch_incoming_message_enqueues_when_queue_worker_exists(self):
        payload = SimpleNamespace(
            text="@AnneAuNimouss salut",
            chatter=SimpleNamespace(name="alice"),
            broadcaster=SimpleNamespace(name="streamer"),
            id="msg-2",
        )
        process_queued_message = AsyncMock()
        enqueue_message = AsyncMock()

        await dispatch_incoming_message(
            payload=payload,
            recent_ids=deque(maxlen=10),
            queue_worker_task=object(),
            enqueue_message_fn=enqueue_message,
            process_queued_message_fn=process_queued_message,
            queued_message_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            now_fn=lambda: 77.0,
            injection_checker=lambda _text: False,
        )

        enqueue_message.assert_awaited_once()
        process_queued_message.assert_not_awaited()
        queued = enqueue_message.await_args.args[0]
        self.assertEqual(queued.msg_id, "msg-2")
        self.assertEqual(queued.received_at, 77.0)

    async def test_handle_non_model_decision_store_only_persists_without_model_reply(self):
        payload = SimpleNamespace(broadcaster=SimpleNamespace())
        decision = DecisionResult(
            decision="store_only",
            rule_id="riddle_partial_no_reply",
            reason="partial_riddle",
        )
        persist_local_turn = Mock()
        remember_remote_turn = Mock(return_value=False)
        send_chat_reply = AsyncMock()
        reply_about_channel_content = AsyncMock()
        mark_replied = Mock()

        handled = await handle_non_model_decision(
            payload=payload,
            author="alice",
            channel_name="streamer",
            msg_id="msg-3",
            decision=decision,
            clean_viewer_message="Mon second est absent",
            event_type="riddle",
            related_viewer="",
            related_message="",
            reply_to_turn_id="",
            related_turn_id="",
            riddle_thread_reset=True,
            riddle_thread_close=False,
            author_is_owner=False,
            reply_about_channel_content_fn=reply_about_channel_content,
            send_chat_reply_fn=send_chat_reply,
            persist_local_turn_fn=persist_local_turn,
            persist_local_and_remote_turn_fn=Mock(),
            remember_remote_turn_fn=remember_remote_turn,
            mark_replied_fn=mark_replied,
        )

        self.assertTrue(handled)
        persist_local_turn.assert_called_once()
        remember_remote_turn.assert_called_once_with(
            "streamer",
            "alice",
            "Mon second est absent",
            message_id="msg-3",
            allow_remote=False,
            author_is_owner=False,
        )
        send_chat_reply.assert_not_awaited()
        reply_about_channel_content.assert_not_awaited()
        mark_replied.assert_not_called()

    async def test_handle_non_model_decision_social_reply_sends_and_marks(self):
        broadcaster = SimpleNamespace()
        payload = SimpleNamespace(broadcaster=broadcaster)
        decision = DecisionResult(
            decision="social_reply",
            rule_id="social_greeting_or_closing",
            reason="social_intent",
            meta={"reply": "Bonjour !"},
        )
        send_chat_reply = AsyncMock()
        persist_local_turn = Mock()
        mark_replied = Mock()

        handled = await handle_non_model_decision(
            payload=payload,
            author="alice",
            channel_name="streamer",
            msg_id="msg-4",
            decision=decision,
            clean_viewer_message="bonjour",
            event_type="chat_message",
            related_viewer="",
            related_message="",
            reply_to_turn_id="",
            related_turn_id="",
            riddle_thread_reset=False,
            riddle_thread_close=False,
            author_is_owner=False,
            reply_about_channel_content_fn=AsyncMock(),
            send_chat_reply_fn=send_chat_reply,
            persist_local_turn_fn=persist_local_turn,
            persist_local_and_remote_turn_fn=Mock(),
            remember_remote_turn_fn=Mock(return_value=False),
            mark_replied_fn=mark_replied,
        )

        self.assertTrue(handled)
        send_chat_reply.assert_awaited_once_with(
            broadcaster,
            "alice",
            "Bonjour !",
            log_prefix="📤 Réponse sociale",
        )
        persist_local_turn.assert_called_once()
        mark_replied.assert_called_once_with("alice")

    async def test_message_queue_worker_skips_expired_message_then_processes_next_one(self):
        queue: asyncio.Queue = asyncio.Queue()
        processed = []
        timestamps = iter([20.0, 11.0])

        await queue.put(SimpleNamespace(author="alice", received_at=0.0))
        await queue.put(SimpleNamespace(author="bob", received_at=10.0))

        async def process_queued_message(message):
            processed.append(message.author)
            worker.cancel()

        worker = asyncio.create_task(
            message_queue_worker(
                message_queue=queue,
                process_queued_message_fn=process_queued_message,
                seconds_until_ready_fn=lambda _author: 0.0,
                now_fn=lambda: next(timestamps),
                max_age_seconds=5.0,
            )
        )

        with self.assertRaises(asyncio.CancelledError):
            await worker

        self.assertEqual(processed, ["bob"])
        self.assertEqual(queue.qsize(), 0)


if __name__ == "__main__":
    unittest.main()
