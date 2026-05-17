"""Line-oriented file reading with size limits."""
from __future__ import annotations

import os
from dataclasses import dataclass

from miniclaw.tool_output import format_file_size


@dataclass
class ReadFileResult:
    content: str
    line_count: int
    total_lines: int
    start_line: int  # 1-based line number of first returned line


class FileTooLargeError(Exception):
    def __init__(self, size_in_bytes: int, max_size_bytes: int) -> None:
        self.size_in_bytes = size_in_bytes
        self.max_size_bytes = max_size_bytes
        super().__init__(
            f"File ({format_file_size(size_in_bytes)}) exceeds maximum allowed size "
            f"({format_file_size(max_size_bytes)}). Use offset and limit (0-based) "
            f"to read specific portions of the file."
        )


def read_file_lines(
    abs_path: str,
    offset: int = 0,
    limit: int | None = None,
    *,
    max_file_bytes: int | None = None,
) -> ReadFileResult:
    """Read a slice of lines from a text file without loading the whole file when limited."""
    if offset < 0:
        offset = 0

    st = os.stat(abs_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path)

    if limit is None and max_file_bytes is not None and st.st_size > max_file_bytes:
        raise FileTooLargeError(st.st_size, max_file_bytes)

    end_line = offset + limit if limit is not None else None
    numbered: list[str] = []
    total_lines = 0

    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f):
            total_lines = line_no + 1
            if line_no < offset:
                continue
            if end_line is not None and line_no >= end_line:
                break
            numbered.append(f"{line_no + 1:6d}|{line}")

    if not numbered and total_lines == 0:
        return ReadFileResult(
            content="(空文件)",
            line_count=0,
            total_lines=0,
            start_line=offset + 1 if offset == 0 else offset + 1,
        )

    if not numbered and offset >= total_lines and total_lines > 0:
        return ReadFileResult(
            content=(
                f"<system-reminder>Warning: offset ({offset}) is beyond end of file "
                f"({total_lines} lines).</system-reminder>"
            ),
            line_count=0,
            total_lines=total_lines,
            start_line=offset + 1,
        )

    start_line = offset + 1 if numbered else offset + 1
    return ReadFileResult(
        content="".join(numbered),
        line_count=len(numbered),
        total_lines=total_lines,
        start_line=start_line,
    )
