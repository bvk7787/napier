# Connecting an assistant (MCP)

`napier mcp` runs napier as an MCP server over stdio, so any assistant that supports the [Model
Context Protocol](https://modelcontextprotocol.io) can look things up the way you would on the
command line and quote the printed page.

## Install the extra

The server needs the `mcp` extra, and `search` also needs `index`. A reinstall replaces the previous
one, so list every extra you want each time:

```bash
cd /path/to/your/napier/clone
uv tool install -e ".[index,mcp]"     # or ".[mcp]" for every tool except search
which napier                          # the full path the configs below need
```

If you installed with pip into a virtual environment, use that environment's `napier` instead, for
example `/path/to/napier/.venv/bin/napier`.

Desktop apps don't see your shell's `PATH`, so give them the full path. The examples below use
`/Users/you/.local/bin/napier`; swap in yours.

## Clients

**Claude Desktop.** Open Settings, then Developer, then Edit Config to get to
`claude_desktop_config.json`. Add the server and restart the app:

```json
{
  "mcpServers": {
    "napier": { "command": "/Users/you/.local/bin/napier", "args": ["mcp"] }
  }
}
```

**Claude Code.** `--scope user` makes it available in every project:

```bash
claude mcp add --scope user napier -- "$(which napier)" mcp
```

**Cursor.** `~/.cursor/mcp.json` for every project, or `.cursor/mcp.json` in one:

```json
{
  "mcpServers": {
    "napier": { "type": "stdio", "command": "/Users/you/.local/bin/napier", "args": ["mcp"] }
  }
}
```

**VS Code** (Copilot agent mode). Run **MCP: Open User Configuration**, or create `.vscode/mcp.json`
in a workspace. The top-level key here is `servers`:

```json
{
  "servers": {
    "napier": { "type": "stdio", "command": "/Users/you/.local/bin/napier", "args": ["mcp"] }
  }
}
```

**Codex.** The CLI, IDE extension and app all read `~/.codex/config.toml`:

```toml
[mcp_servers.napier]
command = "/Users/you/.local/bin/napier"
args = ["mcp"]
```

**Windsurf.** `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "napier": { "command": "/Users/you/.local/bin/napier", "args": ["mcp"] }
  }
}
```

**Anything else.** Use the full path to `napier` as the command and `mcp` as the only argument. If
you moved napier's data, add `NAPIER_HOME` to the entry's environment, for example
`"env": {"NAPIER_HOME": "/Volumes/data/napier"}` (in TOML, a `[mcp_servers.napier.env]` table).

## Tools

| Tool | What it does |
|---|---|
| `status` | Every source with whether it's downloaded, extracted (for grep and read) and indexed (for search) |
| `grep(text, device_id?, source?, regex?, case_sensitive?, context?, max_hits?)` | Exact text search. Returns `hits` and `not_extracted`, the sources it couldn't search yet |
| `read(ref, page? \| section? \| toc? \| pdf_page?, nth?, max_chars?)` | A printed page, a whole section, or the headings. `ref` is a source id, or a device id for its manual |
| `search(query, device_id?, kind?, top?)` | Meaning-based search (needs the `index` extra). Returns `hits` and `not_indexed` |
| `facts(device_id?, status?)` | The facts ledger |
| `add_fact(device_id, claim, status?, source?, pages?, cite?, notes?)` | Add a claim |
| `verify_fact(id, status, note?, cite?)` | Record a check: `hardware`, `manual`, `refuted`... |
| `rack(device_id?, role?, jack_type?, jack_dir?, include_wishlist?)` | Your rack's modules, power and jacks |

The device filter is called `device_id` because Claude's desktop app uses an argument named `device`
for its own routing and drops it before the call reaches napier.

Errors say what went wrong. A mistyped device comes back with the closest matches, a source that
isn't downloaded names the command that fetches it, and a missing extra names the install command.

## What it looks like

Asked "How do I cue a song row on the M8?", an assistant with napier connected calls:

```
grep(text="cue the", device_id="m8_tracker", context=0)
```

and gets (abridged; the `heading` comes from Docling's parse, with the `index` extra):

```json
{"hits": [
  {"source_id": "m8_tracker_manual", "kind": "manual",
   "cite": "M8 Operation Manual, v6.5.2 (2026-04-21), p. 11", "heading": "Song View Shortcuts",
   "line": "• [LEFT]+[PLAY] Cue the selected song row for playback."},
  {"source_id": "m8_tracker_tips", "kind": "community",
   "cite": "Open M8 Tips Tricks and Findings (Dirtywave Discord), latest (changed upstream 2026-10-04), § Live Mode Shortcuts",
   "line": "* Hold Left and press Play to cue the whole row(Similarly smaller selections work also.)"}],
 "not_extracted": []}
```

From that it can answer: hold **LEFT** and press **PLAY** (M8 Operation Manual v6.5.2, p. 11). It
can also note that the community tips doc says this works on smaller selections, labeled as a
community report.

Rack questions work the same way. On the example rack, asking what takes a clock calls:

```
rack(jack_type="clock", jack_dir="in")
```

and gets each matching module with its jacks and, where the manual gives one, the page (abridged;
Quadrax and Beads also match):

```json
{"modules": [
  {"name": "Pamela's Pro Workout", "owned": true,
   "jacks": [{"name": "Clk", "dir": "in", "type": "clock", "also": ["cv", "trigger"], "page": 20}]},
  {"name": "Steppy 1U", "owned": true,
   "jacks": [{"name": "CLOCK (CLK) IN", "dir": "in", "type": "clock", "page": 11}]},
  {"name": "Step 8", "owned": false,
   "jacks": [{"name": "STEP IN", "dir": "in", "type": "trigger", "also": ["clock"], "page": 3}]}],
 "case_power": {"main": {"pct": {"plus12": 75, "minus12": 89, "plus5": 0}}}}
```

The same result carries your usage notes, placement rules and the challenge log, so the assistant
can suggest a change with your earlier decisions in view. Wishlist modules come back with
`owned: false`, and the tool tells the assistant never to describe them as owned. A suggested layout
becomes a file in `racks/scenarios/`, which `napier rack scenarios` checks and `napier rack view`
draws next to the current rack.

## Facts written by an assistant

`add_fact` and `verify_fact` write to the same YAML files as `napier facts add` and
`napier facts verify`. The device has to be one napier knows, every fact gets a `via: mcp` stamp,
and `hardware` or `refuted` needs a note saying what was observed and on which firmware. Nothing is
committed for you, so check `git diff` in the clone (and in `local/` if your overlay is a repo)
before you commit.

## Safety

Manuals and forum posts are written by other people. napier returns their text as document content,
and its server instructions tell the assistant not to act on requests inside it. If a passage tells
the assistant to do something, treat it like a suspicious email. The only tools that write are
`add_fact` and `verify_fact`, and they only touch fact files.

## Troubleshooting

- **The server doesn't show up.** Use the full path to `napier`, restart the app, and check that
  `/full/path/to/napier mcp` starts in a terminal (it waits for input; Ctrl-C to quit). If it says
  the mcp extra is missing, reinstall with `".[index,mcp]"`.
- **"needs the index extra".** `search` needs `uv tool install -e ".[index,mcp]"` and a full
  `napier ingest`. `grep` and `read` work without it.
- **Empty results.** Look at `not_extracted` (grep) or `not_indexed` (search), or ask the assistant
  to call `status`, then fetch and ingest the device:
  `napier fetch --device ID && napier ingest --device ID`.
- **Still running old code after `git pull`.** Restart the assistant app. It keeps the server
  process running between chats.
- **The device filter does nothing.** The argument is `device_id`.
