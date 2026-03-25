import unittest

from arbitrator import arbitrate_chat_message, build_normalized_event


class ArbitratorTests(unittest.TestCase):
    def make_event(self, text: str, author: str = "alice", channel: str = "streamer"):
        return build_normalized_event(
            event_id="evt-1",
            channel=channel,
            author=author,
            timestamp="2026-03-25T18:00:00Z",
            text=text,
        )

    def test_arbitrator_returns_social_reply_for_greeting(self):
        decision = arbitrate_chat_message(
            event=self.make_event("@AnneAuNimouss bonjour"),
            clean_viewer_message="bonjour",
            author_is_owner=False,
            riddle_related=False,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            asks_channel_content=False,
            repeated_social_count=0,
        )

        self.assertEqual(decision.decision, "social_reply")
        self.assertEqual(decision.rule_id, "social_greeting_or_closing")
        self.assertEqual(decision.meta["reply"], "Bonjour !")

    def test_arbitrator_refuses_non_owner_memory_instruction(self):
        decision = arbitrate_chat_message(
            event=self.make_event("@AnneAuNimouss note que je joue a wow"),
            clean_viewer_message="note que je joue a wow",
            author_is_owner=False,
            riddle_related=False,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            asks_channel_content=False,
        )

        self.assertEqual(decision.decision, "refuse_memory_instruction")
        self.assertEqual(decision.rule_id, "memory_instruction_non_owner")

    def test_arbitrator_routes_partial_riddle_to_store_only(self):
        decision = arbitrate_chat_message(
            event=self.make_event('@AnneAuNimouss "Mon second est absent"'),
            clean_viewer_message='"Mon second est absent"',
            author_is_owner=True,
            riddle_related=True,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            asks_channel_content=False,
        )

        self.assertEqual(decision.decision, "store_only")
        self.assertEqual(decision.rule_id, "riddle_partial_no_reply")

    def test_arbitrator_routes_regular_message_to_model_reply(self):
        decision = arbitrate_chat_message(
            event=self.make_event("@AnneAuNimouss que penses tu de Valheim ?"),
            clean_viewer_message="que penses tu de Valheim ?",
            author_is_owner=False,
            riddle_related=False,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            asks_channel_content=False,
        )

        self.assertEqual(decision.decision, "model_reply")
        self.assertTrue(decision.needs_short_memory)

    def test_arbitrator_detects_reaction_followup_as_local_context_reply(self):
        decision = arbitrate_chat_message(
            event=self.make_event("@AnneAuNimouss il fait deja froid des ce soir??"),
            clean_viewer_message="il fait deja froid des ce soir??",
            author_is_owner=False,
            riddle_related=False,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            asks_channel_content=False,
        )

        self.assertEqual(decision.decision, "model_reply")
        self.assertEqual(decision.rule_id, "reaction_followup_local")
        self.assertFalse(decision.needs_long_memory)
        self.assertTrue(decision.meta["prefer_active_thread"])


if __name__ == "__main__":
    unittest.main()
