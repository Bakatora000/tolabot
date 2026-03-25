import tempfile
import unittest
from pathlib import Path

from conversation_graph import (
    append_conversation_turn,
    build_conversation_graph_context,
    find_related_conversation_turn,
    find_reply_target_turn,
    load_conversation_graph,
    select_relevant_conversation_turns,
)


class ConversationGraphTests(unittest.TestCase):
    def test_append_and_load_conversation_graph_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            turn_id = append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de @Dame_Gaby ?",
                "Gaby est une présentatrice TV.",
                graph_file=graph_file,
            )

            loaded = load_conversation_graph(graph_file)
            self.assertTrue(turn_id)
            self.assertEqual(loaded["channels"]["streamer"]["turns"][0]["turn_id"], turn_id)

    def test_find_related_conversation_turn_matches_previous_viewer_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de @Dame_Gaby ?",
                "Gaby est une présentatrice TV.",
                graph_file=graph_file,
            )
            related = find_related_conversation_turn(
                graph,
                channel_name="streamer",
                author_name="streamer",
                message_text="@anneaunimouss je pense qu'il parlait de Dame_Gaby et pas Gaby",
            )

            self.assertIsNotNone(related)
            self.assertEqual(related["speaker"], "viewer1")

    def test_build_conversation_graph_context_formats_corrections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            original_turn_id = append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de @Dame_Gaby ?",
                "Gaby est une présentatrice TV.",
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "streamer",
                "je pense qu'il parlait de Dame_Gaby et pas Gaby",
                "Bien vu, il parlait sans doute de Dame_Gaby.",
                event_type="owner_correction",
                corrects_turn_id=original_turn_id,
                target_viewers=["viewer1"],
                graph_file=graph_file,
            )

            context = build_conversation_graph_context(graph, "streamer", "alice")

            self.assertIn("viewer1: que penses tu de @Dame_Gaby ?", context)
            self.assertIn("correction vers viewer1: je pense qu'il parlait de Dame_Gaby et pas Gaby", context)

    def test_find_reply_target_turn_returns_latest_turn_of_same_speaker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            append_conversation_turn(graph, "streamer", "alice", "premier message", "reponse 1", graph_file=graph_file)
            last_turn_id = append_conversation_turn(graph, "streamer", "alice", "deuxieme message", "reponse 2", graph_file=graph_file)

            related = find_reply_target_turn(graph, "streamer", "alice")

            self.assertIsNotNone(related)
            self.assertEqual(related["turn_id"], last_turn_id)

    def test_build_conversation_graph_context_formats_reply_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            original_turn_id = append_conversation_turn(
                graph,
                "streamer",
                "alice",
                "tu te souviens de notre discussion ?",
                "oui, on parlait de valheim",
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "alice",
                "et pour le boss final ?",
                "il faut mieux se preparer",
                reply_to_turn_id=original_turn_id,
                graph_file=graph_file,
            )

            context = build_conversation_graph_context(graph, "streamer", "bob")

            self.assertIn("suite de alice: et pour le boss final ?", context)

    def test_select_relevant_conversation_turns_prefers_connected_subgraph(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            original_turn_id = append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de @Dame_Gaby ?",
                "Gaby est une présentatrice TV.",
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "streamer",
                "je pense qu'il parlait de Dame_Gaby et pas Gaby",
                "Bien vu, il parlait sans doute de Dame_Gaby.",
                event_type="owner_correction",
                corrects_turn_id=original_turn_id,
                target_viewers=["viewer1"],
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "bob",
                "hors sujet complet",
                "réponse hors sujet",
                graph_file=graph_file,
            )

            selected_turns = select_relevant_conversation_turns(
                graph,
                channel_name="streamer",
                viewer_name="streamer",
                current_message="@anneaunimouss je pense qu'il parlait de Dame_Gaby et pas Gaby",
            )

            selected_messages = {turn["message_text"] for turn in selected_turns}
            self.assertIn("que penses tu de @Dame_Gaby ?", selected_messages)
            self.assertIn("je pense qu'il parlait de Dame_Gaby et pas Gaby", selected_messages)
            self.assertNotIn("hors sujet complet", selected_messages)

    def test_build_conversation_graph_context_uses_current_message_to_focus_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            original_turn_id = append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de @Dame_Gaby ?",
                "Gaby est une présentatrice TV.",
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "streamer",
                "je pense qu'il parlait de Dame_Gaby et pas Gaby",
                "Bien vu, il parlait sans doute de Dame_Gaby.",
                event_type="owner_correction",
                corrects_turn_id=original_turn_id,
                target_viewers=["viewer1"],
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "bob",
                "hors sujet complet",
                "réponse hors sujet",
                graph_file=graph_file,
            )

            context = build_conversation_graph_context(
                graph,
                "streamer",
                "streamer",
                current_message="@anneaunimouss je pense qu'il parlait de Dame_Gaby et pas Gaby",
            )

            self.assertIn("viewer1: que penses tu de @Dame_Gaby ?", context)
            self.assertIn("correction vers viewer1: je pense qu'il parlait de Dame_Gaby et pas Gaby", context)
            self.assertNotIn("hors sujet complet", context)

    def test_select_relevant_conversation_turns_keeps_strong_seed_without_recent_noise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_file = str(Path(tmpdir) / "conversation_graph.json")
            graph = {"channels": {}}

            original_turn_id = append_conversation_turn(
                graph,
                "streamer",
                "viewer1",
                "que penses tu de MissCouette ?",
                "Elle joue à Enshrouded.",
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "streamer",
                "je parlais effectivement de MissCouette. MrAdel779 est hors sujet",
                "Tu as raison, on reste sur MissCouette.",
                event_type="owner_correction",
                corrects_turn_id=original_turn_id,
                target_viewers=["viewer1"],
                graph_file=graph_file,
            )
            append_conversation_turn(
                graph,
                "streamer",
                "bob",
                "hors sujet",
                "réponse hors sujet",
                graph_file=graph_file,
            )

            context = build_conversation_graph_context(
                graph,
                "streamer",
                "streamer",
                current_message="@anneaunimouss du coup que penses tu d'elle ?",
            )

            self.assertIn("MissCouette", context)
            self.assertNotIn("réponse hors sujet", context)


if __name__ == "__main__":
    unittest.main()
