# Data policy

napier is a list of where documents live plus notes about what they say. This page covers what the
repository holds, under what terms, and how a publisher can ask for something to change.

## What the repository holds

- **Source entries** (`sources.yaml`): a URL, a title, a version, a sha256 checksum, a printed-page
  offset. The documents themselves are never committed: each user's napier downloads its own copy
  from the publisher, once, and keeps it on that user's machine.
- **Facts** (`facts/*.yaml`): a claim in the contributor's own words, its status, the source and
  printed page it came from, and for some facts an eval question with **anchors**: short phrases
  quoted from the page so search and `facts recheck` can find the passage.
- **Specs** (`specs/*.yaml`): a module's power draw and jack names, each with the page it's on and,
  for power, a short anchor.
- **The module catalog** (`catalog/modules.yaml`): which napier device a rack slug maps to, with a
  role and tags.

## Terms

- **Contributors' own text** (claims, notes, questions, the catalog, specs' figures and names) is
  under the repository's license, Apache-2.0, like the code.
- **Anchors are quotations.** They stay the publisher's work. Each is kept short (at most 25 words;
  `tests/test_data.py` enforces it) and exists so a reader can find and check the passage in the
  publisher's own document. They aren't a substitute for the document.
- **Documents** are never committed. Where a site's robots.txt disallows automated downloads, napier
  doesn't fetch it; the user downloads it in a browser and hands it over (`napier fetch --source ID
  --from FILE`).

## For publishers and makers

If you publish a document napier lists and want something changed, open an issue with the
[publisher request](https://github.com/bvk7787/napier/issues/new?template=publisher_request.yml)
form (it carries the `publisher-request` label). You can ask to:

- remove a source entry, and with it the facts and anchors that cite it;
- shorten or remove particular anchors;
- point an entry at a different URL (a newer manual, a canonical download page);
- correct a claim, a version or a page.

A maintainer answers within a week and makes the change in a public pull request that links the
issue. Removals are done first and discussed after. You don't need to prove anything beyond being
the publisher or speaking for them; say so in the issue.

If you'd rather napier fetched less often, or not at all, robots.txt works too: napier reads it
before every first request to a site in a run and follows it, including `Crawl-delay`.

## For contributors

- Write claims in your own words. Quote only what an anchor needs, 25 words at most.
- Add documents by URL from the publisher's own site, or a public page that links to it. Don't add
  re-hosted copies, paywalled documents or anything behind a login.
- Forum threads are snapshots of public pages, cited as community reports.
