import unittest

from homegraph.bootstrap_mem0_heuristic import heuristic_extract


class BootstrapMem0HeuristicTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
