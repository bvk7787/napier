# Sources

A source is one document napier can fetch: a manual, a firmware changelog, a forum thread, a
pinned file of firmware source code, or a note of your own. The public list is `sources.yaml` in the
clone; your own go in your overlay's `local/sources.yaml`, which is read first.

## Adding one

```bash
napier source add https://maker.example/module-manual.pdf --id maker_module_manual --device maker_module \
    --title "Maker Module manual" --version "v1.2" --local
napier ingest --source maker_module_manual          # --text-only to skip the search index
napier grep "a phrase you know is on page 12" --device maker_module
```

`source add` checks robots.txt, downloads the file once and writes the entry; for a PDF it also pins
it (sha256) and detects the printed-page offset from page footers and headers. `ingest` extracts the text for `grep` and `read`
and, with the `index` extra, adds it to the search index. Check the offset `source add` printed:
grep for something on a known page and see that the cite matches.

- **`--local`** writes to your overlay (`local/sources.yaml`; create `local/` first). Without it the
  entry goes into the public `sources.yaml`, which is right when you're preparing a pull request and
  awkward otherwise: a dirty public file makes `git pull` conflict.
- **Ids** are lowercase letters, digits and underscores. By convention `<device>_manual`,
  `<device>_changelog`, `<device>_tips`. The device id groups a device's sources (`maker_module`).
- **A local file** works the same way: `napier source add ~/Documents/rig-notes.md --id my_rig_notes
  --device my_rig --kind note --local`. Local files only go in the overlay.

## Kinds

| Kind | What it is | Pinned? | Re-checked? |
|---|---|---|---|
| `manual` | The maker's manual (PDF, or a manual web page) | PDFs: yes (sha256); web pages: no | yes |
| `changelog` | Firmware release notes, a GitHub releases page, a product page's changelog | no | yes |
| `community` | A forum thread or shared doc: opinions and workarounds | no | forum threads: snapshot (`--no-check`); shared docs: yes |
| `code` | Firmware source at one commit, for details the manuals skip | by URL | snapshot |
| `note` | Your own files, in your overlay | no | no |

Results always say which kind they came from, and `--kind` filters by it.

## Formats

`--format` is guessed from the URL (PDF, Google Doc, GitHub releases, `.md`; anything else is
`text`). Pass `--format html` for a web page.

| Format | For |
|---|---|
| `pdf` | PDF manuals. Text by page, so cites are printed page numbers |
| `html`, `text`, `markdown` | Web pages and plain files, split into sections by heading (`--heading REGEX` for unusual headings) |
| `gdoc` | A public Google Doc, exported as markdown |
| `github_releases` | A repository's releases page |
| `discourse` | A Discourse forum topic, through its public `/raw` page |

For a product or shop page that carries a changelog, crop it with `--start-at REGEX` and
`--stop-at REGEX` so price or stock changes don't read as a new version.

## Printed pages

Cites use the number printed on the page, so you can turn to it in the PDF or on paper. Each PDF
has a `page_offset` (printed page = PDF page - offset), detected from page footers like `12`,
`pg 48` or `Manual Title 13` when at least three pages carry a number and at least half of them
agree. When they
don't, `source add` writes 0 and warns; `napier source offset ID` shows what it found, and you can
set `page_offset` by hand.

Pages before the numbering starts (cover, contents) show as `PDF p. N`; `napier read ID --pdf-page N`
reads them. Manuals that restart numbering per chapter (3-12) cite correctly only in the main run.

## When a site doesn't allow automated downloads

napier follows robots.txt: if a site disallows the URL, `source add` and `fetch` refuse. Download
the file in your browser instead and hand it over:

```bash
napier fetch --source maker_module_manual --from ~/Downloads/module-manual.pdf
```

The file is checked against the pin in `sources.yaml`, so you get exactly the version the facts
cite. For a document that isn't in the list yet, add the downloaded file to your overlay
(`napier source add ~/Downloads/module-manual.pdf --id ... --device ... --local`). Only use
`--ignore-robots` when the publisher has told you it's fine.

## Keeping sources current

```bash
napier source check --device maker_module   # fetch each source once; report same / changed / gone
napier source apply maker_module_manual     # take the new version: file, pin, date, page offset
napier ingest --source maker_module_manual
napier facts recheck --source maker_module_manual   # facts whose quoted anchor moved or vanished
```

A changed file waits in `~/.napier/pending` until you apply it. `facts recheck --fix-pages` updates
facts whose anchor just moved to another page; a vanished anchor means the claim needs checking
against the new text: re-anchor it if it still holds, or `napier facts verify ID --refute`.

`source check` sees a document change at the same URL. It can't see a newer manual published under
a new file name; check the maker's download page, then `napier source apply ID --url NEW_URL`.

## Contributing a source

Gear anyone could own belongs in the public list. Add it without `--local`, add a few facts with
their printed pages, run `pytest -q`, and open a pull request. [CONTRIBUTING.md](../CONTRIBUTING.md)
has the checklist, and [data-policy.md](data-policy.md) says what may be quoted.
