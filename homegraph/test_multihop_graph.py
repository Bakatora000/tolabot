from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from homegraph.merge_extraction import merge_payload
from homegraph.multihop_graph import build_multihop_graph_payload


def _base_payload(viewer_id: str, display_name: str, summary: str) -> dict:
    channel = viewer_id.split(":")[1]
    viewer_login = viewer_id.split(":")[-1]
    return {
        "viewer_id": viewer_id,
        "channel": channel,
        "viewer_login": viewer_login,
        "display_name": display_name,
        "summary_short": summary,
        "summary_long": summary,
        "facts": [],
        "relations": [],
        "links": [],
    }


class MultiHopGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "homegraph.sqlite3"

        expevay = _base_payload(
            "twitch:expevay:viewer:expevay",
            "Expevay",
            "Viewer centre autour de Valheim.",
        )
        expevay["links"] = [
            {
                "target_type": "game",
                "target_value": "Valheim",
                "relation_type": "plays",
                "strength": 0.95,
                "confidence": 0.93,
                "status": "active",
                "polarity": "positive",
                "source_memory_ids": ["m1"],
            },
            {
                "target_type": "stream_mode",
                "target_value": "no death",
                "relation_type": "likes",
                "strength": 0.84,
                "confidence": 0.80,
                "status": "active",
                "polarity": "positive",
                "source_memory_ids": ["m2"],
            },
            {
                "target_type": "object",
                "target_value": "long bow",
                "relation_type": "owns",
                "strength": 0.73,
                "confidence": 0.78,
                "status": "active",
                "polarity": "neutral",
                "source_memory_ids": ["m3"],
            },
            {
                "target_type": "viewer",
                "target_value": "MissCouette76",
                "relation_type": "knows",
                "strength": 0.64,
                "confidence": 0.62,
                "status": "uncertain",
                "polarity": "neutral",
                "source_memory_ids": ["m4"],
            },
            {
                "target_type": "viewer",
                "target_value": "K7VHS",
                "relation_type": "knows",
                "strength": 0.68,
                "confidence": 0.70,
                "status": "active",
                "polarity": "neutral",
                "source_memory_ids": ["m5"],
            },
            {
                "target_type": "topic",
                "target_value": "K7VHS",
                "relation_type": "returns_to",
                "strength": 0.72,
                "confidence": 0.76,
                "status": "active",
                "polarity": "neutral",
                "source_memory_ids": ["m6"],
            },
            {
                "target_type": "running_gag",
                "target_value": "K7VHS",
                "relation_type": "returns_to",
                "strength": 0.70,
                "confidence": 0.74,
                "status": "active",
                "polarity": "neutral",
                "source_memory_ids": ["m7"],
            },
        ]

        arthii = _base_payload(
            "twitch:expevay:viewer:arthii_tv",
            "Arthii_TV",
            "Viewer relie a Valheim et aux runs difficiles.",
        )
        arthii["links"] = [
            {
                "target_type": "game",
                "target_value": "Valheim",
                "relation_type": "plays",
                "strength": 0.90,
                "confidence": 0.88,
                "status": "active",
                "polarity": "positive",
                "source_memory_ids": ["a1"],
            },
            {
                "target_type": "stream_mode",
                "target_value": "hardcore",
                "relation_type": "likes",
                "strength": 0.77,
                "confidence": 0.75,
                "status": "active",
                "polarity": "positive",
                "source_memory_ids": ["a2"],
            },
        ]

        karramelle = _base_payload(
            "twitch:expevay:viewer:karramelle",
            "Karramelle",
            "Viewer qui passe aussi par Valheim.",
        )
        karramelle["links"] = [
            {
                "target_type": "game",
                "target_value": "Valheim",
                "relation_type": "plays",
                "strength": 0.88,
                "confidence": 0.86,
                "status": "active",
                "polarity": "positive",
                "source_memory_ids": ["k1"],
            },
            {
                "target_type": "game",
                "target_value": "Enshrouded",
                "relation_type": "dislikes",
                "strength": 0.76,
                "confidence": 0.74,
                "status": "active",
                "polarity": "negative",
                "source_memory_ids": ["k2"],
            },
        ]

        for payload in (expevay, arthii, karramelle):
            merge_payload(payload, db_path=self.db_path, source_ref="test", model_name="test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_depth_1_from_game_returns_connected_viewers_only(self) -> None:
        payload = build_multihop_graph_payload("game:valheim", self.db_path, max_depth=1)
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertIn("game:valheim", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:expevay", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:arthii_tv", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:karramelle", node_ids)
        self.assertNotIn("stream_mode:no_death", node_ids)

    def test_depth_2_from_game_expands_other_targets(self) -> None:
        payload = build_multihop_graph_payload("game:valheim", self.db_path, max_depth=2)
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertIn("stream_mode:no_death", node_ids)
        self.assertIn("stream_mode:hardcore", node_ids)
        self.assertIn("object:long_bow", node_ids)

    def test_entity_focus_from_game_keeps_star_and_useful_secondary_context(self) -> None:
        payload = build_multihop_graph_payload(
            "game:valheim",
            self.db_path,
            mode="entity_focus",
            max_depth=2,
        )
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertIn("game:valheim", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:expevay", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:arthii_tv", node_ids)
        self.assertIn("viewer:twitch:expevay:viewer:karramelle", node_ids)
        self.assertIn("stream_mode:no_death", node_ids)
        self.assertIn("stream_mode:hardcore", node_ids)
        self.assertNotIn("object:long_bow", node_ids)
        self.assertNotIn("game:enshrouded", node_ids)
        self.assertNotIn("running_gag:k7vhs", node_ids)
        self.assertEqual(payload["meta"]["filters_applied"]["mode"], "entity_focus")
        self.assertEqual(payload["source"], "homegraph_entity_focus_graph_v1")

    def test_include_uncertain_false_drops_uncertain_links(self) -> None:
        payload = build_multihop_graph_payload(
            "viewer:twitch:expevay:viewer:expevay",
            self.db_path,
            max_depth=2,
            include_uncertain=False,
        )
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertNotIn("viewer:misscouette76", node_ids)

    def test_min_weight_filters_weaker_links(self) -> None:
        payload = build_multihop_graph_payload(
            "viewer:twitch:expevay:viewer:expevay",
            self.db_path,
            max_depth=2,
            min_weight=0.8,
        )
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertIn("game:valheim", node_ids)
        self.assertIn("stream_mode:no_death", node_ids)
        self.assertNotIn("object:long_bow", node_ids)

    def test_max_links_truncates_graph(self) -> None:
        payload = build_multihop_graph_payload(
            "game:valheim",
            self.db_path,
            max_depth=2,
            max_links=2,
        )
        self.assertEqual(payload["stats"]["link_count"], 2)
        self.assertTrue(payload["meta"]["truncated"])

    def test_center_non_viewer_node_is_supported(self) -> None:
        payload = build_multihop_graph_payload("game:valheim", self.db_path, max_depth=1)
        self.assertIsNone(payload["viewer_id"])
        self.assertEqual(payload["meta"]["center_node_id"], "game:valheim")
        self.assertEqual(payload["meta"]["root_node_id"], "game:valheim")
        self.assertFalse(payload["meta"]["filtered_by_viewer"])

    def test_topic_center_projects_to_matching_viewer_entity(self) -> None:
        payload = build_multihop_graph_payload("topic:k7vhs", self.db_path, max_depth=2)
        node_ids = {node["id"] for node in payload["nodes"]}
        link_kinds = {(link["source"], link["kind"], link["target"]) for link in payload["links"]}

        self.assertIn("topic:k7vhs", node_ids)
        self.assertIn("viewer:k7vhs", node_ids)
        self.assertIn(("topic:k7vhs", "about_viewer", "viewer:k7vhs"), link_kinds)

    def test_running_gag_center_projects_to_matching_viewer_entity(self) -> None:
        payload = build_multihop_graph_payload("running_gag:k7vhs", self.db_path, max_depth=2)
        node_ids = {node["id"] for node in payload["nodes"]}
        link_kinds = {(link["source"], link["kind"], link["target"]) for link in payload["links"]}

        self.assertIn("running_gag:k7vhs", node_ids)
        self.assertIn("viewer:k7vhs", node_ids)
        self.assertIn(("running_gag:k7vhs", "centers_on_viewer", "viewer:k7vhs"), link_kinds)

    def test_unknown_center_returns_empty_graph(self) -> None:
        payload = build_multihop_graph_payload("game:unknown_game", self.db_path, max_depth=2)
        self.assertEqual(payload["stats"]["node_count"], 0)
        self.assertEqual(payload["stats"]["link_count"], 0)
        self.assertEqual(payload["nodes"], [])
        self.assertEqual(payload["links"], [])

    def test_filtered_center_node_is_preserved_as_singleton(self) -> None:
        payload = build_multihop_graph_payload(
            "viewer:misscouette76",
            self.db_path,
            max_depth=2,
            include_uncertain=False,
            min_weight=0.7,
        )
        self.assertEqual(payload["stats"]["node_count"], 1)
        self.assertEqual(payload["stats"]["link_count"], 0)
        self.assertEqual(payload["nodes"][0]["id"], "viewer:misscouette76")


if __name__ == "__main__":
    unittest.main()
