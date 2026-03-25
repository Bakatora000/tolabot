import unittest

from runtime_types import ContextSourceResult, DecisionResult, NormalizedEvent, PromptPlan


class RuntimeTypesTests(unittest.TestCase):
    def test_decision_result_exposes_enabled_compatibility(self):
        decision = DecisionResult(
            decision="web_search",
            rule_id="weather_followup",
            reason="context_followup",
            needs_web=True,
            query="meteo demain a lyon",
        )

        self.assertTrue(decision["enabled"])
        self.assertEqual(decision["rule_id"], "weather_followup")
        self.assertEqual(decision.to_dict()["enabled"], True)

    def test_runtime_dataclasses_capture_target_contract(self):
        event = NormalizedEvent(
            event_id="evt_1",
            type="chat_message",
            channel="expevay",
            author="alice",
            timestamp="2026-03-25T18:00:00Z",
            text="@anneaunimouss salut",
        )
        source = ContextSourceResult(
            source_id="mem0",
            available=True,
            priority=80,
            confidence=0.74,
            stale=False,
            text_block="Contexte viewer: ...",
        )
        prompt = PromptPlan(
            system_block="system",
            viewer_block="viewer",
            conversation_block="conversation",
            web_block="web",
            style_block="style",
            source_trace=["local", "mem0"],
        )

        self.assertEqual(event.type, "chat_message")
        self.assertEqual(source.source_id, "mem0")
        self.assertEqual(prompt.source_trace, ["local", "mem0"])


if __name__ == "__main__":
    unittest.main()
