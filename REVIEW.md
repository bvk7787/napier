# Reviewing napier changes

For anyone reviewing a pull request here, person or agent. That includes the fresh-context review
that runs on the diff before a pull request opens (`/code-review` or `/review`, or a subagent given
this file, plus `/security-review` for High-risk paths). [CLAUDE.md](CLAUDE.md) holds the conventions: flag any change that breaks one,
and any line in README.md, CLAUDE.md, CONTRIBUTING.md or docs/ that the change leaves out of date.

## What failure looks like

| Area | Paths | It fails when |
|---|---|---|
| Ledger | `facts/`, `sources.yaml`, `specs/`, `catalog/` | It lies: a claim its anchors don't back on the cited printed page, a public fact nobody can test, an unpinned manual, a wrong page offset, a spec value that isn't in the manual |
| Fetching | `src/napier/sources.py`, `htmlmd.py`, `auto.py`, `refresh.py`, `rack_sources.py` | It scrapes: robots.txt skipped, a dishonest user agent, more than one fetch per source per run, link following, anything behind a login |
| Overlay boundary | `src/napier/paths.py`, anything that writes files, tests and fixtures, commit messages | It leaks: overlay data, a real name, a rack URL or rig notes reach the public tree, a pull request or a commit |
| Interfaces | `rack export`, `mcp_server.py` | It breaks a consumer: a field renamed or removed, or a tool argument named `device` |
| Search | `search.py`, `store.py`, `text.py`, `parse.py`, `evaluate.py` | It misranks quietly: hit@3 under 90% on `napier eval`, or a citation that loses its printed page |
| Rack | `rack.py`, `scenarios.py`, `viewer.py` | It misplaces: a wrong row or HP, power summed wrong, a wishlist module shown as owned |
| Docs | README.md, CONTRIBUTING.md, `docs/` | It lies: a command that no longer parses, or behavior that changed |
| CI, release and tooling | `.github/`, `pyproject.toml`, `uv.lock`, `.claude/` | It ships unchecked: a check skipped, an action unpinned, a hook that does more than it says |

## Risk tiers

The change sets the tier, by the paths it touches, and the highest path wins. Who wrote it doesn't
move the tier.

- **Low:** docs, tests only, and new sources, facts and specs with `facts recheck`, `eval` and
  `specs check` passing. Merges once the required checks are green. `napier refresh --merge` is the
  one automated merge path, and it stays limited to `sources.yaml`, `facts/` and `specs/`, with
  the eval gate and tests passed locally and no questions written by the local model.
- **Medium:** CLI behavior, search and rack code, new commands. The maintainer reads the diff and
  the review's findings.
- **High:** fetching, the overlay boundary, the `rack export` and MCP shapes, CI and release
  workflows, `pyproject.toml` and `.claude/`. The maintainer reads every line, and the
  fresh-context review includes `/security-review`.

An agent's review posts findings; it never stands in for the maintainer on Medium or High. For an
agent-written pull request, the person who prompted it is its reviewer, as if they had written it.

## Findings

- Each finding names a file and line and says what goes wrong. A guess from a name isn't a finding.
- Tag each one **Important** (fix before merging), **Nit** (optional, three at most per review) or
  **Pre-existing** (the pull request didn't cause it: say so, and don't hold the pull request on it).
- Skip what ruff already checks, `uv.lock`, the generated example notes in `examples/notes/`, and
  changelog wording.
- Start the summary with the number of findings. With none, say "Nothing to fix."
- Every finding gets an answer: fixed, or its thread resolved with a reason. The `main` ruleset
  won't merge with an open thread.

## Keep reviews converging

- After three rounds, stop patching and question the approach.
- After the first round, review only the new diff.
- Flag the class of bug so every instance gets fixed, and don't repeat a finding already posted.
- When the same finding comes back across pull requests, fix it at the source: a test, a ruff
  rule, or a line in CLAUDE.md or here.

## When something gets through

A bug that ships gets a test that reproduces it, in the fix. The fix's pull request says which
check should have caught it, and when the answer is a review, this file gets the missing line.
