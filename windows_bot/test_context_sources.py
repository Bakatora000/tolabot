import unittest

from context_sources import build_auxiliary_context_sources, build_context_source_results, merge_context_text


class ContextSourcesTests(unittest.TestCase):
    def test_merge_context_text_deduplicates_and_ignores_aucun(self):
        merged = merge_context_text("aucun", "alpha", "beta", "alpha", "")

        self.assertEqual(merged, "alpha\nbeta")

    def test_build_auxiliary_context_sources_only_returns_available_blocks(self):
        sources = build_auxiliary_context_sources(
            alias_context="alias local: caouette = MissCouette76",
            focus_context="aucun",
            facts_context="fait incertain rapporte par dame_gaby sur toi: aussi appelée MissCouette.",
        )

        self.assertEqual([source.source_id for source in sources], ["alias_resolution", "facts_memory"])

    def test_build_context_source_results_includes_thread_context(self):
        sources = build_context_source_results(
            viewer_context="alice: salut",
            conversation_context="bob: valheim",
            thread_context="participants: alice, bob",
        )

        self.assertEqual(
            [source.source_id for source in sources],
            ["local_viewer_thread", "conversation_graph", "thread_context"],
        )


if __name__ == "__main__":
    unittest.main()
