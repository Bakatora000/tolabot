from __future__ import annotations

import sqlite3
from pathlib import Path


def _viewer_slug(user_id: str) -> str:
    parts = str(user_id or "").strip().split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[3].strip().lower()
    return str(user_id or "").strip().lower()


def resolve_homegraph_viewer_id(db_path: Path | str, user_id: str, viewer_login: str | None = None) -> str:
    requested = str(user_id or "").strip()
    login = (viewer_login or "").strip().lower() or _viewer_slug(requested)
    if not requested:
        return requested

    try:
        conn = sqlite3.connect(Path(db_path))
    except sqlite3.Error:
        return requested
    conn.row_factory = sqlite3.Row
    try:
        candidates = conn.execute(
            """
            SELECT
                vp.viewer_id,
                COALESCE(vp.viewer_login, '') AS viewer_login,
                (
                    SELECT COUNT(*) FROM viewer_relations vr WHERE vr.viewer_id = vp.viewer_id
                ) AS relation_count,
                (
                    SELECT COUNT(*) FROM viewer_links vl WHERE vl.viewer_id = vp.viewer_id
                ) AS link_count,
                (
                    SELECT COUNT(*) FROM viewer_facts vf WHERE vf.viewer_id = vp.viewer_id
                ) AS fact_count
            FROM viewer_profiles vp
            WHERE LOWER(vp.viewer_id) = ?
               OR LOWER(COALESCE(vp.viewer_login, '')) = ?
               OR LOWER(vp.viewer_id) LIKE ?
            ORDER BY
                relation_count DESC,
                link_count DESC,
                fact_count DESC,
                LENGTH(vp.viewer_id) DESC
            """,
            (requested.lower(), login, f"%:{login}"),
        ).fetchall()
        if candidates:
            best = candidates[0]
            best_score = (
                int(best["relation_count"] or 0),
                int(best["link_count"] or 0),
                int(best["fact_count"] or 0),
            )
            exact = next(
                (row for row in candidates if str(row["viewer_id"]).strip().lower() == requested.lower()),
                None,
            )
            if exact:
                exact_score = (
                    int(exact["relation_count"] or 0),
                    int(exact["link_count"] or 0),
                    int(exact["fact_count"] or 0),
                )
                if exact_score >= best_score:
                    return str(exact["viewer_id"])
            return str(best["viewer_id"])
    finally:
        conn.close()

    return requested
