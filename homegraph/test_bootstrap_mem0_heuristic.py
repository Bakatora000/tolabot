import unittest

from homegraph.bootstrap_mem0_heuristic import find_viewers, heuristic_extract


class BootstrapMem0HeuristicTests(unittest.TestCase):
    def test_find_viewers_ignores_sentence_verbs_but_keeps_twitch_like_names(self) -> None:
        viewers = find_viewers("Arthii_TV affirme que Satisfactory est un bon jeu.")

        self.assertIn("Arthii_TV", viewers)
        self.assertNotIn("Affirme", viewers)

    def test_find_viewers_ignores_pronouns_and_pet_names(self) -> None:
        viewers = find_viewers("Elle parle souvent de Dakota, son chien, sur le stream.")

        self.assertNotIn("Elle", viewers)
        self.assertNotIn("Dakota", viewers)

    def test_heuristic_extract_emits_links_v2(self) -> None:
        payload = {
            "user_id": "twitch:streamer:viewer:alice",
            "channel": "streamer",
            "viewer": "alice",
            "memories": [
                {
                    "id": "mem_1",
                    "memory": "Je joue surtout a Satisfactory et j'adore optimiser mes usines.",
                },
                {
                    "id": "mem_2",
                    "memory": "Sur Valheim je tente du no death en cauchemar.",
                },
                {
                    "id": "mem_3",
                    "memory": "Je complimente parfois Sarahp79 pour ses builds.",
                },
            ],
        }

        extraction = heuristic_extract(payload)
        links = {(item["target_type"], item["target_value"], item["relation_type"]) for item in extraction["links"]}

        self.assertIn(("game", "Satisfactory", "plays"), links)
        self.assertIn(("game", "Satisfactory", "likes"), links)
        self.assertIn(("topic", "automation", "talks_about"), links)
        self.assertIn(("stream_mode", "no death", "plays_in_mode"), links)
        self.assertIn(("viewer", "Sarahp79", "compliments"), links)
        self.assertGreaterEqual(len(extraction["links"]), 5)

    def test_heuristic_extract_does_not_promote_known_games_to_viewers(self) -> None:
        payload = {
            "user_id": "twitch:streamer:viewer:arthii_tv",
            "channel": "streamer",
            "viewer": "arthii_tv",
            "memories": [
                {
                    "id": "mem_1",
                    "memory": "Affirme être un builder compétent sur Satisfactory qui lit son chat pendant ses constructions et qui complimente parfois Sarahp79.",
                },
            ],
        }

        extraction = heuristic_extract(payload)
        viewer_links = {
            (item["target_value"], item["relation_type"])
            for item in extraction["links"]
            if item["target_type"] == "viewer"
        }

        self.assertIn(("Sarahp79", "compliments"), viewer_links)
        self.assertNotIn(("Satisfactory", "compliments"), viewer_links)
        self.assertNotIn(("Satisfactory", "knows"), viewer_links)


if __name__ == "__main__":
    unittest.main()
