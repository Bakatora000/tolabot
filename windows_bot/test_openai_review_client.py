import unittest
from unittest.mock import Mock, patch

from bot_config import AppConfig
from openai_review_client import analyze_review_export, build_review_export


def make_config(**overrides) -> AppConfig:
    base = {
        "client_id": "",
        "client_secret": "",
        "bot_id": "",
        "owner_id": "",
        "bot_token": "",
        "refresh_token": "",
        "channel_name": "streamer",
        "ollama_url": "http://localhost:11434/api/chat",
        "default_ollama_model": "qwen3.5:latest",
        "request_timeout_seconds": 90,
        "chat_memory_ttl_hours": 10,
        "debug_chat_memory": False,
        "global_cooldown_seconds": 2,
        "user_cooldown_seconds": 8,
        "mem0_context_limit": 5,
        "mem0_local_backend_enabled": True,
        "message_queue_max_size": 6,
        "message_queue_max_age_seconds": 25,
        "admin_ui_enabled": True,
        "homegraph_local_enabled": True,
        "homegraph_db_path": "C:/tmp/homegraph.sqlite3",
        "admin_ui_host": "127.0.0.1",
        "admin_ui_port": 9100,
        "openai_review_enabled": True,
        "openai_api_key": "sk-test",
        "openai_review_model": "gpt-5-mini",
        "openai_review_timeout_seconds": 60,
        "openai_review_max_records": 2,
    }
    base.update(overrides)
    return AppConfig(**base)


class OpenAIReviewClientTests(unittest.TestCase):
    def test_build_review_export_compacts_payload(self):
        export_payload = {
            "export": {
                "user_id": "twitch:streamer:viewer:alice",
                "count": 3,
                "records": [
                    {"id": "1", "memory": "  bonjour   Réponse du bot: salut  ", "metadata": {"viewer": "alice"}},
                    {"id": "2", "memory": "je joue aussi sur world of warcraft"},
                    {"id": "3", "memory": "ignored because max records is 2"},
                ],
            }
        }

        compact = build_review_export(make_config(), export_payload)

        self.assertEqual(compact["viewer"], "alice")
        self.assertEqual(compact["user_id"], "twitch:streamer:viewer:alice")
        self.assertEqual(len(compact["records"]), 2)
        self.assertEqual(compact["records"][0], {"id": "1", "text": "bonjour Réponse du bot: salut"})

    @patch("openai_review_client.requests.post")
    def test_analyze_review_export_asks_for_french_text_fields(self, mock_post):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "output_text": (
                '{"viewer":"alice","summary":"RAS","proposals":['
                '{"memory_id":"1","action":"keep","reason":"factuel","proposed_text":"","target_memory_id":""}'
                "]}"
            )
        }
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        review_export = {
            "viewer": "alice",
            "user_id": "twitch:streamer:viewer:alice",
            "count": 1,
            "records": [{"id": "1", "text": "alice aime valheim"}],
        }

        analyze_review_export(make_config(), review_export, severity="balanced")

        payload = mock_post.call_args.kwargs["json"]
        system_prompt = payload["input"][0]["content"]
        user_prompt = payload["input"][1]["content"]

        self.assertIn("Ecris obligatoirement en francais", system_prompt)
        self.assertIn("Retourne les champs textuels en francais", user_prompt)


if __name__ == "__main__":
    unittest.main()
