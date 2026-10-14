# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## What napier does

napier is a command-line tool and an MCP server that runs on your own machine over stdio. It opens
no listening port and sends no telemetry. It writes only:

- its home (`~/.napier` by default): downloaded sources, the parse cache, the text layer, the search
  index and reports;
- the search models in the Hugging Face cache (`~/.cache/huggingface`), with the `[index]` extra;
- the YAML files in its own clone and in your overlay (`local/`), when you add sources or facts,
  sync a rack or run `napier refresh`, and the notes `rack sync` and `rack usage` generate in the
  overlay's `notes/`;
- the files `napier rack view` and `napier rack export` write, where you point `--out`.

It uses the network only to:

- download the URLs in its source lists (robots.txt checked, honest user agent, requests to one site
  at least 2 seconds apart);
- download the search models from Hugging Face once;
- send `$GITHUB_TOKEN`, if you've set it, to api.github.com when fetching a `github_releases` source;
- reach a local Ollama server, if `napier refresh` uses one;
- run `git` and `gh` against your own repositories, when `napier refresh` commits or opens a pull
  request.

The rack view is a self-contained page: it loads nothing from the network unless you pass
`--web-fonts`, which loads its display fonts from Google Fonts.

## What it guards against, and what it trusts

- **Source lists are data.** Ids and device ids must be plain names (lowercase letters, digits and
  underscores), so no entry can name a path outside napier's folders. Only `http` and `https` URLs
  are fetched, never to a private, loopback or link-local address, and a redirect is followed only
  to a public address that robots.txt also allows. Local files (`path`) are accepted only from your
  overlay's list. A response is capped at 300 MB and 10 minutes.
- **Retrieved text is untrusted.** Manuals, changelogs and forum posts are written by other people.
  The MCP server returns them as document content and tells the assistant not to follow
  instructions inside them. The only MCP tools that write are `add_fact` and `verify_fact`; they
  write to the fact file of a device napier already knows, stamp the fact `via: mcp`, and commit
  nothing, so every change shows up in `git diff` for you to review.
- **Regexes are limited.** `grep --regex` refuses long patterns and nested repeats like `(a+)+`.
- **Plug-ins are code you install.** A rack-source plug-in (the `napier.rack_sources` entry point)
  runs with your permissions, like any Python package. Install only ones you trust.
- **`napier refresh` runs your clone's code.** It pulls from your clone's `origin` (unless
  `--no-push`) and runs the test suite and your overlay's `local/tests`, so it executes whatever that
  remote holds. Run it only on a clone whose remote you control.
- **The search models are pinned** to a commit on Hugging Face, so an upstream change doesn't alter
  what runs. Docling downloads its own layout models.

Issues worth reporting privately include:

- a crafted source list, document, fact file or rack file that makes napier run code, or read or
  write outside the places above;
- a way for a downloaded document to escape `~/.napier` (paths, archive members);
- an MCP tool call that writes somewhere other than the fact files its arguments name;
- a URL, redirect or document that gets napier to request a private or local address;
- text in a document that gets the MCP server, rather than the assistant, to act on it.

## Reporting a vulnerability

Please report it privately through GitHub: on the repository's **Security** tab, choose **Report a
vulnerability** (a private security advisory). Don't open a public issue for it. Include the
version (`napier --version`), your OS and Python version, and the steps or files that show the
problem.

You can expect an acknowledgment within a week. We'll work on a fix in the private advisory, credit
you in the release notes unless you'd rather not be named, and publish the advisory when a fixed
release is out.
