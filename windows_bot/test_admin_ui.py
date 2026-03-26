import unittest

from admin_ui import (
    build_conversation_graph_payload,
    build_facts_graph_payload,
    build_homegraph_payload,
)


class AdminUiGraphTests(unittest.TestCase):
    def test_build_conversation_graph_payload_links_turns_and_viewers(self):
        graph = {
            "channels": {
                "streamer": {
                    "turns": [
                        {
                            "turn_id": "t1",
                            "timestamp": "2026-03-26T10:00:00+00:00",
                            "speaker": "alice",
                            "message_text": "salut bob",
                            "bot_reply": "bonjour",
                            "event_type": "message",
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "",
                            "target_viewers": ["bob"],
                        },
                        {
                            "turn_id": "t2",
                            "timestamp": "2026-03-26T10:01:00+00:00",
                            "speaker": "bob",
                            "message_text": "je réponds",
                            "bot_reply": "",
                            "event_type": "message",
                            "reply_to_turn_id": "t1",
                            "corrects_turn_id": "",
                            "target_viewers": [],
                        },
                    ]
                }
            }
        }

        payload = build_conversation_graph_payload(graph, viewer_filter="alice")

        node_ids = {node["id"] for node in payload["nodes"]}
        link_kinds = {link["kind"] for link in payload["links"]}
        self.assertIn("viewer:alice", node_ids)
        self.assertIn("turn:t1", node_ids)
        self.assertIn("turn:t2", node_ids)
        self.assertIn("authored", link_kinds)
        self.assertIn("targets", link_kinds)
        self.assertIn("reply_to", link_kinds)

    def test_build_facts_graph_payload_creates_fact_nodes(self):
        facts_memory = {
            "channels": {
                "streamer": {
                    "facts": [
                        {
                            "timestamp": "2026-03-26T10:00:00+00:00",
                            "subject": "MissCouette76",
                            "predicate": "alias",
                            "value": "aussi appelée MissCouette",
                            "source_speaker": "dame_gaby",
                            "verification_state": "third_party_reported",
                        }
                    ]
                }
            }
        }

        payload = build_facts_graph_payload(facts_memory, viewer_filter="misscouette76")

        self.assertEqual(payload["kind"], "facts")
        self.assertEqual(payload["stats"]["fact_count"], 1)
        self.assertTrue(any(node["kind"] == "fact" for node in payload["nodes"]))
        self.assertTrue(any(link["kind"] == "about" for link in payload["links"]))

    def test_build_homegraph_payload_preserves_contract_and_applies_colors(self):
        raw_payload = {
            "nodes": [
                {"id": "viewer:alice", "kind": "viewer", "label": "alice"},
                {"id": "game:valheim", "kind": "game", "label": "Valheim"},
            ],
            "links": [
                {"source": "viewer:alice", "target": "game:valheim", "kind": "plays"},
            ],
            "stats": {"node_count": 2, "link_count": 1},
            "meta": {"version": "v1", "center_node_id": "game:valheim", "truncated": True},
        }

        payload = build_homegraph_payload(raw_payload, viewer_filter="alice")

        self.assertEqual(payload["kind"], "homegraph")
        self.assertEqual(payload["meta"]["version"], "v1")
        self.assertEqual(payload["meta"]["center_node_id"], "game:valheim")
        self.assertTrue(payload["meta"]["truncated"])
        self.assertEqual(payload["stats"]["node_count"], 2)
        self.assertTrue(any(node["color"] for node in payload["nodes"]))
        self.assertEqual(payload["links"][0]["label"], "plays")


if __name__ == "__main__":
    unittest.main()
