"""MemoryStore: frozen snapshot, live disk state, atomic writes."""
from __future__ import annotations

import os
import tempfile

from miniclaw.memory.budget import (
    BUDGET_HINTS,
    BudgetCheckResult,
    ContentMeasure,
    TruncationMeta,
    build_usage,
    budget_error_message,
    check_budget,
    truncate_for_prompt,
    usage_warning,
)
from miniclaw.memory.config import MEMORY_MD_FILENAME, MEMORY_MD_PLACEHOLDER, MemoryConfig
from miniclaw.memory.paths import (
    get_memory_dir,
    get_memory_md_path,
    is_memory_md_path,
    normalize_memory_rel_path,
    resolve_memory_path,
)
from miniclaw.memory.prompt import format_memory_system_block
from miniclaw.read_file import FileTooLargeError, read_file_lines
from miniclaw.tool_output import enforce_read_output_limits
from miniclaw.tools_config import ReadToolConfig


class MemoryStore:
    """One instance per session: frozen prompt snapshot + live disk operations."""

    def __init__(self, config: MemoryConfig):
        self._config = config
        self._prompt_snapshot: str = ""
        self._truncation_meta = TruncationMeta(
            truncated=False,
            total_bytes=0,
            total_lines=0,
            shown_bytes=0,
            shown_lines=0,
        )

    @property
    def config(self) -> MemoryConfig:
        return self._config

    @property
    def truncation_meta(self) -> TruncationMeta:
        return self._truncation_meta

    def ensure_layout(self) -> None:
        """Create memory dir and placeholder MEMORY.md if missing."""
        get_memory_dir()
        md_path = get_memory_md_path()
        if not os.path.isfile(md_path):
            self._atomic_write_path(md_path, MEMORY_MD_PLACEHOLDER)

    def load_snapshot(self) -> None:
        """Read MEMORY.md from disk, truncate if needed, freeze for system prompt."""
        self.ensure_layout()
        md_path = get_memory_md_path()
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            raw = ""

        snapshot, meta = truncate_for_prompt(raw, self._config)
        self._prompt_snapshot = snapshot
        self._truncation_meta = meta

    def format_for_system_prompt(self) -> str | None:
        """Return frozen block captured at load_snapshot(); unchanged mid-session."""
        return format_memory_system_block(
            self._prompt_snapshot,
            self._truncation_meta,
            self._config,
        )

    def _read_disk_memory_md(self) -> str:
        md_path = get_memory_md_path()
        if not os.path.isfile(md_path):
            return ""
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def memory_md_usage(self) -> dict:
        """Live usage from on-disk MEMORY.md (for tool responses)."""
        measure = ContentMeasure.from_text(self._read_disk_memory_md())
        return build_usage(measure, self._config).to_dict()

    def preflight_write_memory_md(self, new_content: str) -> BudgetCheckResult:
        return check_budget(new_content, self._config)

    @staticmethod
    def _atomic_write_path(abs_path: str, content: str) -> None:
        parent = os.path.dirname(abs_path)
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp", prefix=".mem_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, abs_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _failure_response(
        self,
        error: str,
        *,
        would_be: ContentMeasure | None = None,
        violations: tuple[str, ...] = (),
        extra: dict | None = None,
    ) -> dict:
        resp: dict = {
            "success": False,
            "error": error,
            "memory_md_usage": self.memory_md_usage(),
        }
        if would_be is not None:
            resp["would_be"] = {
                "bytes": would_be.used_bytes,
                "lines": would_be.used_lines,
            }
        if violations:
            resp["violations"] = list(violations)
            resp["limits"] = {
                "bytes": self._config.memory_md_max_bytes,
                "lines": self._config.memory_md_max_lines,
            }
            resp["hints"] = list(BUDGET_HINTS)
        if extra:
            resp.update(extra)
        return resp

    def _success_response(self, *, action: str, path: str, message: str, extra: dict | None = None) -> dict:
        measure = ContentMeasure.from_text(self._read_disk_memory_md())
        warning = usage_warning(measure, self._config)
        resp: dict = {
            "success": True,
            "action": action,
            "path": path,
            "message": message,
            "memory_md_usage": self.memory_md_usage(),
            "warning": warning,
        }
        if extra:
            resp.update(extra)
        return resp

    def write_file(self, rel_path: str, content: str) -> dict:
        norm = normalize_memory_rel_path(rel_path)
        abs_path = resolve_memory_path(norm)

        if is_memory_md_path(norm):
            check = check_budget(content, self._config)
            if not check.ok:
                return self._failure_response(
                    budget_error_message(check.measure, self._config, check.violations),
                    would_be=check.measure,
                    violations=check.violations,
                )

        self._atomic_write_path(abs_path, content)
        extra = None
        if not is_memory_md_path(norm):
            extra = {
                "topic_bytes": ContentMeasure.from_text(content).used_bytes,
                "note": "Topic files have no size limit.",
            }
        return self._success_response(
            action="write",
            path=norm,
            message=f"Updated {norm}",
            extra=extra,
        )

    def edit_file(self, rel_path: str, old_string: str, new_string: str) -> dict:
        norm = normalize_memory_rel_path(rel_path)
        abs_path = resolve_memory_path(norm)

        if not os.path.isfile(abs_path):
            return self._failure_response(f"File not found: {norm}")

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                current = f.read()
        except OSError as e:
            return self._failure_response(f"Failed to read {norm}: {e}")

        if old_string not in current:
            return self._failure_response(f"old_string not found in {norm}")

        count = current.count(old_string)
        if count > 1:
            return self._failure_response(
                f"old_string matched {count} times in {norm}; be more specific."
            )

        updated = current.replace(old_string, new_string, 1)

        if is_memory_md_path(norm):
            check = check_budget(updated, self._config)
            if not check.ok:
                return self._failure_response(
                    budget_error_message(check.measure, self._config, check.violations),
                    would_be=check.measure,
                    violations=check.violations,
                )

        self._atomic_write_path(abs_path, updated)
        extra = None
        if not is_memory_md_path(norm):
            extra = {
                "topic_bytes": ContentMeasure.from_text(updated).used_bytes,
                "note": "Topic files have no size limit.",
            }
        return self._success_response(
            action="edit",
            path=norm,
            message=f"Edited {norm}",
            extra=extra,
        )

    def read_file(
        self,
        rel_path: str,
        offset: int = 0,
        limit: int | None = None,
        *,
        read_cfg: ReadToolConfig | None = None,
    ) -> dict:
        norm = normalize_memory_rel_path(rel_path)
        abs_path = resolve_memory_path(norm)
        if not os.path.isfile(abs_path):
            return self._failure_response(f"File not found: {norm}")

        cfg = read_cfg or ReadToolConfig()
        try:
            result = read_file_lines(
                abs_path,
                offset=offset,
                limit=limit,
                max_file_bytes=cfg.max_file_bytes if limit is None else None,
            )
        except FileTooLargeError as e:
            return self._failure_response(str(e))
        except OSError as e:
            return self._failure_response(f"Failed to read {norm}: {e}")

        limited = enforce_read_output_limits(
            result.content,
            limit=limit,
            max_output_tokens=cfg.max_output_tokens,
        )
        if limited.error:
            return self._failure_response(limited.error)

        resp = self._success_response(
            action="read",
            path=norm,
            message=f"Read {norm}",
        )
        resp["content"] = limited.content
        resp["total_lines"] = result.total_lines
        if limited.truncated:
            resp["content_truncated"] = True
        return resp

    def list_files(
        self,
        rel_dir: str = "",
        recursive: bool = False,
        *,
        max_entries: int = 500,
    ) -> dict:
        norm_dir = ""
        if rel_dir:
            norm_dir = normalize_memory_rel_path(rel_dir)
            list_root = resolve_memory_path(norm_dir)
        else:
            list_root = get_memory_dir()

        if os.path.isfile(list_root):
            return self._failure_response(f"Not a directory: {rel_dir or '.'}")
        if not os.path.isdir(list_root):
            return self._failure_response(f"Directory not found: {rel_dir or '.'}")

        memory_root = get_memory_dir()
        entries: list[dict] = []

        if recursive:
            for dirpath, dirnames, filenames in os.walk(list_root):
                dirnames.sort()
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, memory_root).replace(os.sep, "/")
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    entries.append({"path": rel, "bytes": size})
        else:
            for name in sorted(os.listdir(list_root)):
                full = os.path.join(list_root, name)
                rel = os.path.relpath(full, memory_root).replace(os.sep, "/")
                kind = "dir" if os.path.isdir(full) else "file"
                size = os.path.getsize(full) if os.path.isfile(full) else None
                entries.append({"path": rel, "type": kind, "bytes": size})

        total = len(entries)
        if total > max_entries:
            shown = entries[:max_entries]
            message = f"Listed {len(shown)} of {total} entries"
        else:
            shown = entries
            message = f"Listed {total} entries"

        resp = self._success_response(
            action="list",
            path=norm_dir or ".",
            message=message,
        )
        resp["entries"] = shown
        if total > max_entries:
            resp["entries_truncated"] = True
            resp["total_entries"] = total
        return resp

    def delete_file(self, rel_path: str) -> dict:
        norm = normalize_memory_rel_path(rel_path)
        if is_memory_md_path(norm):
            return self._failure_response(
                "Deleting MEMORY.md is not allowed. Use edit to remove sections."
            )

        abs_path = resolve_memory_path(norm)
        if not os.path.isfile(abs_path):
            return self._failure_response(f"File not found: {norm}")

        try:
            os.unlink(abs_path)
        except OSError as e:
            return self._failure_response(f"Failed to delete {norm}: {e}")

        return self._success_response(
            action="delete",
            path=norm,
            message=f"Deleted {norm}",
        )

    def status(self) -> dict:
        live = self._read_disk_memory_md()
        live_measure = ContentMeasure.from_text(live)
        snap_measure = ContentMeasure.from_text(self._prompt_snapshot)
        resp = self._success_response(
            action="status",
            path=MEMORY_MD_FILENAME,
            message="Memory status",
        )
        resp["memory_dir"] = get_memory_dir()
        resp["disk_memory_md_usage"] = build_usage(live_measure, self._config).to_dict()
        resp["frozen_snapshot_usage"] = build_usage(snap_measure, self._config).to_dict()
        resp["truncation"] = {
            "truncated": self._truncation_meta.truncated,
            "total_bytes": self._truncation_meta.total_bytes,
            "total_lines": self._truncation_meta.total_lines,
            "shown_bytes": self._truncation_meta.shown_bytes,
            "shown_lines": self._truncation_meta.shown_lines,
        }
        return resp
