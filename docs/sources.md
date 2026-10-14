# Sources

A source is one document napier can fetch: a manual, a firmware changelog, a forum thread, a pinned
file of firmware source code, or a note of your own. The public list is `sources.yaml` in the clone.
Your own sources go in `local/sources.yaml` in your overlay, which napier reads first.

## Adding one

```bash
napier source add https://maker.example/module-manual.pdf --id maker_module_manual --device maker_module \
    --title "Maker Module manual" --version "v1.2" --local
napier ingest --source maker_module_manual          # --text-only to skip the search index
napier grep "a phrase you know is on page 12" --device maker_module
```

`source add` checks robots.txt, downloads the file once and writes the entry. For a PDF it also pins
the sha256 and works out the printed-page offset from the page footers and headers. `ingest`
extracts the text for `grep` and `read`, and with the `index` extra it also adds the document to the
search index. To check the offset, grep for something on a page you know and see whether the cite
matches.

`--local` writes the entry to your overlay (create `local/` first). Leave it off only when you're
preparing a pull request. Otherwise the public `sources.yaml` stays modified and `git pull` can
conflict.

Ids are lowercase letters, digits and underscores. The convention is `<device>_manual`,
`<device>_changelog` and `<device>_tips`. The device id (`maker_module`) groups a device's sources.

A local file works the same way, and only belongs in the overlay:

```bash
napier source add ~/Documents/rig-notes.md --id my_rig_notes --device my_rig --kind note --local
```

## Kinds

| Kind | What it is | Pinned? | Re-checked? |
|---|---|---|---|
| `manual` | The maker's manual, as a PDF or web page | PDFs only | yes |
| `changelog` | Firmware release notes, a GitHub releases page, a product page's changelog | no | yes |
| `community` | A forum thread or shared doc with tips and workarounds | no | forum threads are snapshots; shared docs yes |
| `code` | Firmware source at one commit, for details the manuals skip | by URL | snapshot |
| `note` | Your own files, in your overlay | no | no |

Every result says which kind it came from, and `--kind` filters by it. A snapshot (`--no-check`) is
fetched once and never re-checked.

## Formats

napier guesses `--format` from the URL: PDFs, Google Docs, GitHub releases pages and `.md` files are
recognized, and anything else is treated as `text`. Pass `--format html` for a web page.

| Format | For |
|---|---|
| `pdf` | PDF manuals, read page by page so cites use printed page numbers |
| `html`, `text`, `markdown` | Web pages and plain files, split into sections by heading (`--heading REGEX` for unusual headings) |
| `gdoc` | A public Google Doc, exported as markdown |
| `github_releases` | A repository's releases page |
| `discourse` | A Discourse forum topic, through its public `/raw` page |

If a product or shop page carries a changelog, crop it with `--start-at REGEX` and `--stop-at REGEX`
so a price or stock change doesn't look like a new version.

## Printed pages

Cites use the number printed on the page, so you can turn straight to it. Each PDF has a
`page_offset`, where printed page = PDF page - offset. napier detects it from footers like `12`,
`pg 48` or `Manual Title 13`, as long as at least three pages have a number and at least half of
them agree. If they don't, `source add` writes 0 and warns you. `napier source offset ID` shows what
it found, and you can set `page_offset` by hand.

Pages before the numbering starts, like the cover and contents, show up as `PDF p. N`, and
`napier read ID --pdf-page N` reads them. Manuals that restart numbering in each chapter (3-12) only
cite correctly in the main numbered run.

## When robots.txt disallows a download

If a site's robots.txt disallows a URL, `source add` and `fetch` won't download it. Get the file in
your browser and hand it over:

```bash
napier fetch --source maker_module_manual --from ~/Downloads/module-manual.pdf
```

napier checks the file against the pin in `sources.yaml`, so you end up with the exact version the
facts cite. For a document that isn't listed yet, add the downloaded file to your overlay with
`napier source add ~/Downloads/module-manual.pdf --id ... --device ... --local`. Only use
`--ignore-robots` if the publisher has told you it's fine.

## Keeping sources current

```bash
napier source check --device maker_module   # fetch each source once; report same / changed / gone
napier source apply maker_module_manual     # take the new version: file, pin, date, page offset
napier ingest --source maker_module_manual
napier facts recheck --source maker_module_manual   # facts whose quoted anchor moved or vanished
```

A changed file waits in `~/.napier/pending` until you apply it. `facts recheck --fix-pages` updates
facts whose anchor moved to another page. When an anchor disappears, check the claim against the new
text: re-anchor it if it still holds, or mark it wrong with `napier facts verify ID --refute`.

`source check` only sees changes at the same URL. When a maker publishes a new manual under a new
file name, find it on their download page and run `napier source apply ID --url NEW_URL`.

## Contributing a source

If other people are likely to own it too, add it to the public list: leave off `--local`, add a few
facts with their printed pages, run `pytest -q` and open a pull request.
[CONTRIBUTING.md](../CONTRIBUTING.md) has the checklist, and [data-policy.md](data-policy.md) covers
what you can quote.
