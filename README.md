# napier

Your gear's manuals and your Eurorack rack, in one place you and your AI assistant can work from.

[![CI](https://github.com/bvk7787/napier/actions/workflows/ci.yml/badge.svg)](https://github.com/bvk7787/napier/actions/workflows/ci.yml)
![Python 3.11 | 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/bvk7787/napier/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/napier)](https://pypi.org/project/napier/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/bvk7787/napier/badge)](https://scorecard.dev/viewer/?uri=github.com/bvk7787/napier)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)

## Look it up

napier keeps the manuals, firmware changelogs and a few community docs for your gear on your
machine. Every answer tells you the document, its version and the page number printed on the page.

```
$ napier grep "cue the" --device m8_tracker -C 0
m8_tracker_manual p. 11
  > • [LEFT]+[PLAY] Cue the selected song row for playback.
m8_tracker_tips § Live Mode Shortcuts
  > * Hold Left and press Play to cue the whole row(Similarly smaller selections work also.)
```

The first hit is page 11 of the M8 Operation Manual (v6.5.2). The second comes from the community
tips doc and is labeled that way.

## Plan the rack

Keep your Eurorack rack as YAML next to the manuals: what's in each case, what each module is for
and how much power each case can supply. Sketch what-if layouts, and napier checks each one for HP,
power per rail, case seams and modules that ended up far from the ones they pair with, then draws it
next to the rack you have.

![The example rack with Step 8 in place of Beads: one case, power per rail, Step 8 highlighted as new and Beads listed as leaving](https://github.com/bvk7787/napier/raw/main/docs/images/example-scenario.png)

That's the example rack with Step 8 in place of Beads. The -12V rail goes from 89% to 92% of the
supply, nothing overlaps, and Beads is listed as leaving. Power draw and jack lists come from the
manuals, with the page they're on.

## With an assistant

napier is also an MCP server, so Claude and other assistants can use both halves. Ask how to cue a
song row and it quotes page 11. Ask what in your rack takes a clock and it lists the matching jacks
from the manuals. Ask whether Step 8 should replace Beads and it can read what each module is for
and what you decided last time, propose a layout as a scenario file, and let napier check and draw
it before you move anything.

It's built for people with synths, grooveboxes and Eurorack who don't mind a terminal and git. The
source list covers 100+ devices: mostly Eurorack, plus the Dirtywave M8, Elektron Digitakt II, OXI
One MKII and a handful of Strymon and other pedals. Adding a manual for anything else takes one
command.

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

napier rack view --open                    # the example rack and its what-if layout, in your browser
napier rack scenarios                      # the checks behind it
```

The fetch downloads three files and takes 10 to 20 seconds. The rack commands need no downloads. If
your shell can't find `napier`, run `uv tool update-shell` and open a new terminal.

napier runs from its clone. The sources, facts and specs are files in the repo, and `-e` keeps the
installed command pointed at them.

Without uv: `python3 -m venv .venv && .venv/bin/pip install -e .` with Python 3.11 or later, then
run `.venv/bin/napier`.

## Add search and the MCP server

For questions in your own words ("how do I stop the delay feeding back"), install the `index` extra.
The MCP server needs the `mcp` extra. A reinstall replaces the previous one, so list every extra you
want each time:

```bash
uv tool install -e ".[index,mcp]"
napier fetch --device m8_tracker && napier ingest --device m8_tracker
napier search "how do I cue a song row" --device m8_tracker
```

The first `ingest` downloads the embedding and layout models from Hugging Face, and the first
`search` downloads the reranker. That's about 4.7 GB, once. `napier fetch --all` gets every source:
about 150 documents and 350 MB, which takes a few minutes.

To connect Claude Code:

```bash
claude mcp add --scope user napier -- "$(which napier)" mcp
```

[docs/mcp.md](https://github.com/bvk7787/napier/blob/main/docs/mcp.md) has the setup for Claude
Desktop, Cursor, VS Code, Codex and Windsurf, and shows what a lookup looks like from the
assistant's side.

## What you get

For looking things up:

- `grep` and `read` find exact text, like button combos and parameter names, and return whole pages
  or sections. There's no model involved, and a lookup takes a fraction of a second.
- `search` handles open questions. It combines keyword and vector search, reranks the results, and
  cites title, version and printed page for each hit.
- Every result is labeled with its kind of source (manual, changelog, community doc, firmware source
  or your own notes), and you can filter on it.
- The [facts ledger](#the-facts-ledger) records claims with where they came from and how far they've
  been checked. A claim that turns out wrong stays in the ledger marked `refuted`.
- `napier eval` tests search against the ledger. Every public fact carries a question and anchors,
  short phrases quoted from the page that answers it. The eval fails if fewer than 90% of the
  questions find their answer in the top three results. On 2026-10-13 all 686 did, 80% ranked it
  first, and all 550 with a cited page found it on that page. The questions were written by people who knew the
  answers, so treat this as a regression test.
- `napier source check` re-downloads each source and reports what changed. After you apply an
  update, `napier facts recheck` lists the facts whose quoted text moved or disappeared.

For your rack:

- `napier rack view --open` draws the rack and every what-if layout as one HTML page that works
  offline. You can switch between layouts, highlight what changed, find a module, and see power per
  rail for each case.
- `napier rack scenarios` checks the rack and each layout for overlaps, modules crossing a case
  seam, 1U modules in 3U rows, power per case against its supply, partner modules more than 20 cm
  apart, and free space split into slivers.
- Power draw and jack lists come from the manuals (`specs/`, with the page), and `napier rack check`
  shows where your rack's power figures disagree with the manual.
- `usage.yaml` records what each module is for and your placement rules. `challenges.yaml` logs each
  suggested change and what you decided, so a rejected idea doesn't keep coming back.
- Cases can have any mix of 1U and 3U rows, and several cases can sit in a grid. The rack itself
  comes from a file you write or, through a plug-in, from another tool.

## Compared with NotebookLM or pasting the PDF

Those work well for questions about one document.

| | Upload-and-ask tools | napier |
|---|---|---|
| Exact strings like `[SHIFT]+[PLAY]` | Usually found, but you can't see how | `grep` matches exactly, every time |
| Citations | A link into your upload | The printed page number, with title and version |
| Firmware updates | You notice and re-upload | `source check` finds changed documents, `facts recheck` the affected facts |
| Checking answers | Up to you, each time | A ledger of checked facts and an eval that catches regressions |
| Forum tips | Mixed in with everything else | Labeled `community` and filterable |

Nothing leaves your machine except the passages a connected assistant asks for, which go to that
assistant like anything else you paste into it.

## What's in it

About 150 sources covering 100 devices. That includes the Dirtywave M8, Elektron Digitakt II, OXI
One MKII and modules from Intellijel, Instruō, Make Noise, ALM, Steady State Fate, Noise
Engineering, Squarp, WMD, Joranalogue and Erica Synths, plus Strymon and a few other pedals. Most
facts come straight from a manual, with the printed page, and the rest from changelogs, community
docs and firmware source. Each one quotes a few words from its source, so napier can check that the
source still says it.
`napier source list`, `napier status` and `napier facts list` show what's there today.

## Add your own gear

```bash
mkdir -p local                             # your private overlay (see below)
napier source add https://maker.example/module-manual.pdf --id maker_module_manual \
    --device maker_module --version "v1.2" --local
napier ingest --source maker_module_manual
napier facts add maker_module "Holding SHIFT at power-up resets calibration" --status manual \
    --source maker_module_manual --pages 12
```

`source add` checks robots.txt and downloads the file. For a PDF it also pins the checksum and works
out the printed-page offset, which is worth checking against a page you know. `--local` puts the
entry in your private overlay. Once you have an overlay, `facts add` writes there too.

For gear other people are likely to own too, send a pull request to the public list instead
([CONTRIBUTING.md](https://github.com/bvk7787/napier/blob/main/CONTRIBUTING.md)).
[docs/sources.md](https://github.com/bvk7787/napier/blob/main/docs/sources.md) covers formats, page
offsets, sites that don't allow automated downloads and keeping sources current.

## The facts ledger

| status | meaning |
|---|---|
| `manual` | stated in the manual (source and printed pages) |
| `changelog` | stated in a firmware changelog or release notes |
| `community` | reported in a forum post, doc or video; cites the URL |
| `code` | read from firmware source pinned to one commit |
| `hardware` | confirmed on the device, the strongest status |
| `unverified` | an open question, or a claim with no source yet |
| `refuted` | checked and found wrong |

The public ledger holds the first four kinds, plus `refuted`. Every fact in it quotes an anchor, a
short phrase from its source on the cited page, so `napier facts recheck` can test it. What you
confirm on your own gear, and questions you haven't settled, go in your overlay with
`napier facts add DEVICE "..." --status hardware --notes "..."`. Settle one of your open questions
with `napier facts verify ID --hardware --note "..."`, or mark a claim wrong with `--refute`. Facts
an assistant writes over MCP get a `via: mcp` stamp, which makes them easy to spot in the diff.

## Your rack

The rack commands show the example rack until you set up your own:

```bash
mkdir -p local && cp -r examples/racks local/racks
$EDITOR local/racks/layout.yaml            # your modules: slug, HP, power, position ("row 2, hp 43")
$EDITOR local/racks/devices.yaml           # your cases: rows, how they're arranged, off-rack modules
napier rack sync                           # writes the snapshot; reports moves and overlaps
napier rack view --open
```

Then describe what each module is for in `usage.yaml`, and write what-if layouts in `scenarios/`, by
hand or with your assistant.
[docs/rack.md](https://github.com/bvk7787/napier/blob/main/docs/rack.md) covers the file formats and
how to write a plug-in that reads your rack from another tool.

## Your own data

Anything personal goes in `local/`, a private overlay inside your clone. Git ignores it, and it can
be its own private repo. Its `sources.yaml` and `facts/` merge with the public ones, with yours
listed first. It also holds your rack, your notes and a `napier.toml` with your name.
`source add --local` writes there, and so does `facts add`. Nothing in `local/` gets committed to
the public repo.

## Updating

```bash
cd /path/to/napier && git pull
uv tool install -e ".[index,mcp]"          # the extras you use; picks up new dependencies
napier fetch --device m8_tracker           # anything new or re-pinned for your devices
napier ingest --device m8_tracker
```

Restart your assistant app afterwards so it runs the new version. `napier status` shows what's
downloaded, extracted and indexed for each device.

## Uninstall

```bash
uv tool uninstall napier
rm -rf ~/.napier                           # downloads, text layer, index, reports
```

If you used them, also remove:

- the clone, after copying anything you want to keep from `local/`
- the models in `~/.cache/huggingface/hub`: the `models--*` folders for the models in
  [docs/how-it-works.md](https://github.com/bvk7787/napier/blob/main/docs/how-it-works.md#search)
  and Docling's layout models (`uv cache clean` clears uv's own download cache)
- the `napier` entry in your assistant's MCP config (`claude mcp remove napier` for Claude Code)
- any scheduled `napier refresh`

## FAQ

**Is my gear covered?** Run `napier source list`, or look through
[sources.yaml](https://github.com/bvk7787/napier/blob/main/sources.yaml). If it isn't there, add it
with `napier source add` or open a [source
request](https://github.com/bvk7787/napier/issues/new?template=source_request.yml).

**Can I `pip install napier`?** The PyPI package just points you to the repo. napier needs its data
files, and those live in the clone.

**Does anything get uploaded?** No. napier downloads the documents in its lists and the search
models, and sends nothing out. An assistant you connect sees whatever its lookups return.

**Do I need a GPU?** No. Search runs fine on a laptop CPU, and faster on Apple Silicon or with CUDA.

**Windows?** Untested. CI runs on macOS and Linux.

**Why are some manuals "not downloaded"?** A few sites' robots.txt doesn't allow automated
downloads, and napier respects that. `napier fetch` prints the URL. Download the file in a browser
and run `napier fetch --source ID --from FILE`.

**Is it OK to quote manuals in facts?** The repo holds links, checksums and short quoted phrases.
Each user downloads the documents from the publisher. The [data
policy](https://github.com/bvk7787/napier/blob/main/docs/data-policy.md) has the details, including
how publishers can ask for changes.

## Limitations

- `grep` needs the PDF's text layer. A scanned manual only reaches `read` and `search` through
  Docling's OCR (with the `index` extra), and its printed page numbers can't be detected.
- Each document gets one page offset. Manuals that restart numbering per chapter (3-12) or switch
  from roman to arabic numerals only cite correctly in the main numbered run.
- Grep is a case-insensitive substring match, so `mA` also finds "Manual" (use `--case` or
  `--regex`). Brackets matter: `LEFT+PLAY` won't find `[LEFT]+[PLAY]`.
- `source check` sees changes at the same URL. A new manual published under a new file name won't
  show up, so check the maker's page when new firmware comes out.
- The source list reflects the gear its contributors own.

## Safety

napier only downloads the URLs in its source lists. It checks robots.txt first, identifies itself
honestly, waits at least 2 seconds between requests to a site, backs off when a site asks it to and
never logs in. It doesn't open any ports or send telemetry. It only writes to `~/.napier`, the
Hugging Face cache, the YAML and generated notes in your clone and overlay, and anywhere you point
`--out`.

Text from manuals and forums reaches your assistant marked as document content, and the MCP server
tells it not to follow instructions found in that text. The only tools that write are the two fact
tools, and their changes show up in `git diff`.
[docs/how-it-works.md](https://github.com/bvk7787/napier/blob/main/docs/how-it-works.md) has the
details, and [SECURITY.md](https://github.com/bvk7787/napier/blob/main/SECURITY.md) explains how to
report a problem.

napier is provided as is under Apache-2.0. When a fact matters, like calibration or a firmware
update that could brick a module, check the manual page it cites.

## Requirements

- macOS or Linux with Python 3.11 or later (uv can install one for you).
- The base install is small. The `index` extra pulls in PyTorch through sentence-transformers and
  Docling, about 1.5 GB on macOS and several GB on Linux, where PyTorch's default wheels include
  CUDA. The models take another 4.7 GB. All sources together take about 350 MB in `~/.napier/files`,
  plus about 300 MB for the index and parse cache.
- Parsing and indexing every source the first time takes a while on a laptop. After that, `ingest`
  only redoes what changed.

## For maintainers

`napier refresh` runs the whole update pass unattended: it checks sources, syncs the rack, applies
updates, re-ingests, rechecks facts and specs, and runs the eval and tests. Then it opens a pull
request for the public changes, listing anything that needs a person to look at it. It can use a
local [Ollama](https://ollama.com) model to reword eval questions for sources that changed. Changes
to your overlay are committed and pushed straight to the overlay's repo.

It needs a clean clone on `main` (and a clean overlay), the `index` extra and pytest, plus the
GitHub CLI and push access to `origin` unless you pass `--no-push`. If you just use napier,
`git pull` gets you the maintainers' updates.

## Contributing and license

Issues and pull requests are welcome, especially sources and facts for gear you own. See
[CONTRIBUTING.md](https://github.com/bvk7787/napier/blob/main/CONTRIBUTING.md), the [code of
conduct](https://github.com/bvk7787/napier/blob/main/CODE_OF_CONDUCT.md),
[SUPPORT.md](https://github.com/bvk7787/napier/blob/main/SUPPORT.md) for questions, and the
[changelog](https://github.com/bvk7787/napier/blob/main/CHANGELOG.md).

Copyright 2026 the napier authors. The code and contributors' text are Apache-2.0
([LICENSE](https://github.com/bvk7787/napier/blob/main/LICENSE),
[NOTICE](https://github.com/bvk7787/napier/blob/main/NOTICE)). Quoted anchors remain their
publishers' work ([data policy](https://github.com/bvk7787/napier/blob/main/docs/data-policy.md)),
and third-party terms are in
[THIRD_PARTY_NOTICES.md](https://github.com/bvk7787/napier/blob/main/THIRD_PARTY_NOTICES.md).

Named for John Napier, whose tables of logarithms turned a hard calculation into a lookup.

Dirtywave, M8, Elektron, Digitakt, OXI, Intellijel, Instruō, Make Noise, ALM, Steady State Fate,
Noise Engineering, Strymon, Squarp, WMD, Joranalogue, Erica Synths, ModularGrid, NotebookLM and the
other product and company names here are trademarks of their owners. napier is an independent
project and isn't affiliated with or endorsed by any of them.
