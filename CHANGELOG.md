# Changelog

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.3] - 2026-06-23

### Added

- **Skill tool** — load and activate skills on demand; `read` / `grep` / `glob` can access registered skill directories beyond the workspace.
- **Memory tool** — persistent memory under `~/.miniclaw/memory/`; `MEMORY.md` is auto-injected into the system prompt each session with byte/line budget tracking.
- **Session search** — SQLite-backed session records with FTS; `session_search` tool supports browse, discovery, and scroll over past conversations.
- **YAML skill frontmatter** — skills now parse YAML frontmatter via `pyyaml` (supports block/folded scalars and extended metadata keys).
- **Context compaction summaries** — compact boundary content is recorded in session events after auto-summarize.

### Changed

- Sessions and memory are **enabled by default** in `default_config.json`.
- Tool output limits apply to memory write operations; oversized reads return clear errors.

### Fixed

- Summary tail splitting preserves tool message / assistant pairing.
- Removed unused `sessions_enabled` parameter from session initialization paths.

## [0.1.2] - 2026-05-17

### Added

- Context management — micro-compaction and auto-summarize before LLM requests.
- Tool output limits — read file size/token caps, glob result cap, generic tool result truncation.

## [0.1.1] - 2026-04-12

### Added

- Plan mode, streaming output, TTFT metrics, cache hit rate monitoring.
- Configurable workspace directory (`-w` / `MINICLAW_WORKSPACE`).

## [0.1.0] - 2026-04-11

Initial PyPI release — CLI REPL with six workspace tools, skills system, and MiniMax default model.

[0.1.3]: https://github.com/sundl123/miniclaw/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/sundl123/miniclaw/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/sundl123/miniclaw/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/sundl123/miniclaw/releases/tag/v0.1.0
