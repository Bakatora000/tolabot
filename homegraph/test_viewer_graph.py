from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from homegraph.graph import build_viewer_graph_payload
from homegraph.merge_extraction import merge_payload


class ViewerGraphTests(unittest.TestCase):
    def test_sparse_viewer_without_profile_returns_singleton_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "homegraph.sqlite3"
            payload = {
                "viewer_id": "twitch:expevay:viewer:expevay",
                "channel": "expevay",
                "viewer_login": "expevay",
                "display_name": "Expevay",
                "summary_short": "Viewer centre autour de Valheim.",
                "summary_long": "Viewer centre autour de Valheim.",
                "facts": [],
                "relations": [],
                "links": [
                    {
                        "target_type": "viewer",
                        "target_value": "Dame_Gaby",
                        "relation_type": "knows",
                        "strength": 0.61,
                        "confidence": 0.58,
                        "status": "uncertain",
                        "polarity": "neutral",
                        "source_memory_ids": ["m1"],
                    }
                ],
            }
            merge_payload(payload, db_path=db_path, source_ref="test", model_name="test")

            result = build_viewer_graph_payload("twitch:expevay:viewer:dame_gaby", db_path)

            self.assertTrue(result["ok"])
            self.assertEqual(result["viewer_id"], "twitch:expevay:viewer:dame_gaby")
            self.assertEqual(result["stats"]["node_count"], 1)
            self.assertEqual(result["stats"]["link_count"], 0)
            self.assertEqual(result["nodes"][0]["id"], "viewer:twitch:expevay:viewer:dame_gaby")
            self.assertEqual(result["nodes"][0]["label"], "dame_gaby")
            self.assertEqual(result["links"], [])


if __name__ == "__main__":
    unittest.main()
