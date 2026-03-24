from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("homegraph/data/homegraph.sqlite3")

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS viewer_profiles (
    viewer_id TEXT PRIMARY KEY,
    channel TEXT,
    viewer_login TEXT,
    display_name TEXT,
    summary_short TEXT,
    summary_long TEXT,
    last_updated_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS viewer_facts (
    fact_id TEXT PRIMARY KEY,
    viewer_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'active',
    valid_from TEXT,
    valid_to TEXT,
    source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    source_excerpt TEXT,
    last_reviewed_at TEXT,
    review_state TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (viewer_id) REFERENCES viewer_profiles(viewer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS viewer_relations (
    relation_id TEXT PRIMARY KEY,
    viewer_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id_or_value TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    confidence REAL,
    valid_from TEXT,
    valid_to TEXT,
    source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (viewer_id) REFERENCES viewer_profiles(viewer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS graph_jobs (
    job_id TEXT PRIMARY KEY,
    viewer_id TEXT,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    model_name TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS graph_job_items (
    item_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    source_ref TEXT,
    payload_json TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (job_id) REFERENCES graph_jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_viewer_facts_viewer_id
    ON viewer_facts(viewer_id);

CREATE INDEX IF NOT EXISTS idx_viewer_facts_kind
    ON viewer_facts(kind);

CREATE INDEX IF NOT EXISTS idx_viewer_facts_status
    ON viewer_facts(status);

CREATE INDEX IF NOT EXISTS idx_viewer_relations_viewer_id
    ON viewer_relations(viewer_id);

CREATE INDEX IF NOT EXISTS idx_viewer_relations_relation_type
    ON viewer_relations(relation_type);

CREATE INDEX IF NOT EXISTS idx_graph_jobs_viewer_id
    ON graph_jobs(viewer_id);

CREATE INDEX IF NOT EXISTS idx_graph_jobs_status
    ON graph_jobs(status);

CREATE INDEX IF NOT EXISTS idx_graph_job_items_job_id
    ON graph_job_items(job_id);
"""


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    resolved = Path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    return resolved
