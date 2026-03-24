import unittest
from unittest.mock import Mock, patch

from ollama_client import ask_ollama, summarize_channel_profile


class OllamaClientTests(unittest.TestCase):
    @patch("ollama_client.requests.post")
    def test_ask_ollama_sends_sanitized_prompt_and_returns_normalized_text(self, mock_post):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"message": {"content": "  Salut\nà toi  "}}
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        result = ask_ollama(
            user_name="alice",
            message="@anneaunimouss   Salut&nbsp;!\nComment ça va ?",
            ollama_url="http://localhost:11434/api/chat",
            ollama_model="qwen3.5:latest",
            request_timeout_seconds=42,
            viewer_context="alice: Salut bot\nbot: Salut Alice",
            global_context="bob: Salut a tous\nbot: Hello Bob",
            conversation_mode="riddle_final",
        )

        self.assertEqual(result, "Salut à toi")
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 42)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "qwen3.5:latest")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["think"], False)
        self.assertIn("solution finale", payload["messages"][0]["content"])
        self.assertIn("<viewer_context>alice: Salut bot\nbot: Salut Alice</viewer_context>", payload["messages"][1]["content"])
        self.assertIn("<global_chat_context>bob: Salut a tous\nbot: Hello Bob</global_chat_context>", payload["messages"][1]["content"])
        self.assertIn("<viewer_message>Salut ! Comment ça va ?</viewer_message>", payload["messages"][1]["content"])

    @patch("ollama_client.requests.post")
    def test_summarize_channel_profile_returns_local_fallback_when_history_is_empty(self, mock_post):
        result = summarize_channel_profile(
            profile={"top_categories": [], "recent_titles": []},
            ollama_url="http://localhost:11434/api/chat",
            ollama_model="qwen3.5:latest",
            request_timeout_seconds=30,
        )

        self.assertIn("historique local", result)
        mock_post.assert_not_called()

    @patch("ollama_client.requests.post")
    def test_summarize_channel_profile_posts_observed_history(self, mock_post):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"message": {"content": "  La chaîne parle surtout de survie.  "}}
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        result = summarize_channel_profile(
            profile={
                "top_categories": [("Valheim", 3), ("Minecraft", 1)],
                "recent_titles": ["Night run", "Build chill"],
            },
            ollama_url="http://localhost:11434/api/chat",
            ollama_model="mistral:latest",
            request_timeout_seconds=15,
        )

        self.assertEqual(result, "La chaîne parle surtout de survie.")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "mistral:latest")
        self.assertIn("- Valheim: 3 fois", payload["messages"][1]["content"])
        self.assertIn("- Night run", payload["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
