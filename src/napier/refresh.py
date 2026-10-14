"""Keeping sources current: find documents that changed upstream, swap in new versions, and
find facts whose anchors or pages no longer match the text they cite.

  check      download each source again and compare with what's pinned or on disk
  apply      take the new download (or a new URL) into sources.yaml and the files folder
  recheck    look for every fact's anchors in its source's text layer, and say which moved or vanished

sources.yaml and facts/*.yaml are edited one entry at a time, so comments and hand layout elsewhere
in those files survive.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from napier import facts as factsmod
from napier import paths
from napier.parse import norm
from napier.sources import EXT, Source, detect_offset, download, entry_yaml, file_sha256, load_sources, offset_trusted
from napier.text import load_units


def pending_file(src: Source) -> Path:
    """Where `check` leaves a changed download for `apply` to pick up."""
    paths.check_name("source id", src.id)
    base = paths.home() / "pending"
    return paths.inside(base, base / f"{src.id}.{EXT[src.format]}")


# ---------------------------------------------------------------- check

@dataclass
class Check:
    id: str
    device: str
    version: str
    status: str            # same | changed | gone | error | local | missing | snapshot
    detail: str = ""
    new_sha: str = ""


def _download_retry(src: Source, timeout: float, tries: int = 3) -> bytes:
    """download() (which spaces requests per host and backs off on 429/503), retrying the TLS EOFs
    and resets some maker sites give rapid repeat connections."""
    for n in range(tries):
        try:
            return download(src, timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if n == tries - 1:
                raise
            time.sleep(4 * (n + 1))
    raise RuntimeError("unreachable")


def check_one(src: Source, timeout: float = 60) -> Check:
    c = Check(src.id, src.device, src.version, "same")
    if not src.check:
        c.status, c.detail = "snapshot", "check: false, a one-time snapshot that is never re-fetched"
        return c
    if src.path:
        c.status, c.detail = "local", "local file, nothing to fetch"
        return c
    try:
        data = _download_retry(src, timeout)
    except urllib.error.HTTPError as e:
        c.status, c.detail = ("gone" if e.code in (404, 410) else "error"), f"HTTP {e.code} at {src.url}"
        return c
    except Exception as e:  # noqa: BLE001
        c.status, c.detail = "error", f"{type(e).__name__}: {e}"
        return c
    if src.is_pdf and not data.startswith(b"%PDF-"):
        c.status, c.detail = "gone", "URL no longer returns a PDF (moved or replaced by a page)"
        return c
    c.new_sha = hashlib.sha256(data).hexdigest()
    if src.sha256:
        old = src.sha256
    elif src.file.exists():
        old = file_sha256(src.file)
    else:
        old = ""
    if not old:
        c.status, c.detail = "missing", "no local copy to compare (run `napier fetch`)"
    elif old != c.new_sha:
        c.status = "changed"
        c.detail = f"{len(data) // 1024} KB, differs from {'pin' if src.sha256 else 'local copy'}"
    if c.status in ("changed", "missing"):
        p = pending_file(src)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return c


def check(sources: list[Source], timeout: float = 60, log=None) -> list[Check]:
    out = []
    for s in sources:
        c = check_one(s, timeout)
        if log:
            log(c)
        out.append(c)
    return out


# ---------------------------------------------------------------- editing sources.yaml in place

def _block_span(text: str, key: str, ident: str) -> tuple[int, int]:
    """(start, end) of the top-level list item `- <key>: <ident>`; ends at the next item or comment."""
    m = re.search(rf"^- {key}: {re.escape(ident)}[ \t]*$", text, re.M)
    if not m:
        raise KeyError(f"no entry with {key} {ident!r}")
    nxt = re.compile(r"^(- |#)", re.M).search(text, m.end())
    return m.start(), (nxt.start() if nxt else len(text))


def _replace_block(text: str, a: int, b: int, new: str) -> str:
    """Swap text[a:b] for `new`, keeping the original block's trailing blank lines."""
    old = text[a:b]
    tail = old[len(old.rstrip("\n")):]
    return text[:a] + new.rstrip("\n") + tail + text[b:]


def update_source_entry(sid: str, changes: dict, file: Path | None = None) -> dict:
    """Change fields of one sources.yaml entry (None removes a field). Returns the new entry."""
    from napier.sources import file_of
    file = file or file_of(sid)
    text = file.read_text()
    a, b = _block_span(text, "id", sid)
    entry = yaml.safe_load(text[a:b])[0]
    for k, v in changes.items():
        if v is None:
            entry.pop(k, None)
        else:
            entry[k] = v
    file.write_text(_replace_block(text, a, b, entry_yaml(entry).lstrip("\n")))
    load_sources(file)               # still valid?
    return entry


