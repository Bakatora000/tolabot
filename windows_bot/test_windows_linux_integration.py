from __future__ import annotations

import os
import time
import unittest
from uuid import uuid4

from admin_client import admin_healthcheck, delete_memory, get_recent_memories, remember_user_memory
from admin_tunnel import AdminTunnelManager
from bot_config import AppConfig, load_config
from memory_client import build_mem0_user_id, get_memory_context, healthcheck_memory_api, is_mem0_enabled, store_memory_turn


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "oui", "on"}


RUN_WINDOWS_LINUX_INTEGRATION = _env_flag("RUN_WINDOWS_LINUX_INTEGRATION")


@unittest.skipUnless(
    RUN_WINDOWS_LINUX_INTEGRATION,
    "Set RUN_WINDOWS_LINUX_INTEGRATION=1 to run Windows/Linux integration tests.",
)
class WindowsLinuxIntegrationTests(unittest.TestCase):
    config: AppConfig
    tunnel: AdminTunnelManager

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        cls.tunnel = AdminTunnelManager(cls.config)
        cls.tunnel.start(startup_timeout_seconds=10.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tunnel.stop()

    def _make_user_identity(self) -> tuple[str, str, str]:
        channel = (self.config.channel_name or "integration").strip().lower()
        viewer = f"windows_linux_e2e_{uuid4().hex[:10]}"
        user_id = build_mem0_user_id(channel, viewer)
        return channel, viewer, user_id

    def _cleanup_user(self, user_id: str) -> None:
        try:
            memories = get_recent_memories(self.config, user_id)
        except Exception:
            return

        for item in memories:
            memory_id = str(item.get("id", "")).strip()
            if memory_id:
                delete_memory(self.config, memory_id)

    def test_admin_healthcheck_over_ssh_tunnel(self):
        self.assertTrue(admin_healthcheck(self.config))

    def test_admin_roundtrip_remember_recent_delete(self):
        _, _, user_id = self._make_user_identity()
        text = f"Souvenir admin integration {uuid4().hex[:8]} sur viewer de test."

        try:
            created = remember_user_memory(
                self.config,
                user_id,
                text,
                metadata={"source": "windows_linux_integration_test"},
            )
            memory_id = str(created.get("id", "")).strip()
            self.assertTrue(memory_id)

            memories = get_recent_memories(self.config, user_id)
            returned_ids = {str(item.get("id", "")).strip() for item in memories}
            returned_texts = {str(item.get("memory", "")).strip() for item in memories}

            self.assertIn(memory_id, returned_ids)
            self.assertIn(text, returned_texts)
        finally:
            self._cleanup_user(user_id)

    def test_public_mem0_healthcheck_when_configured(self):
        if not is_mem0_enabled(self.config):
            self.skipTest("Public mem0 API is not configured in .env.")
        self.assertTrue(healthcheck_memory_api(self.config))

    def test_public_mem0_roundtrip_when_configured(self):
        if not is_mem0_enabled(self.config):
            self.skipTest("Public mem0 API is not configured in .env.")

        channel, viewer, user_id = self._make_user_identity()
        token = uuid4().hex[:12]
        user_message = f"Pour info integration {token} aime les amplis compacts et les DAC R2R."
        bot_reply = "Bien noté pour la mémoire durable."

        try:
            memory_id = store_memory_turn(
                self.config,
                channel=channel,
                viewer=viewer,
                user_message=user_message,
                bot_reply=bot_reply,
                metadata={"source": "windows_linux_integration_test", "message_id": f"msg-{token}"},
            )
            self.assertTrue(memory_id)

            deadline = time.time() + 10.0
            context = {"items": []}
            while time.time() < deadline:
                context = get_memory_context(
                    self.config,
                    channel=channel,
                    viewer=viewer,
                    message=f"Que sais-tu sur integration {token} ?",
                )
                if context.get("items"):
                    break
                time.sleep(0.5)

            self.assertTrue(context.get("items"))
            self.assertTrue(
                any(token in str(item.get("memory", "")).lower() for item in context["items"])
            )
        finally:
            self._cleanup_user(user_id)


if __name__ == "__main__":
    unittest.main()
