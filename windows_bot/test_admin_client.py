import unittest
from unittest.mock import Mock, patch

from admin_client import (
    AdminApiError,
    admin_healthcheck,
    delete_user_memories,
    list_admin_users,
)
from bot_config import AppConfig


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
        "mem0_enabled": False,
        "mem0_api_base_url": "",
        "mem0_api_key": "",
        "mem0_timeout_seconds": 10,
        "mem0_verify_ssl": True,
        "mem0_context_limit": 5,
        "mem0_fallback_local": True,
        "message_queue_max_size": 6,
        "message_queue_max_age_seconds": 25,
        "admin_ui_enabled": True,
        "admin_api_local_url": "http://127.0.0.1:9000",
        "admin_api_key": "admin-secret",
        "admin_api_timeout_seconds": 10,
        "admin_ssh_host": "server",
        "admin_ssh_user": "vhserver",
        "admin_ssh_local_port": 9000,
        "admin_ssh_remote_port": 9000,
        "admin_ui_host": "127.0.0.1",
        "admin_ui_port": 9100,
    }
    base.update(overrides)
    return AppConfig(**base)


class AdminClientTests(unittest.TestCase):
    @patch("admin_client.requests.request")
    def test_admin_healthcheck_hits_expected_endpoint(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "status": "ok"}
        mock_request.return_value = response

        self.assertTrue(admin_healthcheck(make_config()))
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["X-Admin-Key"], "admin-secret")

    @patch("admin_client.requests.request")
    def test_list_admin_users_parses_users(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "ok": True,
            "users": [
                {"user_id": "twitch:streamer:viewer:alice", "channel": "streamer", "viewer": "alice"}
            ],
        }
        mock_request.return_value = response

        users = list_admin_users(make_config())
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].viewer, "alice")

    @patch("admin_client.requests.request")
    def test_delete_user_memories_returns_deleted_flag(self, mock_request):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "deleted": True}
        mock_request.return_value = response

        self.assertTrue(delete_user_memories(make_config(), "twitch:streamer:viewer:alice"))

    @patch("admin_client.requests.request")
    def test_admin_client_raises_clear_error_on_http_failure(self, mock_request):
        response = Mock()
        response.status_code = 403
        response.json.return_value = {"ok": False, "error": "invalid_admin_key"}
        mock_request.return_value = response

        with self.assertRaises(AdminApiError):
            list_admin_users(make_config())


if __name__ == "__main__":
    unittest.main()