def apply(sid: str, url: str | None = None, version: str | None = None, title: str | None = None,
          timeout: float = 60) -> dict:
    """Take a changed source: new file in place, new pin, fetched date, page offset re-detected.
    With `url`, download from there instead (a renamed or newer manual). Returns a report."""
    src = next((s for s in load_sources() if s.id == sid), None)
    if not src:
        raise KeyError(f"no source {sid!r}")
    changes: dict = {"fetched": dt.date.today().isoformat()}
    if url:
        changes["url"] = url
        src = Source(**{**src.__dict__, "url": url})
    if version:
        changes["version"] = version
    if title:
        changes["title"] = title
    p = pending_file(src)
    if url or not p.exists():
        data = download(src, timeout)
    else:
        data = p.read_bytes()
    if src.is_pdf and not data.startswith(b"%PDF-"):
        raise ValueError(f"{sid}: {src.url} did not return a PDF")
    dest = src.file
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    if p.exists():
        p.unlink()
    rep = dict(id=sid, old_sha=src.sha256, new_sha=hashlib.sha256(data).hexdigest(), old_offset=src.page_offset)
    if src.sha256:
        changes["sha256"] = rep["new_sha"]
    if src.is_pdf:
        off, agree, total = detect_offset(dest)
        rep.update(offset=off, agree=agree, numbered=total)
        if offset_trusted(agree, total):
            changes["page_offset"] = off
        else:
            rep["offset_note"] = (f"detector unsure ({agree}/{total} numbered pages agree); kept {src.page_offset}. "
                                  "Check printed page numbers by hand.")
    update_source_entry(sid, changes)
    return rep


# ---------------------------------------------------------------- recheck facts

@dataclass
class Recheck:
    id: str
    device: str
    source: str
    problem: str           # ok | anchor-missing | alt-only | page-moved | no-text | unanchored
    detail: str = ""
    found_pages: list = field(default_factory=list)


def _unit_text(u: dict) -> str:
    return norm((u.get("md") or "") + " " + (u.get("raw") or ""))


def _find(anchor_sets: list[list[str]], units: list[dict]) -> list[int]:
    """Printed pages (0 for unnumbered or text units) of the units that hold any one anchor set.
    An anchor set that only matches across a page break counts for the first of the two pages."""
    texts = [_unit_text(u) for u in units]
    pages = set()
    for s in anchor_sets:
        want = [norm(a) for a in s]
        for i, t in enumerate(texts):
            nxt = texts[i + 1] if i + 1 < len(texts) else ""
            if all(w in t for w in want) or (nxt and all(w in t + nxt for w in want)
                                             and not all(w in nxt for w in want)):
                pages.add(units[i].get("printed") or 0)
    return sorted(pages)


def recheck(device: str | None = None, source: str | None = None) -> list[Recheck]:
    srcs = {s.id: s for s in load_sources()}
    out = []
    for f in factsmod.load(device):
        sid = f.get("source") or ""
        if source and sid != source:
            continue
        r = Recheck(f["id"], f["device"], sid, "ok")
        if not f.get("anchors"):
            r.problem = "unanchored"
            out.append(r)
            continue
        if sid not in srcs:
            r.problem, r.detail = "no-text", f"unknown source {sid!r}"
            out.append(r)
            continue
        units = load_units(sid)
        if not units:
            r.problem, r.detail = "no-text", "no text layer (run `napier ingest`)"
            out.append(r)
            continue
        primary = _find([f["anchors"]], units)
        alt = _find(f.get("alt") or [], units) if f.get("alt") else []
        if not primary and not alt:
            r.problem, r.detail = "anchor-missing", f"{f['anchors']} not in {srcs[sid].label()}"
        elif not primary:
            r.problem, r.detail, r.found_pages = "alt-only", "only an alt anchor set still matches", alt
        elif srcs[sid].is_pdf and f.get("pages") and not set(f["pages"]) & set(p for p in primary if p):
            r.problem, r.found_pages = "page-moved", [p for p in primary if p]
            r.detail = f"cited {f['pages']}, now on {r.found_pages}"
        out.append(r)
    return out


def set_fact_pages(fid: str, pages: list[int], root: Path | None = None) -> Path:
    """Rewrite only one fact's block with new pages, leaving the rest of the file untouched."""
    device = factsmod.find(fid, root)["device"]
    file = factsmod.facts_file(device, root)
    text = file.read_text()
    a, b = _block_span(text, "id", fid)
    fact = yaml.safe_load(text[a:b])[0]
    fact["pages"] = pages
    order = factsmod.ORDER
    fact = {k: fact[k] for k in order if k in fact} | {k: v for k, v in fact.items() if k not in order}
    new = yaml.safe_dump([fact], sort_keys=False, allow_unicode=True, width=110)
    file.write_text(_replace_block(text, a, b, new))
    yaml.safe_load(file.read_text())
    return file
