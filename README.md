# napier

Page-cited answers from your music gear's manuals, for you and your AI assistant.

Ask an assistant how to cue a song row on the M8 and you get a confident answer with no source.
napier keeps the makers' manuals, firmware changelogs and a few forum write-ups on your machine, and
every hit names the document, its version and the page number printed on the page. It's a
command-line tool and an MCP server, so Claude and other assistants run the same lookup and quote
the page.

```
$ napier grep "cue the" --device m8_tracker -C 0
m8_tracker_manual p. 11
  > • [LEFT]+[PLAY] Cue the selected song row for playback.
m8_tracker_tips § Live Mode Shortcuts
  > * Hold Left and press Play to cue the whole row(Similarly smaller selections work also.)
```

The first hit is the M8 Operation Manual v6.5.2, page 11. The second is the community tips document,
labeled as such.

[![CI](https://github.com/bvk7787/napier/actions/workflows/ci.yml/badge.svg)](https://github.com/bvk7787/napier/actions/workflows/ci.yml)
![Python 3.11 | 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/bvk7787/napier/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/napier)](https://pypi.org/project/napier/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/bvk7787/napier/badge)](https://scorecard.dev/viewer/?uri=github.com/bvk7787/napier)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)

**Who it's for:** people with synths, grooveboxes and Eurorack who are comfortable with a terminal
and git. It ships with sources for 101 devices: mostly Eurorack, plus the Dirtywave M8, Elektron
Digitakt II, OXI One MKII and a set of Strymon and other effects pedals. Adding your own takes one
command. Exact lookups install in seconds; meaning-based search needs a few GB of libraries and
models.

## Try it

You need git and [uv](https://docs.astral.sh/uv/) (`brew install uv`, or
`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone https://github.com/bvk7787/napier && cd napier
uv tool install -e .                       # the CLI, without the search models

napier fetch --device m8_tracker           # the M8 manual, changelog and community tips
napier ingest --text-only --device m8_tracker
napier grep "cue the" --device m8_tracker
napier read m8_tracker --page 11           # the whole printed page
napier facts list --device m8_tracker      # what's been checked, and how far
```

That downloads three files, about 20 seconds with napier's 2-second spacing between requests to a
site. If your shell can't find `napier` afterwards, run `uv tool update-shell` and open a new
terminal. napier runs from its clone because the sources, facts and specs are data you read and
edit there, and `-e` keeps the installed command pointing at it. It isn't installable from PyPI on
its own.

Without uv: `python3 -m venv .venv && .venv/bin/pip install -e .` (Python 3.11 or later), then use
`.venv/bin/napier`.

## Add search and your assistant

Meaning-based search ("how do I stop the delay feeding back") needs the `index` extra, and the MCP
server needs `mcp`. List every extra you want each time you install, because a reinstall with fewer
drops the others:

```bash
uv tool install -e ".[index,mcp]"
napier fetch --device m8_tracker && napier ingest --device m8_tracker
napier search "how do I cue a song row" --device m8_tracker
```

The first `ingest` downloads the embedding and layout models from Hugging Face, and the first
`search` the reranker: about 4.7 GB in all, once. `napier fetch --all` gets every source (about 150
documents, 350 MB, a few minutes at one request every 2 seconds per site).

Then connect your assistant. For Claude Code:

```bash
claude mcp add --scope user napier -- "$(which napier)" mcp
```

[docs/mcp.md](https://github.com/bvk7787/napier/blob/main/docs/mcp.md) has the configs for Claude Desktop, Cursor, VS Code, Codex and Windsurf,
the tool list, and what a lookup looks like from the assistant's side.

## What it does

- **Exact lookups** (`grep`, `read`) for button combos, parameter names and whole sections or
  pages. No AI model involved; a lookup takes well under a second.
- **Meaning-based search** (`search`) for open questions. It combines keyword and vector search,
  then reranks, and every hit cites title, version and printed page.
- **Source kinds kept apart.** Manuals, changelogs, community write-ups, pinned firmware source and
  your own notes are labeled in every result and can be filtered, so a forum workaround never
  passes for the manual.
- **A ledger of checked facts.** Each claim records where it came from and how far it's been
  checked: in the manual, in a changelog, reported by the community, or confirmed on the hardware.
  A claim that turns out wrong is kept as `refuted`, so nobody repeats it.
- **A regression test for search.** 681 facts carry a question and the phrases that answer it.
  `napier eval` asks each one and fails below 90% with the answer in the top three. On 2026-10-13
  all 681 found their answer in the top three, 80% ranked it first, and every one with a cited page
  (549) found it on that page. The questions were written by people who knew the answer, so it
  guards against regressions on them.
- **Change tracking.** `napier source check` re-downloads each source once and reports which
  changed; after you apply an update, `napier facts recheck` lists the facts whose quoted text
  moved or vanished, so you can re-check them.
- **A Eurorack rack planner**: what's racked, power per case against your supply, and what-if
  layouts checked before you move anything ([Your rack](#your-rack)).

## Why not NotebookLM, or hand the PDF to an assistant?

Both answer questions about a document in front of them. What napier adds:

| | Upload-and-ask tools | napier |
|---|---|---|
| Exact strings like `[SHIFT]+[PLAY]` | Usually found, in a way you can't inspect | `grep` is exact and repeatable; `search` handles open questions |
| Citations | A link to a passage in your upload | The page number printed in the manual, with title and version |
| Firmware and manual updates | You notice and re-upload | `source check` finds changed documents; `facts recheck` lists the facts to re-check |
| Is the answer right? | You judge each answer | A ledger of checked facts, and an eval that fails when search regresses |
| Forum workarounds | Weighted like anything else | Kept as `community`, labeled apart from the manual |
| 150 documents | Whatever you've added to that notebook | One store; every device at once, or one with `--device` |
| What you've checked | Lives in that chat | In the ledger, shared by every assistant you connect |

napier is a local store: nothing leaves your machine unless an assistant you connected asks for it,
and then the passages it returns go to that assistant like anything else you paste in.

## What's in it

149 sources for 101 devices: 113 manuals, 21 changelogs, 10 pinned firmware sources and 5 community
documents. Dirtywave M8, Elektron Digitakt II, OXI One MKII, Intellijel, Instruō, Make Noise, ALM,
Steady State Fate, Noise Engineering, Strymon, Squarp, WMD, Joranalogue, Erica Synths and more;
`napier source list` shows them all. The ledger holds 713 facts: 624 stated in a manual, 50 in a
changelog, 15 from the community, 6 from firmware source, 2 confirmed on hardware and 16 open
questions. 88 modules have spec files: 77 with manual-cited power draw, 80 with their jacks.

## Add your own gear

```bash
mkdir -p local                             # your private overlay (below)
napier source add https://maker.example/module-manual.pdf --id maker_module_manual \
    --device maker_module --version "v1.2" --local
napier ingest --source maker_module_manual
napier facts add maker_module "Holding SHIFT at power-up resets calibration" --status manual \
    --source maker_module_manual --pages 12
```

`source add` checks robots.txt and downloads the file; for a PDF it also pins it by sha256 and
detects the printed-page offset, so check the offset it prints. `--local` keeps the entry in your
overlay, and facts for a device only your overlay knows are written there too. Gear anyone could own
is worth a pull request to the public list instead ([CONTRIBUTING.md](https://github.com/bvk7787/napier/blob/main/CONTRIBUTING.md)).
[docs/sources.md](https://github.com/bvk7787/napier/blob/main/docs/sources.md) covers kinds, formats, page offsets, sites that don't allow
automated downloads, and keeping sources current.

## The facts ledger

| status | meaning |
|---|---|
| `manual` | stated in the manual (source and printed pages) |
| `changelog` | stated in a firmware changelog or release notes |
| `community` | reported by a forum, doc or video; cites the URL |
| `code` | read from firmware source pinned to one commit |
| `hardware` | confirmed on the device, the strongest status |
| `unverified` | an open question, or a claim with no source yet |
| `refuted` | checked and found wrong |

`napier facts verify ID --hardware --note "..."` records a check on the device, and `--refute`
marks a claim wrong. A fact with a question and anchors (short phrases quoted from its page) is
also a search test. Facts written by an assistant over MCP are stamped `via: mcp` so you can review
them in the diff.

## Your rack

For Eurorack: keep your rack as YAML next to the manuals, with what each module is for, power per
case against your supply, and what-if layouts that `napier rack scenarios` checks for overlaps, case
seams, power, and modules that ended up far from their partners. `napier rack view --open` draws it
all as one HTML page that loads nothing from the network.

![The example rack with a what-if layout: Step 8 replaces Beads, power per rail, one module leaving](https://github.com/bvk7787/napier/raw/main/docs/images/example-scenario.png)

Try it on the example rack with `napier rack view --open`. [docs/rack.md](https://github.com/bvk7787/napier/blob/main/docs/rack.md) shows how
to start your own and how to write a plug-in that reads a rack from somewhere else.

## Your own data

Anything personal lives in a private **overlay**, `local/` inside your clone, which git ignores and
which can be its own private repository. Its `sources.yaml` and `facts/` merge with the public ones
(your notes list first), and it holds your rack, your notes and a `napier.toml` with your name for
generated pages. `source add --local` writes there, and so does `facts add` for a device whose file
lives there. Nothing in it is ever committed to the public repository.

## Updating

```bash
cd /path/to/napier && git pull
uv tool install -e ".[index,mcp]"          # the same extras you use; picks up new dependencies
napier fetch --device m8_tracker           # anything new or re-pinned for your devices
napier ingest --device m8_tracker
```

Restart your assistant app afterwards so it starts the new server. `napier status` shows what's
downloaded, extracted and indexed for each device.

## Uninstall

```bash
uv tool uninstall napier
rm -rf ~/.napier                           # downloads, text layer, index, reports
```

Also, if you used them:

- the clone. Your overlay is `local/` inside it, so copy anything you want to keep first;
- the search models in `~/.cache/huggingface/hub`: the `models--*` folders for the two models in
  [docs/how-it-works.md](https://github.com/bvk7787/napier/blob/main/docs/how-it-works.md#search) and Docling's layout models. `uv cache clean`
  clears uv's download cache;
- the `napier` entry in your assistant's MCP config (`claude mcp remove napier` for Claude Code);
- any scheduled `napier refresh`.

## FAQ

**Is my gear covered?** `napier source list` shows every device, or browse
[sources.yaml](https://github.com/bvk7787/napier/blob/main/sources.yaml). If yours isn't, `napier source add` takes one command, and a
[source request](https://github.com/bvk7787/napier/issues/new?template=source_request.yml) works
too.

**Can I `pip install napier`?** The PyPI package only points you here: napier needs its data files,
which live in the clone.

**Does anything get uploaded?** No. napier downloads the documents in its lists and the search
models, and sends nothing anywhere. An assistant you connect sees what its lookups return.

**Do I need a GPU?** No. Search runs on a laptop CPU, faster on Apple Silicon or with CUDA.

**Windows?** Untested. macOS and Linux are what CI runs.

**Why are some manuals "not downloaded"?** A few sites' robots.txt disallows automated downloads,
and napier respects that. `napier fetch` prints the URL; download it in a browser and run
`napier fetch --source ID --from FILE`.

**Is it OK to quote manuals in facts?** The repository holds links, checksums and short quoted
phrases, and each user downloads the documents from their publishers. The
[data policy](https://github.com/bvk7787/napier/blob/main/docs/data-policy.md) has the details, and how publishers can ask for changes.

## Limitations

- **`grep` needs a text layer.** A scanned manual with no text layer reaches `read` and `search`
  only through Docling's OCR (with the `index` extra), and its printed pages can't be detected.
- **One page offset per document.** Manuals that restart numbering per chapter (3-12) or mix roman
  and arabic numerals cite the right page only in the main numbered run.
- **Grep is literal.** It's case-insensitive substring matching, so `mA` also finds "Manual" (use
  `--case` or `--regex`), and brackets matter: `LEFT+PLAY` won't find `[LEFT]+[PLAY]`.
- **New manuals under new file names** aren't detected by `source check`; it sees changes at the
  same URL. Check the maker's page when a firmware comes out.
- **The source list follows its contributors' gear** until more people add theirs.

## Safety and trust

napier downloads only the URLs in its lists, politely: robots.txt first, an honest user agent, at
least 2 seconds between requests to a site, backoff when a site asks, no crawling and no logins.
It opens no port, sends no telemetry, and writes only to `~/.napier`, the Hugging Face cache, the
YAML and generated notes in your clone and overlay, and any path you give `--out`. Passages from
manuals and forums go to your assistant marked as document content; the MCP server tells it not to
act on instructions inside them, and the only tools that write change fact files you review in git. [docs/how-it-works.md](https://github.com/bvk7787/napier/blob/main/docs/how-it-works.md)
has the details and [SECURITY.md](https://github.com/bvk7787/napier/blob/main/SECURITY.md) how to report a problem.

Provided as is, under Apache-2.0, without warranty. When a fact matters (calibration, firmware
updates, anything that can brick a module), follow the manual page it cites.

## Requirements

- **macOS or Linux**, Python 3.11 or later (uv brings one).
- **Disk.** The base install is small. The `index` extra pulls in PyTorch through
  sentence-transformers and Docling: about 1.5 GB on macOS, and several GB on Linux, where PyTorch's
  default wheels include the CUDA libraries. The models add about 4.7 GB in the Hugging Face cache.
  All sources take about 350 MB in `~/.napier/files`, and the index and parse cache about 300 MB
  more.
- **Time.** Parsing and indexing every source the first time takes a while on a laptop; later
  ingests only redo what changed.

## Maintainers: keeping the public list current

`napier refresh` runs the update pass unattended: source check, rack sync, apply, ingest, recheck,
specs check, eval and tests, then a pull request for the public changes with what changed and what
needs a human. It can use a local [Ollama](https://ollama.com) model to reword questions whose
source changed. Changes to your overlay are committed and pushed straight to the overlay's own
repository. It's for maintainers and forks: it needs a clean git clone on `main` (and a clean
overlay), the `index` extra and pytest, plus the GitHub CLI and push access to `origin` unless you
pass `--no-push`. If you only use napier, `git pull` gets you the maintainers' updates.

## Contributing and license

Issues and pull requests are welcome, especially sources and facts for gear you own. See
[CONTRIBUTING.md](https://github.com/bvk7787/napier/blob/main/CONTRIBUTING.md), the [code of conduct](https://github.com/bvk7787/napier/blob/main/CODE_OF_CONDUCT.md), [SUPPORT.md](https://github.com/bvk7787/napier/blob/main/SUPPORT.md)
for questions, and the [changelog](https://github.com/bvk7787/napier/blob/main/CHANGELOG.md).

Copyright 2026 the napier authors. Code and contributors' text are Apache-2.0 ([LICENSE](https://github.com/bvk7787/napier/blob/main/LICENSE),
[NOTICE](https://github.com/bvk7787/napier/blob/main/NOTICE)); quoted anchors stay their publishers' ([data policy](https://github.com/bvk7787/napier/blob/main/docs/data-policy.md));
third-party terms are in [THIRD_PARTY_NOTICES.md](https://github.com/bvk7787/napier/blob/main/THIRD_PARTY_NOTICES.md).

Named for John Napier, whose tables of logarithms turned a hard calculation into a lookup.

Dirtywave, M8, Elektron, Digitakt, OXI, Intellijel, Instruō, Make Noise, ALM, Steady State Fate,
Noise Engineering, Strymon, Squarp, WMD, Joranalogue, Erica Synths, ModularGrid, NotebookLM and the
other product and company names here are trademarks of their owners. napier is an independent
project, not affiliated with or endorsed by any of them.
