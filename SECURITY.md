# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## What napier does

napier is a command-line tool and an MCP server that runs on your own machine over stdio. It doesn't
open a listening port or send telemetry.

It only writes to:

- its home folder (`~/.napier` by default): downloaded sources, the parse cache, the text layer, the
  search index and reports
- the Hugging Face cache (`~/.cache/huggingface`), for the search models in the `[index]` extra
- YAML files in its own clone and your overlay (`local/`), when you add sources or facts, sync a
  rack or run `napier refresh`, plus the notes `rack sync` and `rack usage` generate in the
  overlay's `notes/`
- wherever you point `--out` for `napier rack view` and `napier rack export`

It only uses the network to:

- download the URLs in its source lists, after checking robots.txt, with an honest user agent and at
  least 2 seconds between requests to the same site
- download the search models from Hugging Face, once
- send `$GITHUB_TOKEN` to api.github.com when fetching a `github_releases` source, if you've set it
- talk to a local Ollama server, if `napier refresh` uses one
- run `git` and `gh` against your own repositories when `napier refresh` commits or opens a pull
  request

The rack view page loads nothing from the network unless you pass `--web-fonts`, which loads its
display fonts from Google Fonts.

## What it protects against

Source lists are treated as data. Source and device ids have to be plain names (lowercase letters,
digits and underscores), so an entry can't point at a path outside napier's folders. Only `http` and
`https` URLs are fetched, and never from a private, loopback or link-local address. Redirects are
followed only to public addresses that robots.txt also allows. Local files (`path`) are only
accepted from your overlay's list, and each response is capped at 300 MB and 10 minutes.

Retrieved text is untrusted. Manuals, changelogs and forum posts are written by other people, so the
MCP server returns them as document content and tells the assistant not to follow instructions
inside them. The only MCP tools that write are `add_fact` and `verify_fact`. They only write to the
fact file of a device napier already knows, stamp each fact `via: mcp` and never commit, so every
change shows up in `git diff`.

`grep --regex` refuses long patterns and nested repeats like `(a+)+`.

The search models are pinned to a commit on Hugging Face, so an upstream update can't change what
runs. Docling downloads its own layout models.

## What it trusts

A rack-source plug-in (the `napier.rack_sources` entry point) is a Python package that runs with
your permissions. Only install ones you trust.

`napier refresh` pulls from your clone's `origin` (unless `--no-push`) and runs the test suite and
your overlay's `local/tests`, which means it runs whatever code that remote holds. Only use it on a
clone whose remote you control.

## Reporting a vulnerability

Report it privately through GitHub:
<https://github.com/bvk7787/napier/security/advisories/new>, or **Report a vulnerability** on the
repo's **Security** tab. Please don't open a public issue. Include `napier --version`, your OS and
Python version, and the steps or files that show the problem.

Things worth reporting include:

- a source list, document, fact file or rack file that gets napier to run code, or to read or write
  outside the places above
- a downloaded document that escapes `~/.napier` (through paths or archive members)
- an MCP call that writes somewhere other than the fact file for the device or fact it names
- a URL, redirect or document that gets napier to request a private or local address
- document text that makes the MCP server itself act on it

You'll get a reply within a week. We'll work on the fix in the private advisory, credit you in the
release notes unless you'd rather not be named, and publish the advisory once a fixed release is
out.
