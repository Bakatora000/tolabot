import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from admin_client import (
    AdminApiError,
    admin_healthcheck,
    delete_user_memories,
    forget_user_memory,
    get_homegraph_multihop_graph,
    get_homegraph_user_graph,
    get_recent_memories,
    list_admin_users,
    merge_homegraph_enrichment,
    preview_homegraph_enrichment,
    validate_homegraph_enrichment,
)
from bot_config import AppConfig
from homegraph_ids import resolve_homegraph_viewer_id


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


class AdminClientTests(unittest.TestCase):
    def test_admin_healthcheck_uses_local_capability(self):
        self.assertTrue(admin_healthcheck(make_config()))

    @patch("admin_client._load_local_memory_backend")
    def test_list_admin_users_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        backend.list_user_ids.return_value = [
            "twitch:streamer:viewer:alice",
            "twitch:integration:viewer:testuser",
        ]
        mock_backend_loader.return_value = backend

        users = list_admin_users(make_config(mem0_local_backend_enabled=True))

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].user_id, "twitch:streamer:viewer:alice")

    def test_delete_user_memories_returns_deleted_flag(self):
        backend = Mock()
        backend.purge_user.return_value = (2, False)
        with patch("admin_client._load_local_memory_backend", return_value=backend):
            result = delete_user_memories(make_config(), "twitch:streamer:viewer:alice")
        self.assertTrue(result.ok)
        self.assertEqual(result.deleted_count, 2)
        self.assertFalse(result.truncated)

    @patch("admin_client._load_local_memory_backend")
    def test_delete_user_memories_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        backend.purge_user.return_value = (3, False)
        mock_backend_loader.return_value = backend

        result = delete_user_memories(make_config(mem0_local_backend_enabled=True), "twitch:streamer:viewer:alice")

        self.assertTrue(result.ok)
        self.assertEqual(result.deleted_count, 3)
        backend.purge_user.assert_called_once()

    @patch("admin_client._load_local_memory_backend")
    def test_get_recent_memories_uses_local_backend_when_enabled(self, mock_backend_loader):
        backend = Mock()
        backend.recent.return_value = [
            Mock(
                id="mem_1",
                user_id="twitch:streamer:viewer:alice",
                memory="Souvenir",
                metadata={"source": "twitch_chat"},
                created_at="2026-03-27T10:00:00Z",
                updated_at="2026-03-27T10:00:00Z",
                score=1.0,
            )
        ]
        mock_backend_loader.return_value = backend

        results = get_recent_memories(make_config(mem0_local_backend_enabled=True), "twitch:streamer:viewer:alice")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "mem_1")
        self.assertEqual(results[0]["memory"], "Souvenir")

    @patch("admin_client._load_local_homegraph_modules")
    def test_get_homegraph_user_graph_uses_local_homegraph_when_enabled(self, mock_modules):
        build_viewer_graph_payload = Mock(return_value={"nodes": [], "links": [], "stats": {"node_count": 2}, "meta": {"source": "local"}})
        mock_modules.return_value = {
            "init_db": Mock(),
            "build_viewer_graph_payload": build_viewer_graph_payload,
            "build_multihop_graph_payload": Mock(),
            "build_viewer_context_payload": Mock(),
            "merge_payload": Mock(),
            "stable_node_kinds": ["viewer", "game", "topic"],
            "stable_link_kinds": [],
        }

        payload = get_homegraph_user_graph(
            make_config(homegraph_local_enabled=True),
            "twitch:streamer:viewer:alice",
            include_uncertain=False,
            min_weight=0.7,
            max_links=6,
        )

        self.assertEqual(payload["stats"]["node_count"], 2)
        build_viewer_graph_payload.assert_called_once()

    @patch("admin_client.resolve_homegraph_viewer_id")
    @patch("admin_client._load_local_homegraph_modules")
    def test_get_homegraph_user_graph_resolves_local_homegraph_viewer_id(self, mock_modules, mock_resolver):
        build_viewer_graph_payload = Mock(return_value={"nodes": [], "links": [], "stats": {"node_count": 2}, "meta": {"source": "local"}})
        mock_modules.return_value = {
            "init_db": Mock(),
            "build_viewer_graph_payload": build_viewer_graph_payload,
            "build_multihop_graph_payload": Mock(),
            "build_viewer_context_payload": Mock(),
            "merge_payload": Mock(),
            "stable_node_kinds": ["viewer", "game", "topic"],
            "stable_link_kinds": [],
        }
        mock_resolver.return_value = "twitch:streamer:viewer:alice"

        get_homegraph_user_graph(
            make_config(homegraph_local_enabled=True),
            "twitch:expevay:viewer:alice",
        )

        build_viewer_graph_payload.assert_called_once()
        args, _kwargs = build_viewer_graph_payload.call_args
        self.assertEqual(args[0], "twitch:streamer:viewer:alice")


