"""Module specs from the manuals: power draw and the jack list, each tied to the page that says it.

specs/<name>.yaml (one per module; `slugs` names the module slugs it describes, ModularGrid-style):

    device: make_noise_maths          # napier device
    slugs: [make-noise-maths-black-panel]
    source: make_noise_maths_manual   # where the numbers and jack names come from
    hp: 20                            # optional, when the manual states it
    hp_page: 3
    power:                            # mA per rail as the manual states it
      plus12: 60
      minus12: 50
      plus5: 0
      page: 3                         # printed page (omit for text sources)
      anchor: "60mA @ +12V"           # text that must appear on that page
    jacks:
      - {name: "Ch. 1 Signal IN", dir: in, type: audio, page: 5}
    notes: free text

`check()` verifies every anchor and jack name against the source's text layer (on the cited page
for PDFs), so a spec can't drift from the manual it cites. `compare()` lines manual power up
against the rack source's numbers in the rack snapshot.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from napier import paths
from napier.parse import norm
from napier.sources import load_sources
from napier.text import load_units

DIRS = ("in", "out", "io")
TYPES = ("audio", "cv", "gate", "trigger", "clock", "pitch", "midi", "usb", "power", "other")
RAILS = ("plus12", "minus12", "plus5")


def specs_dir() -> Path:
    return Path(os.environ.get("NAPIER_SPECS") or paths.REPO_ROOT / "specs").expanduser()


def load_all() -> dict[str, dict]:
    """{spec name: spec dict}."""
    out = {}
    d = specs_dir()
    if d.exists():
        for f in sorted(d.glob("*.yaml")):
            s = yaml.safe_load(f.read_text()) or {}
            s["_name"] = f.stem
            out[f.stem] = s
    return out


def by_slug() -> dict[str, dict]:
    return {slug: s for s in load_all().values() for slug in (s.get("slugs") or [])}


@dataclass
class Problem:
    spec: str
    what: str
    detail: str


@dataclass
class CheckResult:
    specs: int = 0
    jacks: int = 0
    powered: int = 0
    problems: list[Problem] = field(default_factory=list)


def _pages_with(text: str, units: list[dict]) -> set:
    """Printed pages (0 for text sources or unnumbered pages) whose text holds `text`, including a
    match that runs across a page break (counted for the first page)."""
    want = norm(text)
    if not want:
        return set()
    texts = [norm((u.get("md") or "") + " " + (u.get("raw") or "")) for u in units]
    found = set()
    for i, t in enumerate(texts):
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        if want in t or (nxt and want in t + nxt and want not in nxt):
            found.add(units[i].get("printed") or 0)
    return found


def _on_page(text: str, page, units: list[dict], is_pdf: bool) -> tuple[bool, set]:
    pages = _pages_with(text, units)
    if not pages:
        return False, pages
    if not is_pdf or not page:
        return True, pages
    want = set(page) if isinstance(page, list) else {page}
    return bool(want & pages), pages


def check(names: list[str] | None = None) -> CheckResult:
    srcs = {s.id: s for s in load_sources()}
    res = CheckResult()
    for name, s in load_all().items():
        if names and name not in names:
            continue
        res.specs += 1
        P = lambda what, detail, name=name: res.problems.append(Problem(name, what, detail))
        sid = s.get("source")
        if sid not in srcs:
            P("source", f"unknown source {sid!r}")
            continue
        if not s.get("slugs"):
            P("slugs", "no ModularGrid slugs")
        units = load_units(sid)
        if not units:
            P("source", f"{sid} has no text layer (run `napier ingest --source {sid}`)")
            continue
        pdf = srcs[sid].is_pdf
        pw = s.get("power")
        if pw:
            res.powered += 1
            for r in RAILS:
                if pw.get(r) is not None and not isinstance(pw.get(r), int):
                    P("power", f"{r} should be an integer mA, got {pw.get(r)!r}")
            if not pw.get("anchor"):
                P("power", "no anchor")
            else:
                ok, pages = _on_page(pw["anchor"], pw.get("page"), units, pdf)
                if not ok:
                    P("power", f"anchor {pw['anchor']!r} not on p. {pw.get('page')}"
                               + (f" (found on {sorted(pages)})" if pages else " (not found)"))
        seen = set()
        for j in s.get("jacks") or []:
            res.jacks += 1
            jn = j.get("name", "")
            if j.get("dir") not in DIRS:
                P("jack", f"{jn!r}: dir must be one of {DIRS}")
            if j.get("type") not in TYPES:
                P("jack", f"{jn!r}: type must be one of {TYPES}")
            key = (jn, j.get("dir"))
            if key in seen:
                P("jack", f"{jn!r} ({j.get('dir')}) listed twice")
            seen.add(key)
            ok, pages = _on_page(j.get("label") or jn, j.get("page"), units, pdf)
            if not ok:
                P("jack", f"{jn!r} not on p. {j.get('page')}" + (f" (found on {sorted(pages)})" if pages else " (not found)"))
    return res


def io_counts(spec: dict) -> dict:
    """Jack counts per type and direction, e.g. {'audio_in': 2, 'cv_out': 1}."""
    out: dict[str, int] = {}
    for j in spec.get("jacks") or []:
        dirs = ("in", "out") if j.get("dir") == "io" else (j.get("dir"),)
        for d in dirs:
            k = f"{j.get('type')}_{d}"
            out[k] = out.get(k, 0) + 1
    return out


def compare(snapshot_modules: list[dict], tolerance: int = 5) -> list[dict]:
    """Manual power vs the rack source's power per racked module. A rail differing by more than
    `tolerance` mA (or present on one side only) is a mismatch."""
    specs = by_slug()
    out = []
    for m in snapshot_modules:
        s = specs.get(m["slug"])
        if not s or not s.get("power"):
            continue
        mg, man = m.get("power") or {}, s["power"]
        diffs = {}
        for r in RAILS:
            a, b = mg.get(r), man.get(r)
            if b is None:
                continue
            if (a or 0) != b and abs((a or 0) - b) > tolerance:
                diffs[r] = dict(rack_source=a, manual=b)
        if diffs:
            out.append(dict(slug=m["slug"], name=f"{m['vendor']} {m['name']}", spec=s["_name"], source=s["source"],
                            page=man.get("page"), diffs=diffs))
    return out
