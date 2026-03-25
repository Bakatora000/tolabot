import unittest

from context_sources import make_context_source_result
from runtime_types import ContextSourceResult, DecisionResult, NormalizedEvent, PromptPlan, RuntimeContextBundle


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
        runtime_context = RuntimeContextBundle(
            viewer_context="viewer",
            global_context="conversation",
            web_context="web",
            context_source="local",
            sources=[source],
            conversation_mode="",
        )

        self.assertEqual(event.type, "chat_message")
        self.assertEqual(source.source_id, "mem0")
        self.assertEqual(prompt.source_trace, ["local", "mem0"])
        self.assertEqual(runtime_context.context_source, "local")

    def test_make_context_source_result_skips_empty_blocks(self):
        self.assertIsNone(
            make_context_source_result(
                "mem0",
                "aucun",
                priority=80,
                confidence=0.7,
            )
        )


if __name__ == "__main__":
    unittest.main()
