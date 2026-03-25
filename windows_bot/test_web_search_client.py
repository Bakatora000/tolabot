import unittest
from unittest.mock import Mock, patch

from web_search_client import build_web_search_context, build_web_search_query, search_searxng, should_enable_web_search


class WebSearchClientTests(unittest.TestCase):
    def test_should_enable_web_search_auto_detects_external_queries(self):
        self.assertTrue(should_enable_web_search("quelle est la météo aujourd'hui ?"))
        self.assertTrue(should_enable_web_search("quel est le prix du bitcoin ?"))
        self.assertTrue(should_enable_web_search("quelle est le meilleur film de 2025 ?"))
        self.assertFalse(
            should_enable_web_search(
                "que peux tu me dire sur Dame_Gaby ?",
                viewer_context="alice: qui est Dame_Gaby ?\nbot: Dame_Gaby joue à Valheim.",
                global_context="aucun",
            )
        )

    def test_should_enable_web_search_on_followup_when_recent_context_is_external(self):
        self.assertTrue(
            should_enable_web_search(
                "et pour demain ?",
                viewer_context="alice: quelle est la météo aujourd'hui à Lyon ?\nbot: Selon les données, il fait actuellement nuageux à Lyon aujourd'hui.",
                global_context="aucun",
            )
        )

    def test_should_enable_web_search_on_temperature_followup_when_recent_context_is_weather(self):
        self.assertTrue(
            should_enable_web_search(
                "et la température ?",
                viewer_context="alice: quel temps fait il actuellement à Villeurbanne ?\nbot: Il pleut actuellement à Villeurbanne !",
                global_context="aucun",
            )
        )

    def test_build_web_search_query_uses_recent_weather_location_for_followup(self):
        query = build_web_search_query(
            "et pour demain ?",
            viewer_context="alice: quelle est la météo aujourd'hui à Lyon ?\nbot: Selon les données, il fait actuellement nuageux à Lyon aujourd'hui.",
            global_context="aucun",
        )

        self.assertEqual(query, "météo demain à Lyon")

    def test_build_web_search_query_uses_recent_weather_location_for_temperature_followup(self):
        query = build_web_search_query(
            "et la température ?",
            viewer_context="alice: quel temps fait il actuellement à Villeurbanne ?\nbot: Il pleut actuellement à Villeurbanne !",
            global_context="aucun",
        )

        self.assertEqual(query, "température actuelle à Villeurbanne")

    def test_build_web_search_query_uses_recent_weather_location_for_weekday_followup(self):
        query = build_web_search_query(
            "et pour vendredi, il fera beau?",
            viewer_context="alice: que dit la météo pour demain soir à Lyon?\nbot: Selon les sources web, la température à Lyon ce soir devrait être d'environ 13°C.",
            global_context="aucun",
        )

        self.assertEqual(query, "météo vendredi à Lyon")

    def test_build_web_search_query_normalizes_reuters_front_page_request(self):
        query = build_web_search_query(
            "dans l'actualité de la semaine, que dit l'agence de press Reuters en première page?",
            viewer_context="aucun",
            global_context="aucun",
        )

        self.assertEqual(query, "Reuters actualité première page")

    def test_build_web_search_query_normalizes_best_film_request(self):
        query = build_web_search_query(
            "quelle est le meilleur film de 2025 ?",
            viewer_context="aucun",
            global_context="aucun",
        )

        self.assertEqual(query, "meilleur film 2025")

    @patch("web_search_client.requests.get")
    def test_search_searxng_parses_results(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "results": [
                {
                    "title": "Météo Paris",
                    "url": "https://example.com/meteo",
                    "content": "Temps doux aujourd'hui.",
                }
            ]
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        results = search_searxng(
            "quelle est la météo à Paris ?",
            base_url="http://127.0.0.1:8888",
            timeout_seconds=8,
            max_results=5,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Météo Paris")
        self.assertEqual(mock_get.call_args.kwargs["params"]["format"], "json")

    def test_build_web_search_context_formats_sources(self):
        context = build_web_search_context(
            [
                {
                    "title": "Météo Paris",
                    "content": "Temps doux aujourd'hui.",
                    "url": "https://example.com/meteo",
                }
            ]
        )

        self.assertIn("[1] Météo Paris", context)
        self.assertIn("Temps doux aujourd'hui.", context)
        self.assertIn("https://example.com/meteo", context)


if __name__ == "__main__":
    unittest.main()
