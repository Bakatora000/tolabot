import unittest
from unittest.mock import Mock, patch

from admin_tunnel import AdminTunnelManager, build_ssh_tunnel_command
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
        "admin_ssh_host": "server.example.net",
        "admin_ssh_user": "vhserver",
        "admin_ssh_local_port": 9000,
        "admin_ssh_remote_port": 8000,
        "admin_ui_host": "127.0.0.1",
        "admin_ui_port": 9100,
    }
    base.update(overrides)
    return AppConfig(**base)


class AdminTunnelTests(unittest.TestCase):
    def test_build_ssh_tunnel_command_uses_expected_ports(self):
        command = build_ssh_tunnel_command(make_config())
        self.assertIn("9000:127.0.0.1:8000", command)
        self.assertIn("vhserver@server.example.net", command)

    @patch("admin_tunnel.is_local_port_open", side_effect=[False, True, True])
    @patch("admin_tunnel.subprocess.Popen")
    def test_tunnel_manager_start_waits_until_port_is_ready(self, mock_popen, mock_port_open):
        process = Mock()
        process.poll.return_value = None
        process.pid = 1234
        mock_popen.return_value = process

        manager = AdminTunnelManager(make_config())
        status = manager.start(startup_timeout_seconds=1.0)

        self.assertTrue(status.local_port_open)
        self.assertEqual(status.pid, 1234)

    @patch("admin_tunnel.is_local_port_open", return_value=False)
    @patch("admin_tunnel.subprocess.Popen")
    def test_tunnel_manager_start_surfaces_ssh_stderr(self, mock_popen, _mock_port_open):
        process = Mock()
        process.poll.return_value = 255
        process.pid = 1234
        process.stderr.read.return_value = "Permission denied (publickey)."
        mock_popen.return_value = process

        manager = AdminTunnelManager(make_config())

        with self.assertRaisesRegex(RuntimeError, "Permission denied"):
            manager.start(startup_timeout_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
