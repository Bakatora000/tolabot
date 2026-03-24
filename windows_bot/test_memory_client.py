import unittest
from unittest.mock import Mock, patch

from bot_config import AppConfig
from memory_client import (
    MemoryApiError,
    build_mem0_user_id,
    get_memory_context,
    healthcheck_memory_api,
    is_useful_memory_item,
    MemorySearchItem,
    should_store_in_mem0,
    store_memory_turn,
)


def make_config(**overrides) -> AppConfig:
    base = {
        "client_id": "",
        "client_secret": "",
        "bot_id": "",
        "owner_id": "",
        "bot_token": "",
        "refresh_token": "",
        "channel_name": "expevay",
        "ollama_url": "http://localhost:11434/api/chat",
        "default_ollama_model": "qwen3.5:latest",
        "request_timeout_seconds": 90,
        "chat_memory_ttl_hours": 10,
        "debug_chat_memory": False,
        "global_cooldown_seconds": 2,
        "user_cooldown_seconds": 8,
        "mem0_enabled": True,
        "mem0_api_base_url": "https://olala.expevay.net/api/memory",
        "mem0_api_key": "secret",
        "mem0_timeout_seconds": 10,
        "mem0_verify_ssl": True,
        "mem0_context_limit": 5,
        "mem0_fallback_local": True,
    }
    base.update(overrides)
    return AppConfig(**base)


class MemoryClientTests(unittest.TestCase):
    def test_build_mem0_user_id_normalizes_channel_and_viewer(self):
        self.assertEqual(build_mem0_user_id("Expevay ", " Alice "), "twitch:expevay:viewer:alice")

    def test_is_useful_memory_item_filters_low_value_fragments(self):
        self.assertFalse(is_useful_memory_item(MemorySearchItem(id="1", score=0.8, memory="bonjour")))
        self.assertFalse(is_useful_memory_item(MemorySearchItem(id="2", score=0.2, memory="Possède un DAC FiiO K11 R2R.")))
        self.assertTrue(is_useful_memory_item(MemorySearchItem(id="3", score=0.8, memory="Possède un DAC FiiO K11 R2R.")))

    def test_should_store_in_mem0_keeps_durable_items_and_skips_noise(self):
        self.assertTrue(should_store_in_mem0("je joue aussi sur world of warcraft", "Tu joues aussi à World of Warcraft ?"))
        self.assertTrue(should_store_in_mem0("n'oublie pas que dame_gaby est un gentil bouledogue français", "Bien noté.", author_is_owner=True))
        self.assertFalse(should_store_in_mem0("n'oublie pas que dame_gaby est un gentil bouledogue français", "Bien noté.", author_is_owner=False))
        self.assertFalse(should_store_in_mem0("bonjour", "Salut"))
        self.assertFalse(should_store_in_mem0("dit moi le meilleur jeu de 2025", "Valheim"))
        self.assertFalse(should_store_in_mem0("Bravo! Bien joué.", "Merci !"))
        self.assertFalse(should_store_in_mem0("Mon premier n'est pas haut", "NO_REPLY"))

    @patch("memory_client.requests.request")
    def test_healthcheck_memory_api_hits_expected_endpoint(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"status": "ok", "service": "mem0-api"}
        mock_request.return_value = response

        self.assertTrue(healthcheck_memory_api(make_config()))
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["X-API-Key"], "secret")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertTrue(kwargs["verify"])

    @patch("memory_client.requests.request")
    def test_get_memory_context_flattens_search_results(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "ok": True,
            "results": [
                {"id": "mem_0", "score": 0.9, "memory": "bonjour"},
                {"id": "mem_1", "score": 0.9, "memory": "Préfère les amplis compacts."},
                {"id": "mem_2", "score": 0.8, "memory": "Possède un DAC FiiO K11 R2R."},
            ],
        }
        mock_request.return_value = response

        context = get_memory_context(make_config(), "expevay", "alice", "On parlait de quoi déjà ?")

        self.assertIn("alice: Préfère les amplis compacts.", context["viewer_context"])
        self.assertNotIn("bonjour", context["viewer_context"].lower())
        self.assertEqual(context["global_context"], "aucun")
        self.assertEqual(len(context["items"]), 2)
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["json"]["user_id"], "twitch:expevay:viewer:alice")
        self.assertEqual(kwargs["json"]["limit"], 5)

    @patch("memory_client.requests.request")
    def test_store_memory_turn_posts_combined_text_and_metadata(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "id": "mem_123"}
        mock_request.return_value = response

        memory_id = store_memory_turn(
            make_config(),
            channel="expevay",
            viewer="alice",
            user_message="Salut bot",
            bot_reply="Salut Alice",
            metadata={"source": "twitch_chat", "message_id": "msg-1"},
        )

        self.assertEqual(memory_id, "mem_123")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["json"]["user_id"], "twitch:expevay:viewer:alice")
        self.assertEqual(kwargs["json"]["metadata"]["channel"], "expevay")
        self.assertEqual(kwargs["json"]["metadata"]["viewer"], "alice")
        self.assertEqual(kwargs["json"]["metadata"]["message_id"], "msg-1")
        self.assertIn("Réponse du bot: Salut Alice", kwargs["json"]["text"])

    @patch("memory_client.requests.request")
    def test_store_memory_turn_skips_low_value_memory(self, mock_request):
        memory_id = store_memory_turn(
            make_config(),
            channel="expevay",
            viewer="alice",
            user_message="bonjour",
            bot_reply="Salut",
            metadata={"source": "twitch_chat", "message_id": "msg-2"},
        )

        self.assertIsNone(memory_id)
        mock_request.assert_not_called()

    @patch("memory_client.requests.request")
    def test_search_raises_clear_error_on_http_failure(self, mock_request):
        response = Mock()
        response.status_code = 403
        response.json.return_value = {"ok": False, "error": "invalid_api_key"}
        mock_request.return_value = response

        with self.assertRaises(MemoryApiError):
            get_memory_context(make_config(), "expevay", "alice", "test")


if __name__ == "__main__":
    unittest.main()
