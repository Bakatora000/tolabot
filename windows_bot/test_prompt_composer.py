import unittest

from context_sources import build_context_source_results
from prompt_composer import build_messages_from_prompt_plan, build_prompt_plan


class PromptComposerTests(unittest.TestCase):
    def test_build_prompt_plan_tracks_sources_and_blocks(self):
        sources = build_context_source_results(
            viewer_context="alice: salut",
            conversation_context="bot: bonjour",
            web_context="[1] Meteo Lyon - Temps nuageux.",
            context_label="local+mem0",
        )

        plan = build_prompt_plan(sources, conversation_mode="")

        self.assertEqual(plan.viewer_block, "alice: salut")
        self.assertEqual(plan.conversation_block, "bot: bonjour")
        self.assertEqual(plan.web_block, "[1] Meteo Lyon - Temps nuageux.")
        self.assertEqual(plan.source_trace, ["viewer_context", "conversation_context", "web_context"])

    def test_build_messages_from_prompt_plan_preserves_web_context_tags(self):
        sources = build_context_source_results(
            viewer_context="alice: salut",
            conversation_context="bot: bonjour",
            web_context="[1] Meteo Lyon - Temps nuageux.",
        )
        plan = build_prompt_plan(sources, conversation_mode="")

        messages = build_messages_from_prompt_plan(plan, user_name="alice", clean_message="quel temps fait-il ?")

        self.assertIn("web_context recent", messages[0]["content"].lower())
        self.assertIn("<web_context>[1] Meteo Lyon - Temps nuageux.</web_context>", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