class HomegraphViewerIdResolutionTests(unittest.TestCase):
    def test_resolve_prefers_richest_profile_for_same_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "homegraph.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE viewer_profiles (
                        viewer_id TEXT PRIMARY KEY,
                        channel TEXT,
                        viewer_login TEXT,
                        display_name TEXT,
                        summary_short TEXT,
                        summary_long TEXT,
                        source_ref TEXT,
                        model_name TEXT,
                        last_updated_at TEXT
                    );
                    CREATE TABLE viewer_facts (
                        fact_id TEXT PRIMARY KEY,
                        viewer_id TEXT NOT NULL,
                        kind TEXT,
                        value TEXT,
                        confidence REAL,
                        status TEXT,
                        source_memory_ids_json TEXT,
                        source_excerpt TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE viewer_relations (
                        relation_id TEXT PRIMARY KEY,
                        viewer_id TEXT NOT NULL,
                        target_type TEXT,
                        target_id_or_value TEXT,
                        relation_type TEXT,
                        confidence REAL,
                        status TEXT,
                        source_memory_ids_json TEXT,
                        source_excerpt TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE viewer_links (
                        link_id TEXT PRIMARY KEY,
                        viewer_id TEXT NOT NULL,
                        target_entity_id TEXT,
                        target_fallback_value TEXT,
                        relation_type TEXT,
                        strength REAL,
                        confidence REAL,
                        status TEXT,
                        polarity TEXT,
                        source_memory_ids_json TEXT,
                        source_excerpt TEXT,
                        updated_at TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO viewer_profiles (viewer_id, viewer_login) VALUES (?, ?)",
                    ("twitch:streamer:viewer:alice", "alice"),
                )
                conn.execute(
                    "INSERT INTO viewer_profiles (viewer_id, viewer_login) VALUES (?, ?)",
                    ("twitch:expevay:viewer:alice", "alice"),
                )
                conn.execute(
                    """
                    INSERT INTO viewer_relations (
                        relation_id, viewer_id, target_type, target_id_or_value, relation_type
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("rel_1", "twitch:expevay:viewer:alice", "game", "valheim", "plays"),
                )
                conn.commit()
            finally:
                conn.close()

            resolved = resolve_homegraph_viewer_id(db_path, "twitch:streamer:viewer:alice", "alice")
            self.assertEqual(resolved, "twitch:expevay:viewer:alice")

    @patch("admin_client._load_local_homegraph_modules")
    def test_merge_homegraph_enrichment_uses_local_sqlite_when_enabled(self, mock_modules):
        merge_payload_mock = Mock()
        build_viewer_context_payload = Mock(return_value={"context": {"summary_short": "Viewer regulier"}, "text_block": "Contexte viewer:\n- Viewer regulier"})
        build_viewer_graph_payload = Mock(return_value={"stats": {"node_count": 3, "link_count": 2}})
        mock_modules.return_value = {
            "init_db": Mock(),
            "build_viewer_graph_payload": build_viewer_graph_payload,
            "build_multihop_graph_payload": Mock(),
            "build_viewer_context_payload": build_viewer_context_payload,
            "merge_payload": merge_payload_mock,
            "stable_node_kinds": ["viewer", "game", "topic", "stream_mode", "object", "trait", "running_gag"],
            "stable_link_kinds": [],
        }

        result = merge_homegraph_enrichment(
            make_config(homegraph_local_enabled=True),
            "twitch:streamer:viewer:alice",
            {
                "viewer_id": "twitch:streamer:viewer:alice",
                "summary_short": "Viewer regulier",
                "facts": [],
                "relations": [],
                "links": [],
                "model_name": "gpt-5-mini",
                "source_ref": "test",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["graph_stats"]["node_count"], 3)
        merge_payload_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
