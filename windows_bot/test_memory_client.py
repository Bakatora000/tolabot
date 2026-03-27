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
        "openai_review_enabled": False,
        "openai_api_key": "",
        "openai_review_model": "gpt-5-mini",
        "openai_review_timeout_seconds": 90,
        "openai_review_max_records": 50,
    }
    base.update(overrides)
    return AppConfig(**base)


class MemoryClientTests(unittest.TestCase):
    def test_build_mem0_user_id_normalizes_channel_and_viewer(self):
        self.assertEqual(build_mem0_user_id("Streamer ", " Alice "), "twitch:streamer:viewer:alice")

    def test_is_useful_memory_item_filters_low_value_fragments(self):
        self.assertFalse(is_useful_memory_item(MemorySearchItem(id="1", score=0.8, memory="bonjour")))
        self.assertFalse(is_useful_memory_item(MemorySearchItem(id="2", score=0.2, memory="Possède un DAC FiiO K11 R2R.")))
        self.assertTrue(is_useful_memory_item(MemorySearchItem(id="3", score=0.8, memory="Possède un DAC FiiO K11 R2R.")))

    def test_should_store_in_mem0_keeps_durable_items_and_skips_noise(self):
        self.assertTrue(should_store_in_mem0("je joue aussi sur world of warcraft", "Tu joues aussi à World of Warcraft ?"))
        self.assertTrue(should_store_in_mem0("n'oublie pas que viewer_pet est un gentil bouledogue français", "Bien noté.", author_is_owner=True))
        self.assertFalse(should_store_in_mem0("n'oublie pas que viewer_pet est un gentil bouledogue français", "Bien noté.", author_is_owner=False))
        self.assertFalse(should_store_in_mem0("bonjour", "Salut"))
        self.assertFalse(should_store_in_mem0("dit moi le meilleur jeu de 2025", "Valheim"))
        self.assertFalse(should_store_in_mem0("Bravo! Bien joué.", "Merci !"))
        self.assertFalse(should_store_in_mem0("Mon premier n'est pas haut", "NO_REPLY"))

    def test_store_memory_turn_skips_low_value_memory(self):
        memory_id = store_memory_turn(
            make_config(),
            channel="streamer",
            viewer="alice",
            user_message="bonjour",
            bot_reply="Salut",
            metadata={"source": "twitch_chat", "message_id": "msg-2"},
        )

        self.assertIsNone(memory_id)

    @patch("memory_client._get_local_memory_backend")
    def test_healthcheck_memory_api_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        mock_backend_loader.return_value = backend

        self.assertTrue(healthcheck_memory_api(make_config(mem0_local_backend_enabled=True)))
        backend.healthcheck.assert_called_once()

    @patch("memory_client._get_local_memory_backend")
    def test_get_memory_context_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        backend.search.return_value = [
            Mock(id="mem_1", score=0.91, memory="Préfère les amplis compacts."),
            Mock(id="mem_2", score=0.87, memory="Possède un DAC FiiO K11 R2R."),
        ]
        mock_backend_loader.return_value = backend

        context = get_memory_context(
            make_config(mem0_local_backend_enabled=True),
            "streamer",
            "alice",
            "On parlait de quoi déjà ?",
        )

        self.assertIn("alice: Préfère les amplis compacts.", context["viewer_context"])
        self.assertEqual(len(context["items"]), 2)

    @patch("memory_client._get_local_memory_backend")
    def test_store_memory_turn_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        backend.remember.return_value = "mem_local_123"
        mock_backend_loader.return_value = backend

        memory_id = store_memory_turn(
            make_config(mem0_local_backend_enabled=True),
            channel="streamer",
            viewer="alice",
            user_message="Salut bot",
            bot_reply="Salut Alice",
            metadata={"source": "twitch_chat", "message_id": "msg-1"},
        )

        self.assertEqual(memory_id, "mem_local_123")
        backend.remember.assert_called_once()


if __name__ == "__main__":
    unittest.main()
