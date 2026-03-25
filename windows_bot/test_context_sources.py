import unittest

from context_sources import build_auxiliary_context_sources, merge_context_text


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


if __name__ == "__main__":
    unittest.main()
