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
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from napier import paths

STATUSES = ("manual", "changelog", "community", "hardware", "code", "unverified", "refuted")
HEADER = """\
# Facts for {device}. Managed by `napier facts` (hand edits are fine; comments other than this
# header are not kept when napier rewrites the file).
# status: manual | changelog | community | hardware | code | unverified | refuted
# pages are printed page numbers in `source`. q + anchors make the fact an eval case.
"""
ORDER = ["id", "claim", "status", "source", "pages", "cite", "verified", "via", "q", "anchors", "alt", "notes"]


def _overlay_only(device: str) -> bool:
    """True when only the overlay's source list knows the device (gear you added with --local)."""
    from napier.sources import _load_one
    lf = paths.local_sources_file()
    if not lf or not lf.exists():
        return False
    in_overlay = any(s.device == device for s in _load_one(lf))
    return in_overlay and not any(s.device == device for s in _load_one(paths.sources_file()))


def facts_file(device: str, root: Path | None = None) -> Path:
    """Where a device's facts live: `root` if given; else wherever a file for the device already is
    (the overlay's local/facts first); else local/facts for a device only the overlay's sources know;
    else the public facts/."""
    paths.check_name("device", device)
    if root:
        return paths.inside(root, root / f"{device}.yaml")
    for r in reversed(paths.facts_dirs()):
        if (r / f"{device}.yaml").exists():
            return paths.inside(r, r / f"{device}.yaml")
    lr = paths.local_root()
    if lr and _overlay_only(device):
        return paths.inside(lr / "facts", lr / "facts" / f"{device}.yaml")
    return paths.inside(paths.facts_dir(), paths.facts_dir() / f"{device}.yaml")


def load(device: str | None = None, root: Path | None = None) -> list[dict]:
    roots = [root] if root else paths.facts_dirs()
    if device:
        files = [facts_file(device, root)]
    else:
        # one list sorted by file name across public and overlay folders, as if they were one folder
        files = sorted((f for r in roots for f in r.glob("*.yaml")), key=lambda f: f.name)
    out = []
    for f in files:
        if not f.exists():
            continue
        for d in yaml.safe_load(f.read_text()) or []:
            d.setdefault("device", f.stem)
            out.append(d)
    return out


def save(device: str, facts: list[dict], root: Path | None = None) -> Path:
    f = facts_file(device, root)
    f.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in facts:
        row = {k: d[k] for k in ORDER if k in d and d[k] not in (None, "", [])}
        row.update({k: v for k, v in d.items() if k not in ORDER and k != "device"})
        rows.append(row)
    f.write_text(HEADER.format(device=device) + "\n" +
                 yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=100))
    return f


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
    facts = load(device, root)
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
    save(device, facts, root)
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
    device = find(fid, root)["device"]
    facts = load(device, root)
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
            save(device, facts, root)
            return f
    raise KeyError(fid)


def eval_cases(device: str | None = None, root: Path | None = None) -> list[dict]:
    return [f for f in load(device, root) if f.get("q") and f.get("anchors")]
