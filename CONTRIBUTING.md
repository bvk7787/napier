# Contributing

Thanks for looking. napier is a small project, kept in spare time, and answers are best effort.
Issues are for bugs, source requests and feature ideas. Everyone taking part is expected to follow
the [code of conduct](CODE_OF_CONDUCT.md). Report security problems privately, as
[SECURITY.md](SECURITY.md) says.

## Setup

```bash
git clone https://github.com/bvk7787/napier.git && cd napier
uv sync --extra dev                             # the versions in uv.lock; add --extra index for search
. .venv/bin/activate
pytest -q                                       # needs no network, models or manuals
ruff check src tests
mypy                                            # settings in pyproject.toml
```

Without uv: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`. CI also runs
`pytest --cov` with a coverage floor, a package build, and the CLI from an installed wheel.

The tests run against fixtures and the shipped YAML. `tests/test_data.py` checks that sources,
facts, specs and the module catalog stay consistent; `tests/test_examples.py` checks the example
rack; `tests/test_readme.py` checks that every command the docs show still parses.
`tests/conftest.py` clears every `NAPIER_*` variable, points `NAPIER_HOME` at a temp folder and
switches the private overlay off, so your own setup never changes a result.

[CLAUDE.md](CLAUDE.md) describes the layout and the rules the code keeps. Read it before a larger
change.

## The most useful contribution: sources and facts

Add the manual for gear you own:

```bash
napier source add https://maker.example/manual.pdf --id maker_module_manual --device maker_module \
    --title "Maker Module manual" --version "v1.2"     # fetches, pins, detects the page offset
napier ingest --source maker_module_manual
napier grep "a phrase you know is on page 12" --device maker_module   # does the cite say p. 12?
```

[docs/sources.md](docs/sources.md) covers kinds, formats and page offsets.

- **One fetch, politely.** `source add` checks robots.txt. Don't use `--ignore-robots` unless the
  publisher has told you it's fine, and say so in the pull request. No crawls, search-result
  scrapes, logins or paywalled documents.
- **Pin PDF manuals** (`sha256`, which `source add` writes for PDFs). Leave changelogs and product pages
  unpinned, cropped with `--start-at`/`--stop-at` so price or stock changes don't read as updates.
- **Forum threads** are `community` snapshots (`--no-check`), cited as opinions and workarounds.
- **Facts** say where they came from: `--status manual --source <id> --pages <printed page>`, in
  your own words. A fact you add with `q` and `anchors` becomes a search test; run
  `napier eval --device <id>` and say in the pull request what it scored.
- **Anchors are short quotations**, at most 25 words each, just enough to find the passage
  ([docs/data-policy.md](docs/data-policy.md); `tests/test_data.py` enforces the limit).
- **Confirmed on the hardware?** Say what you checked and on which firmware. That's what the
  `hardware` status means, so it's worth the detail.
- **Wrong facts stay in the ledger as `refuted`** (`napier facts verify <id> --refute --note "..."`).
- **Specs** (`specs/<module>.yaml`): power and jacks only from the manual, with the page and an exact
  anchor. Run `napier specs check <name>` with the manual fetched.
- **Catalog** (`catalog/modules.yaml`): map a module's slug to its napier device, role and tags.

## Before you start on code

Open an issue, or comment on an existing one, and wait for a maintainer's go-ahead before writing
code. That goes for pull requests that only add or reshape tests too. Pull requests without that
agreement may be closed. Sources and facts for gear you own don't need an issue first.

## What a pull request needs

- **Tests.** A behavior change comes with a test, and `pytest -q` and `ruff check src tests` pass.
- **No one's personal data.** Code, tests, docs and commit messages name no real person, rig or
  private rack. Fixtures use invented names and `example.test` URLs. Personal setups belong in an
  overlay (`local/`), which is never committed here.
- **Stable JSON.** `napier rack export` and the MCP tools are read by scripts and agents: new fields
  are fine, and existing names and fields stay.
- **Docs.** Update the README, CLAUDE.md or docs/ where the behavior they describe changed, and add
  a line to the changelog under Unreleased.

## Rack-source plug-ins

A plug-in for a rack-planning service or format lives in its own package, registered under the
`napier.rack_sources` entry-point group ([docs/rack.md](docs/rack.md)). We'll link to plug-ins that
are polite (robots.txt, honest user agent, one fetch per page per run) and respect the service's
terms. Plug-ins that log in to other people's accounts or scrape against a site's terms won't be
listed.

## Releases

A maintainer bumps `version` in `pyproject.toml` (the one place it's written), moves the
changelog's entries under the new version with the date, and pushes the tag `v<version>`. The
release workflow builds the package, checks it installs and runs, and publishes it to PyPI with
Trusted Publishing.
