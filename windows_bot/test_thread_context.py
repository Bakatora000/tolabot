import unittest

from arbitrator import build_normalized_event
from thread_context import build_thread_context


class ThreadContextTests(unittest.TestCase):
    def test_build_thread_context_summarizes_recent_thread(self):
        chat_memory = {
            "channels": {
                "streamer": {
                    "global_turns": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "channel": "streamer",
                            "viewer": "alice",
                            "viewer_message": "on parlait de valheim no death",
                            "bot_reply": "oui, c'est tendu",
                        },
                        {
                            "timestamp": "2026-03-25T12:01:00+00:00",
                            "channel": "streamer",
                            "viewer": "bob",
                            "viewer_message": "ca depend du biome",
                            "bot_reply": "",
                        },
                    ],
                    "viewer_turns": {},
                }
            }
        }
        conversation_graph = {
            "channels": {
                "streamer": {
                    "turns": [
                        {
                            "turn_id": "t1",
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "speaker": "alice",
                            "message_text": "on parlait de valheim no death",
                            "bot_reply": "oui, c'est tendu",
                            "event_type": "message",
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "",
                            "target_viewers": [],
                        },
                        {
                            "turn_id": "t2",
                            "timestamp": "2026-03-25T12:01:00+00:00",
                            "speaker": "bob",
                            "message_text": "ca depend du biome",
                            "bot_reply": "",
                            "event_type": "message",
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "",
                            "target_viewers": [],
                        },
                    ]
                }
            }
        }

        event = build_normalized_event(
            event_id="m1",
            channel="streamer",
            author="alice",
            timestamp="2026-03-25T12:02:00+00:00",
            text="et du coup pour le no death ?",
        )

        result = build_thread_context(chat_memory, conversation_graph, "streamer", event)

        self.assertIsNotNone(result)
        self.assertEqual(result.source_id, "thread_context")
        self.assertEqual(result.meta["participants"], ["alice", "bob"])
        self.assertEqual(result.meta["turn_count"], 2)
        self.assertIn("sujet recent probable: death, parlait, valheim", result.text_block)
        self.assertIn("derniere question pertinente: alice: et du coup pour le no death ?", result.text_block)
        self.assertIn("tours recents:\nalice: on parlait de valheim no death\nbob: ca depend du biome", result.text_block)

    def test_build_thread_context_includes_recent_correction(self):
        chat_memory = {"channels": {"streamer": {"global_turns": [], "viewer_turns": {}}}}
        conversation_graph = {
            "channels": {
                "streamer": {
                    "turns": [
                        {
                            "turn_id": "t1",
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "speaker": "streamer",
                            "message_text": "je parlais de misscouette, pas de gaby",
                            "bot_reply": "",
                            "event_type": "owner_correction",
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "t0",
                            "target_viewers": ["alice"],
                        }
                    ]
                }
            }
        }

        event = build_normalized_event(
            event_id="m2",
            channel="streamer",
            author="alice",
            timestamp="2026-03-25T12:02:00+00:00",
            text="du coup tu penses quoi d'elle ?",
        )

        result = build_thread_context(chat_memory, conversation_graph, "streamer", event)

        self.assertIsNotNone(result)
        self.assertIn(
            "correction ou desaccord recent: streamer: je parlais de misscouette, pas de gaby",
            result.text_block,
        )


if __name__ == "__main__":
    unittest.main()
