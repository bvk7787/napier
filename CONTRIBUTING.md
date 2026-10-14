# Contributing

Thanks for taking a look. napier is a small project kept up in spare time, so replies are best
effort. Issues are for bugs, source requests and feature ideas. Please follow the [code of
conduct](CODE_OF_CONDUCT.md), and report security problems privately as [SECURITY.md](SECURITY.md)
describes.

## Setup

```bash
git clone https://github.com/bvk7787/napier.git && cd napier
uv sync --extra dev                             # the versions in uv.lock; add --extra index for search
. .venv/bin/activate
pytest -q                                       # needs no network, models or manuals
ruff check src tests
mypy                                            # settings in pyproject.toml
```

Without uv: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`. CI also
enforces a coverage floor, builds the package and runs the CLI from an installed wheel.

The tests run against fixtures and the shipped YAML. `tests/test_data.py` checks that sources,
facts, specs and the module catalog stay consistent, `tests/test_examples.py` checks the example
rack, and `tests/test_readme.py` makes sure every command in the docs still parses.
`tests/conftest.py` clears the `NAPIER_*` variables, uses a temp folder for `NAPIER_HOME` and turns
the private overlay off, so your own setup can't change a result.

Read [CLAUDE.md](CLAUDE.md) before a larger change. It describes the layout and the rules the code
follows.

## Adding sources and facts

The most useful contribution is the manual for gear you own:

```bash
napier source add https://maker.example/manual.pdf --id maker_module_manual --device maker_module \
    --title "Maker Module manual" --version "v1.2" --public   # fetch, pin, find the page offset
napier ingest --source maker_module_manual
napier grep "a phrase you know is on page 12" --device maker_module   # does the cite say p. 12?
```

[docs/sources.md](docs/sources.md) covers kinds, formats and page offsets. A few ground rules:

- `source add` checks robots.txt. Only use `--ignore-robots` if the publisher has told you it's
  fine, and say so in the pull request. Crawls, search-result scrapes and anything behind a login or
  paywall don't belong here.
- PDF manuals get pinned (`source add` writes the sha256). Leave changelogs and product pages
  unpinned, and crop them with `--start-at` and `--stop-at` so a price or stock change doesn't look
  like an update.
- Forum threads are `community` snapshots (`--no-check`), cited as opinions and workarounds.
  They're searchable, but facts from them stay in your overlay, since a public fact quotes its
  source and forum posts aren't quoted.
- Every public fact can be tested. Write the claim in your own words, name its source, and give a
  question (`q`) and one or more anchors, short phrases copied from the passage that backs it up.
  A fact from a PDF also gives the printed page. Add these by hand in `facts/<device>.yaml` (without
  an overlay, `facts add` writes there), then run `napier facts recheck --device <id>` and
  `napier eval --device <id>`, and put the eval score in the pull request.
- Anchors are short quotations, 25 words at most, just enough to find the passage. See
  [docs/data-policy.md](docs/data-policy.md); `tests/test_data.py` enforces the limit.
- Hardware checks and open questions don't go in the public ledger. They're useful to you, but
  nobody else can test them, so keep them in your overlay.
- When a fact turns out wrong, mark it with `napier facts verify <id> --refute --note "..."` and
  anchor the passage that contradicts it. It stays in the ledger so nobody adds it again.
- Specs (`specs/<module>.yaml`) take power and jacks from the manual only, with the page and an
  exact anchor. Run `napier specs check <name>` with the manual fetched.
- The catalog (`catalog/modules.yaml`) maps a module's slug to its napier device, role and tags.

## Before you start on code

Open an issue, or comment on an existing one, and wait for a maintainer to agree before you write
code. That includes pull requests that only add or reorganize tests. Pull requests that skip this
step may be closed. Sources and facts for gear you own don't need an issue.

## What a pull request needs

- A behavior change comes with a test, and `pytest -q` and `ruff check src tests` pass.
- No personal data. Code, tests, docs and commit messages shouldn't name a real person, rig or
  private rack. Fixtures use made-up names and `example.test` URLs, and personal setups go in an
  overlay (`local/`), which is never committed here.
- `napier rack export` and the MCP tools are read by scripts and agents. You can add fields, but
  existing fields keep their names and stay in the output.
- Update the README, CLAUDE.md or docs/ when the behavior they describe changes, and add a line to
  the changelog under Unreleased.

## Rack-source plug-ins

A plug-in for a rack-planning service or file format lives in its own package, registered under the
`napier.rack_sources` entry point ([docs/rack.md](docs/rack.md)). We'll link to plug-ins that fetch
politely (robots.txt, an honest user agent, one fetch per page per run) and follow the service's
terms. Plug-ins that log in to other people's accounts or scrape against a site's terms won't be
listed.

## Releases

A maintainer bumps `version` in `pyproject.toml`, the only place it's written, and runs `uv lock`
(CI installs with `uv sync --locked` and fails on a stale lock). Then they move the changelog's
Unreleased entries under the new version with today's date and push the tag `v<version>`. The
release workflow builds the package, checks that it installs and runs, and publishes it to PyPI with
Trusted Publishing.
