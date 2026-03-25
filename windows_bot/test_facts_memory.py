import tempfile
import unittest
from pathlib import Path

from facts_memory import (
    append_reported_facts,
    build_facts_context,
    extract_reported_facts,
    load_facts_memory,
)


class FactsMemoryTests(unittest.TestCase):
    def test_extract_reported_facts_marks_third_party_statement_as_uncertain(self):
        facts = extract_reported_facts(
            "MissCouette76 est aussi MissCouette pour information",
            source_speaker="dame_gaby",
        )

        self.assertTrue(facts)
        self.assertEqual(facts[0]["subject"], "MissCouette76")
        self.assertEqual(facts[0]["verification_state"], "third_party_reported")

    def test_extract_reported_facts_marks_self_statement_as_confirmed(self):
        facts = extract_reported_facts(
            "MissCouette76 est aussi MissCouette pour information",
            source_speaker="MissCouette76",
        )

        self.assertTrue(facts)
        self.assertEqual(facts[0]["verification_state"], "self_confirmed")

    def test_extract_reported_alias_phrase(self):
        facts = extract_reported_facts(
            'quand on te parle de "dame gaby" il s\'agit de Dame_Gaby',
            source_speaker="expevay",
        )

        alias_fact = next(fact for fact in facts if fact["predicate"] == "alias")
        self.assertEqual(alias_fact["subject"], "Dame_Gaby")
        self.assertIn("dame gaby", alias_fact["value"].lower())

    def test_extract_reported_facts_ignores_questions(self):
        facts = extract_reported_facts(
            "quelle est la météo aujourd'hui à Lyon ?",
            source_speaker="expevay",
        )

        self.assertEqual(facts, [])

    def test_append_and_load_facts_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            facts_file = str(Path(tmpdir) / "facts_memory.json")
            facts_memory = {"channels": {}}

            append_reported_facts(
                facts_memory,
                "streamer",
                "dame_gaby",
                "MissCouette76 est aussi MissCouette pour information",
                facts_file=facts_file,
            )

            loaded = load_facts_memory(facts_file)
            stored = loaded["channels"]["streamer"]["facts"][0]
            self.assertEqual(stored["subject"], "MissCouette76")

    def test_build_facts_context_varies_by_current_author(self):
        facts_memory = {
            "channels": {
                "streamer": {
                    "facts": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
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

        reporter_context = build_facts_context(
            facts_memory,
            "streamer",
            "dame_gaby",
            "@anneaunimouss que peux tu me dire sur MissCouette76 ?",
        )
        subject_context = build_facts_context(
            facts_memory,
            "streamer",
            "misscouette76",
            "@anneaunimouss que sais tu sur moi ?",
        )

        self.assertIn("fait rapporte par toi", reporter_context)
        self.assertIn("fait incertain rapporte par dame_gaby sur toi", subject_context)

    def test_extract_group_name_and_membership_facts(self):
        facts = extract_reported_facts(
            'oui je joue à valheim, actuellement je joue avec Misscouette76 et Dae_3_7 où nous formons un trio surnommé "les Valkyrottes"',
            source_speaker="dame_gaby",
        )

        group_fact = next(fact for fact in facts if fact["predicate"] == "group_members")
        membership_facts = [fact for fact in facts if fact["predicate"] == "group_name"]

        self.assertEqual(group_fact["subject"], "les Valkyrottes")
        self.assertIn("dame_gaby", group_fact["value"].lower())
        self.assertEqual(len(membership_facts), 3)

    def test_build_facts_context_can_answer_group_name_from_members(self):
        facts_memory = {
            "channels": {
                "streamer": {
                    "facts": [
                        {
                            "timestamp": "2026-03-25T12:00:00+00:00",
                            "subject": "les Valkyrottes",
                            "predicate": "group_members",
                            "value": "dame_gaby, MissCouette76, Dae_3_7",
                            "source_speaker": "dame_gaby",
                            "verification_state": "self_confirmed",
                        }
                    ]
                }
            }
        }

        context = build_facts_context(
            facts_memory,
            "streamer",
            "expevay",
            "@anneaunimouss Gaby, MissCouette76 et Dae_3_7 sont dans un groupe. Quel est son nom ?",
        )

        self.assertIn("les Valkyrottes", context)
        self.assertIn("groupe compose de", context)


if __name__ == "__main__":
    unittest.main()
