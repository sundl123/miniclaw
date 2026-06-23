"""SQLite session store with FTS5 search."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from typing import Any

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    workspace TEXT,
    model TEXT,
    jsonl_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    type TEXT,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);
"""

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content)
    SELECT new.id, COALESCE(new.content, '')
    WHERE new.type IS NULL AND new.role IN ('user', 'assistant');
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, COALESCE(old.content, ''));
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, COALESCE(old.content, ''));
    INSERT INTO messages_fts(rowid, content)
    SELECT new.id, COALESCE(new.content, '')
    WHERE new.type IS NULL AND new.role IN ('user', 'assistant');
END;
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _sanitize_fts_query(query: str) -> str:
    """Basic FTS5 query sanitization."""
    q = (query or "").strip()
    if not q:
        return ""
    # Quote dotted/hyphenated tokens for unicode61
    parts = []
    for token in q.split():
        if re.match(r"^[\w.-]+$", token) and ("." in token or "-" in token):
            parts.append(f'"{token}"')
        else:
            parts.append(token)
    return " ".join(parts)


class SessionDB:
    """SQLite-backed session message store."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._fts_available = self._init_schema()

    @property
    def fts_available(self) -> bool:
        return self._fts_available

    def _init_schema(self) -> bool:
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
            fts_ok = True
            try:
                self._conn.executescript(_FTS_SQL)
            except sqlite3.OperationalError:
                fts_ok = False
            self._conn.commit()
            return fts_ok

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert_session(
        self,
        session_id: str,
        *,
        started_at: str,
        workspace: str,
        model: str,
        jsonl_path: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    id, started_at, updated_at, workspace, model, jsonl_path
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, started_at, started_at, workspace, model, jsonl_path),
            )
            self._conn.commit()

    def insert_message(
        self,
        session_id: str,
        seq: int,
        *,
        ts: str,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list | dict | None = None,
        type: str | None = None,
    ) -> int:
        tool_calls_json = None
        if tool_calls is not None:
            tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO messages (
                    session_id, seq, ts, role, content,
                    tool_name, tool_call_id, tool_calls, type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, seq, ts, role, content,
                    tool_name, tool_call_id, tool_calls_json, type,
                ),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (ts, session_id),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def get_message_by_seq(self, session_id: str, seq: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND seq = ?",
                (session_id, seq),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def count_messages(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ? AND type IS NULL",
                (session_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def get_first_user_preview(self, session_id: str, max_chars: int = 80) -> str:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT content FROM messages
                WHERE session_id = ? AND role = 'user' AND type IS NULL
                ORDER BY seq ASC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row or not row["content"]:
            return ""
        text = row["content"]
        return text[:max_chars] + ("…" if len(text) > max_chars else "")

    def browse_sessions(
        self,
        limit: int = 10,
        *,
        exclude_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.*,
                    (SELECT COUNT(*) FROM messages m
                     WHERE m.session_id = s.id AND m.type IS NULL) AS message_count
                FROM sessions s
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (limit + 5,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            sid = row["id"]
            if exclude_session_id and sid == exclude_session_id:
                continue
            results.append({
                "session_id": sid,
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
                "workspace": row["workspace"],
                "model": row["model"],
                "message_count": row["message_count"],
                "preview": self.get_first_user_preview(sid),
            })
            if len(results) >= limit:
                break
        return results

    def search_messages(
        self,
        query: str,
        *,
        limit: int = 10,
        sort: str | None = None,
        exclude_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        if self._fts_available and not (_has_cjk(q) and len(q) < 6):
            results = self._search_fts(q, limit=limit * 5, sort=sort)
        else:
            results = self._search_like(q, limit=limit * 5, sort=sort)

        if exclude_session_id:
            results = [r for r in results if r.get("session_id") != exclude_session_id]

        # Dedupe by session, keep best rank per session
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for r in results:
            sid = r.get("session_id", "")
            if sid in seen:
                continue
            seen.add(sid)
            deduped.append(r)
            if len(deduped) >= limit:
                break
        return deduped

    def _search_fts(
        self,
        query: str,
        *,
        limit: int,
        sort: str | None,
    ) -> list[dict[str, Any]]:
        fts_q = _sanitize_fts_query(query)
        if not fts_q:
            return self._search_like(query, limit=limit, sort=sort)

        sort_norm = (sort or "").strip().lower()
        if sort_norm == "newest":
            order_by = "ORDER BY m.ts DESC, rank"
        elif sort_norm == "oldest":
            order_by = "ORDER BY m.ts ASC, rank"
        else:
            order_by = "ORDER BY rank"

        sql = f"""
            SELECT m.*, rank
            FROM messages_fts f
            JOIN messages m ON m.id = f.rowid
            WHERE messages_fts MATCH ?
              AND m.type IS NULL
              AND m.role IN ('user', 'assistant')
            {order_by}
            LIMIT ?
        """
        try:
            with self._lock:
                rows = self._conn.execute(sql, (fts_q, limit)).fetchall()
        except sqlite3.OperationalError:
            return self._search_like(query, limit=limit, sort=sort)

        return [self._hydrate_search_row(row) for row in rows]

    def _search_like(
        self,
        query: str,
        *,
        limit: int,
        sort: str | None,
    ) -> list[dict[str, Any]]:
        sort_norm = (sort or "").strip().lower()
        if sort_norm == "oldest":
            order_by = "ORDER BY m.ts ASC"
        else:
            order_by = "ORDER BY m.ts DESC"

        pattern = f"%{query}%"
        sql = f"""
            SELECT m.*, 0 AS rank
            FROM messages m
            WHERE m.type IS NULL
              AND m.role IN ('user', 'assistant')
              AND m.content LIKE ?
            {order_by}
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (pattern, limit)).fetchall()
        return [self._hydrate_search_row(row) for row in rows]

    def _hydrate_search_row(self, row: sqlite3.Row) -> dict[str, Any]:
        d = _row_to_dict(row)
        content = d.get("content") or ""
        snippet = content[:200] + ("…" if len(content) > 200 else "")
        d["snippet"] = snippet
        if d.get("tool_calls"):
            try:
                d["tool_calls"] = json.loads(d["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d

    def get_messages_around(
        self,
        session_id: str,
        around_seq: int,
        *,
        window: int = 5,
    ) -> dict[str, Any]:
        anchor = self.get_message_by_seq(session_id, around_seq)
        if anchor is None:
            return {"window": [], "messages_before": 0, "messages_after": 0}

        with self._lock:
            before_rows = self._conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND seq <= ? AND type IS NULL
                ORDER BY seq DESC
                LIMIT ?
                """,
                (session_id, around_seq, window + 1),
            ).fetchall()
            after_rows = self._conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND seq > ? AND type IS NULL
                ORDER BY seq ASC
                LIMIT ?
                """,
                (session_id, around_seq, window),
            ).fetchall()

        before = list(reversed(before_rows))
        combined = before + list(after_rows)
        messages = [_row_to_dict(r) for r in combined]
        for m in messages:
            if m.get("tool_calls"):
                try:
                    m["tool_calls"] = json.loads(m["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    pass

        messages_before = max(0, len(before) - 1)
        messages_after = len(after_rows)
        return {
            "window": messages,
            "messages_before": messages_before,
            "messages_after": messages_after,
        }

    def get_bookends(
        self,
        session_id: str,
        *,
        bookend: int = 3,
        window_min_seq: int,
        window_max_seq: int,
    ) -> dict[str, list[dict[str, Any]]]:
        role_clause = "role IN ('user', 'assistant')"
        with self._lock:
            start_rows = self._conn.execute(
                f"""
                SELECT * FROM messages
                WHERE session_id = ? AND type IS NULL AND seq < ?
                  AND {role_clause} AND length(COALESCE(content, '')) > 0
                ORDER BY seq ASC
                LIMIT ?
                """,
                (session_id, window_min_seq, bookend),
            ).fetchall()
            end_rows = self._conn.execute(
                f"""
                SELECT * FROM messages
                WHERE session_id = ? AND type IS NULL AND seq > ?
                  AND {role_clause} AND length(COALESCE(content, '')) > 0
                ORDER BY seq DESC
                LIMIT ?
                """,
                (session_id, window_max_seq, bookend),
            ).fetchall()

        start = [_row_to_dict(r) for r in start_rows]
        end = [_row_to_dict(r) for r in reversed(end_rows)]
        return {"bookend_start": start, "bookend_end": end}
