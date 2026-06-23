"""RecordsWriter: JSONL + SQLite dual-write."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from miniclaw.config import get_local_iso_date
from miniclaw.sessions.config import SessionsConfig
from miniclaw.sessions.db import SessionDB
from miniclaw.sessions.paths import get_state_db_path, session_jsonl_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_session_id() -> str:
    return uuid.uuid4().hex[:8]


class RecordsWriter:
    """Append-only session recorder with JSONL + SQLite dual-write."""

    def __init__(
        self,
        config: SessionsConfig,
        db: SessionDB,
        *,
        session_id: str,
        jsonl_path: str,
        workspace: str,
        model: str,
    ):
        self._config = config
        self._db = db
        self.session_id = session_id
        self._jsonl_path = jsonl_path
        self._workspace = workspace
        self._model = model
        self._seq = 0

    @property
    def db(self) -> SessionDB:
        return self._db

    @classmethod
    def open(
        cls,
        config: SessionsConfig,
        *,
        workspace: str,
        model: str,
    ) -> RecordsWriter:
        session_id = generate_session_id()
        local_date = get_local_iso_date()
        jsonl_path = session_jsonl_path(session_id, local_date)
        db = SessionDB(get_state_db_path())
        started_at = _utc_now_iso()
        db.insert_session(
            session_id,
            started_at=started_at,
            workspace=workspace,
            model=model,
            jsonl_path=jsonl_path,
        )
        writer = cls(
            config, db,
            session_id=session_id,
            jsonl_path=jsonl_path,
            workspace=workspace,
            model=model,
        )
        writer.append_meta(
            "session_start",
            workspace=workspace,
            model=model,
            jsonl_path=jsonl_path,
        )
        return writer

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _cap_content(self, content: str | None) -> tuple[str | None, dict]:
        if content is None:
            return None, {}
        max_bytes = self._config.records_max_event_bytes
        encoded = content.encode("utf-8")
        if len(encoded) <= max_bytes:
            return content, {}
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return truncated, {"truncated": True, "original_bytes": len(encoded)}

    def _append_line(self, event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _write_event(self, event: dict) -> int:
        seq = event["seq"]
        role = event.get("role", "system")
        content = event.get("content")
        tool_calls = event.get("tool_calls")
        self._db.insert_message(
            self.session_id,
            seq,
            ts=event["ts"],
            role=role,
            content=content,
            tool_name=event.get("name") or event.get("tool_name"),
            tool_call_id=event.get("tool_call_id"),
            tool_calls=tool_calls,
            type=event.get("type"),
        )
        self._append_line(event)
        return seq

    def append_meta(self, type: str, **fields) -> int:
        seq = self._next_seq()
        event = {
            "ts": _utc_now_iso(),
            "session_id": self.session_id,
            "seq": seq,
            "type": type,
            "role": "system",
            **fields,
        }
        self._write_event(event)
        return seq

    def append_user(self, content: str) -> int:
        capped, extra = self._cap_content(content)
        seq = self._next_seq()
        event = {
            "ts": _utc_now_iso(),
            "session_id": self.session_id,
            "seq": seq,
            "role": "user",
            "content": capped,
            **extra,
        }
        return self._write_event(event)

    def append_assistant(self, message: dict) -> int:
        content = message.get("content") or ""
        capped, extra = self._cap_content(content if content else None)
        seq = self._next_seq()
        event: dict = {
            "ts": _utc_now_iso(),
            "session_id": self.session_id,
            "seq": seq,
            "role": "assistant",
            "content": capped or "",
            **extra,
        }
        tool_calls = message.get("tool_calls")
        if tool_calls:
            event["tool_calls"] = tool_calls
        reasoning = message.get("reasoning")
        if reasoning:
            event["reasoning"] = reasoning
        return self._write_event(event)

    def append_tool(
        self,
        *,
        tool_call_id: str,
        name: str,
        content: str,
    ) -> int:
        capped, extra = self._cap_content(content)
        seq = self._next_seq()
        event = {
            "ts": _utc_now_iso(),
            "session_id": self.session_id,
            "seq": seq,
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": capped,
            **extra,
        }
        return self._write_event(event)
