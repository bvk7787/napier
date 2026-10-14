"""The facts ledger: facts/<device>.yaml, one list of claims per device, each with where it came
from. Status says how far a claim has been checked:

  manual      stated in the manual (source + printed pages)
  changelog   stated in a firmware changelog or release notes
  community   reported by a forum, doc or video (cite a URL); not yet confirmed
  hardware    confirmed on the device itself (strongest)
  unverified  an open question, or a claim with no source yet
  refuted     checked and found wrong (kept so nobody repeats it)

A fact with `q` and `anchors` is also an eval case: `napier eval` asks q and checks that a top
result contains every anchor.

A device's facts can sit in two files, the public facts/<device>.yaml and the overlay's
local/facts/<device>.yaml, and napier reads both. Every public fact quotes an anchor from its source,
so `facts recheck` can test it. Hardware checks, open questions and anything without a quotable
source stay in the overlay, which is where new facts go when you have one.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from napier import paths

STATUSES = ("manual", "changelog", "community", "hardware", "code", "unverified", "refuted")
PERSONAL = ("hardware", "unverified")      # never in the public ledger: they quote no source
HEADER = """\
# Facts for {device}. Managed by `napier facts` (hand edits are fine; comments other than this
# header are not kept when napier rewrites the file).
# status: manual | changelog | community | hardware | code | unverified | refuted
# pages are printed page numbers in `source`. q + anchors make the fact an eval case.
"""
ORDER = ["id", "claim", "status", "source", "pages", "cite", "verified", "via", "q", "anchors", "alt", "notes"]


def _dirs(root: Path | None) -> list[Path]:
    return [root] if root else paths.facts_dirs()


def files(device: str, root: Path | None = None) -> list[Path]:
    """The files holding facts about DEVICE: the public one, then the overlay's, where they exist."""
    paths.check_name("device", device)
    return [paths.inside(r, r / f"{device}.yaml") for r in _dirs(root) if (r / f"{device}.yaml").exists()]


def facts_file(device: str, root: Path | None = None) -> Path:
    """Where a new fact about DEVICE goes: `root` if given; else the overlay's local/facts when there is an
    overlay, so what you record stays yours; else the public facts/, for a pull request. A public fact
    also needs anchors on a cited page, which you add by hand (tests/test_data.py checks)."""
    paths.check_name("device", device)
    if root:
        return paths.inside(root, root / f"{device}.yaml")
    lr = paths.local_root()
    base = lr / "facts" if lr else paths.facts_dir()
    return paths.inside(base, base / f"{device}.yaml")


def _read(file: Path, device: str) -> list[dict]:
    rows = (yaml.safe_load(file.read_text()) or []) if file.exists() else []
    for d in rows:
        d.setdefault("device", device)
    return rows


def load(device: str | None = None, root: Path | None = None) -> list[dict]:
    if device:
        found = files(device, root)
    else:
        # one list sorted by file name across public and overlay folders, as if they were one folder
        found = sorted((f for r in _dirs(root) for f in r.glob("*.yaml")), key=lambda f: f.name)
    return [d for f in found for d in _read(f, f.stem)]


def file_of(fid: str, root: Path | None = None) -> Path:
    """The file a fact is in."""
    for r in _dirs(root):
        for f in sorted(r.glob("*.yaml")):
            if any(d.get("id") == fid for d in yaml.safe_load(f.read_text()) or []):
                return f
    raise KeyError(f"no fact {fid!r}")


def _write(file: Path, device: str, facts: list[dict]) -> Path:
    file.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in facts:
        row = {k: d[k] for k in ORDER if k in d and d[k] not in (None, "", [])}
        row.update({k: v for k, v in d.items() if k not in ORDER and k != "device"})
        rows.append(row)
    file.write_text(HEADER.format(device=device) + "\n" +
                    yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=100))
    return file


def slug(text: str, n: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:n]) or "fact"


def _check_citation(status: str, source: str, pages) -> None:
    """A manual fact names its source, and a fact from a PDF manual its printed pages."""
    if status != "manual":
        return
    if not source:
        raise ValueError("a manual fact names its source (a napier source id)")
    from napier.sources import load_sources
    fmt = {s.id: s.format for s in load_sources()}
    if source not in fmt:
        raise ValueError(f"no source {source!r} (see napier source list)")
    if fmt[source] == "pdf" and not pages:
        raise ValueError(f"{source} is a PDF: give the printed pages the claim is on")


def add(device: str, claim: str, status: str = "unverified", source: str = "", pages=None, cite: str = "",
        notes: str = "", fid: str = "", root: Path | None = None, via: str = "") -> dict:
    """via: how the fact was recorded when it wasn't the CLI (e.g. "mcp", for an assistant acting on the
    user's word), kept on the fact so a reviewer can tell."""
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {', '.join(STATUSES)}")
    _check_citation(status, source, pages)
    file = facts_file(device, root)
    facts = _read(file, device)
    ids = {f["id"] for f in load(root=root)}
    base = fid or f"{device.split('_')[0]}-{slug(claim)}"
    fid, k = base, 2
    while fid in ids:
        fid, k = f"{base}-{k}", k + 1
    fact = dict(id=fid, claim=claim, status=status, source=source, pages=list(pages or []), cite=cite,
                notes=notes)
    if status != "unverified":
        fact["verified"] = dt.date.today().isoformat()
    if via:
        fact["via"] = via
    facts.append(fact)
    _write(file, device, facts)
    return fact


def find(fid: str, root: Path | None = None) -> dict:
    for f in load(root=root):
        if f["id"] == fid:
            return f
    raise KeyError(f"no fact {fid!r}")


def set_status(fid: str, status: str, note: str = "", cite: str = "", root: Path | None = None,
               via: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {', '.join(STATUSES)}")
    file = file_of(fid, root)
    if status in PERSONAL and not root and file.parent.resolve() == paths.facts_dir().resolve():
        raise ValueError(f"{fid} is in the public ledger, where every fact quotes its source. Record your own "
                         f"check as a new fact, which goes to your overlay: napier facts add {file.stem} "
                         f"\"<what you found>\" --status {status}")
    facts = _read(file, file.stem)
    for f in facts:
        if f["id"] == fid:
            f["status"] = status
            f["verified"] = dt.date.today().isoformat()
            if via:
                f["via"] = via
            else:
                f.pop("via", None)
            if cite:
                f["cite"] = cite
            if note:
                f["notes"] = (f.get("notes", "") + ("\n" if f.get("notes") else "") +
                              f"{f['verified']}: {note}").strip()
            _write(file, file.stem, facts)
            return f
    raise KeyError(fid)


def eval_cases(device: str | None = None, root: Path | None = None) -> list[dict]:
    return [f for f in load(device, root) if f.get("q") and f.get("anchors")]
