# Connecting an assistant (MCP)

`napier mcp` serves napier's lookups to any assistant that speaks the
[Model Context Protocol](https://modelcontextprotocol.io) over stdio. The assistant runs the same
`grep`, `read` and `search` you would, and quotes the printed page.

## Install the extra

The server needs the `mcp` extra; add `index` too if you want `search`. List every extra you want
each time you install, because reinstalling with fewer drops the others:

```bash
cd /path/to/your/napier/clone
uv tool install -e ".[index,mcp]"     # or ".[mcp]" for every tool except search
which napier                          # the full path the configs below need
```

With pip instead of uv, install into a virtual environment and use that environment's `napier`
(for example `/path/to/napier/.venv/bin/napier`) as the command.

Desktop apps don't see your shell's `PATH`, so give them the full path `which napier` printed.
Below it's `/Users/you/.local/bin/napier`; use yours.

## Clients

**Claude Desktop.** Settings, Developer, Edit Config opens `claude_desktop_config.json`. Add the
server and restart Claude Desktop:

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
in a workspace. Note the top-level key is `servers`:

```json
{
  "servers": {
    "napier": { "type": "stdio", "command": "/Users/you/.local/bin/napier", "args": ["mcp"] }
  }
}
```

**Codex** (CLI, IDE extension and app share it). `~/.codex/config.toml`:

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

**Anything else.** The command is the full path to `napier` and the one argument is `mcp`. To point
the server at data you moved, add an environment variable to the entry, for example
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

The device filter is named `device_id` because Claude's desktop app uses an argument named `device`
for its own routing and drops it before the call reaches napier.

Errors come back with the reason, so the assistant can tell you what to do: an unknown device
suggests the closest names, a source that isn't downloaded says which command fetches it, and a
missing extra names the install command.

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

So it can answer: hold **LEFT** and press **PLAY** (M8 Operation Manual v6.5.2, p. 11), and add that
the community tips doc says the same works on smaller selections, labeled as a community report.

## Facts written by an assistant

`add_fact` and `verify_fact` write to the YAML files in your clone or overlay, the same as
`napier facts add` and `napier facts verify`. Each one is stamped `via: mcp`, the device must be one napier knows,
and `hardware` or `refuted` need a note saying what was observed and on which firmware. Nothing is
committed for you: review the diff (`git diff facts/`) before you commit it.

## Safety

Manuals and forum posts are text written by other people. napier returns them as document content
and tells the assistant, in its server instructions, not to act on requests that appear inside
them. Treat a passage that tells the assistant to do something as you would a suspicious email. The
only tools that write are `add_fact` and `verify_fact`, and they write only to fact files.

## Troubleshooting

- **The server doesn't show up.** Use the full path to `napier`, restart the app, and check that
  `/full/path/to/napier mcp` starts in a terminal (it waits for input; Ctrl-C to quit). If it says
  the mcp extra is missing, reinstall with `".[index,mcp]"`.
- **"needs the index extra".** `search` needs `uv tool install -e ".[index,mcp]"` and a full
  `napier ingest`. `grep` and `read` work without it.
- **Empty results.** Look at `not_extracted` (grep) or `not_indexed` (search), or ask the assistant
  to call `status`. Fetch and ingest the device: `napier fetch --device ID && napier ingest --device ID`.
- **Still running old code after `git pull`.** Restart the assistant app; it keeps the server process
  running.
- **The device filter does nothing.** The argument is `device_id`.
