# Data policy

napier is a list of where documents live, plus notes about what they say. This page covers what the
repo holds, the terms it's under, and how a publisher can ask for a change.

## What the repo holds

- `sources.yaml` has one entry per document: a URL, title, version, sha256 checksum and printed-page
  offset. The documents themselves are never committed. Each user's napier downloads its own copy
  from the publisher and keeps it on their machine.
- `facts/*.yaml` holds claims in the contributor's own words, each with its status and the source
  and page it came from. Some facts also have an eval question and **anchors**, short phrases quoted
  from the page so search and `facts recheck` can find the passage.
- `specs/*.yaml` lists a module's power draw and jack names with the page each is on, plus a short
  anchor for the power figures.
- `catalog/modules.yaml` maps rack slugs to napier devices, with a role and tags.

## Terms

Contributors' own text (claims, notes, questions, the catalog, and the figures and names in specs)
is Apache-2.0, like the code.

Anchors are quotations and remain the publisher's work. Each is at most 25 words
(`tests/test_data.py` enforces this) and is there so a reader can find the passage in the
publisher's own document.

When a site's robots.txt doesn't allow automated downloads, napier doesn't fetch from it. The user
downloads the file in a browser and hands it over with `napier fetch --source ID --from FILE`.

## For publishers and makers

If you publish a document napier lists and want something changed, open an issue with the [publisher
request](https://github.com/bvk7787/napier/issues/new?template=publisher_request.yml) form. You can
ask to:

- remove a source entry, along with the facts and anchors that cite it
- shorten or remove specific anchors
- point an entry at a different URL, like a newer manual or your main download page
- correct a claim, version or page number

A maintainer replies within a week and makes the change in a public pull request linked to your
issue. Removals happen first, and any discussion comes after. You don't need to prove anything
beyond saying in the issue that you're the publisher or speak for them.

To have napier fetch less often, or not at all, use robots.txt. napier reads it before its first
request to a site in each run and follows it, including `Crawl-delay`.

## For contributors

- Write claims in your own words, and quote only what an anchor needs (25 words at most).
- Add documents by their URL on the publisher's site, or on a public page that links to them.
  Re-hosted copies, paywalled documents and anything behind a login don't belong here.
- Forum threads are snapshots of public pages and are cited as community reports. Facts from a
  forum paraphrase the thread and link to it, and never quote individual posters.
