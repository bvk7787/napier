# Changelog

All notable changes to napier are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) (before 1.0, a minor version may change
the CLI or the data formats).

## [Unreleased]

### Changed

- `napier refresh --merge` queues a squash merge that lands once CI passes, matching the
  repository's merge rules.

## [0.1.0] - 2026-10-13

First public release.

### Added

- Sources: manuals, firmware changelogs, forum snapshots, pinned firmware source and your own notes,
  with printed-page offsets detected from the page footers. 149 sources for 101 devices ship with it.
- `grep` and `read` over a text layer (one unit per printed page or section), and hybrid `search`
  (vectors and BM25, fused, reranked) with pinned model revisions. Every result cites title,
  version and printed page, and says which kind of source it came from.
- The facts ledger (`manual`, `changelog`, `community`, `code`, `hardware`, `unverified`,
  `refuted`) and `napier eval`, which fails below 90% hit@3.
- `source check`, `source apply` and `facts recheck` for keeping sources current, and
  `napier refresh`, an unattended pass for maintainers that opens a pull request.
- An MCP server (`napier mcp`) with `status`, `search`, `grep`, `read`, `facts`, `add_fact`,
  `verify_fact` and `rack`. Errors reach the assistant with their reason; `grep` and `search` list
  the sources they couldn't search yet; facts it writes are stamped `via: mcp`.
- A Eurorack rack planner: rack sources (built-in `file`, plug-ins under `napier.rack_sources`),
  configurable case geometry, usage notes, what-if scenarios with power, distance and free-space
  checks, manual-cited specs, and `rack view`.
- A private overlay (`local/`) for your own sources, facts, rack and notes, merged at run time and
  never committed to the public repository.
- Polite fetching on every request: robots.txt per RFC 9309 (including `Crawl-delay` and
  redirects), at least 2 seconds between requests to a site, backoff on 429 and 503, an honest user
  agent. `fetch --from FILE` for documents a site doesn't allow napier to download.
- Limits on what a source list or document can do: plain-name ids, http(s) only, no private or local
  addresses, a 300 MB and 10-minute cap per download, and a guard against runaway regexes.
- `napier status` summarizes per device (`--wide` for every source); unknown device or source ids
  suggest the closest names.
- docs: MCP setup for Claude Desktop, Claude Code, Cursor, VS Code, Codex and Windsurf; sources;
  how it works; the rack planner; the data policy and a publisher request form.

[Unreleased]: https://github.com/bvk7787/napier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bvk7787/napier/releases/tag/v0.1.0
