"""Rack sources: where `napier rack sync` reads your actual rack from.

A rack source turns some description of a rack (a file you write, a page on a rack-planning site,
an export from another tool) into one plain structure:

    rack     {id, name, modified, rows, hp}
    modules  [{slug, vendor, name, hp, is_1u, power: {plus12, minus12, plus5}, depth_mm, passive,
               row, col}, ...]          one entry per physical module; row and col (HP) are 1-based

napier ships one, `file`: a YAML rack you write by hand (racks/layout.yaml), so nothing is fetched.
Anything else is a plug-in: an object with

    name               short id, used to enable it
    read(settings, base) -> dict     the structure above; `settings` is the mapping from
                                     racks/devices.yaml, `base` the racks folder (for relative paths)

registered by its package under the entry-point group "napier.rack_sources", e.g.

    [project.entry-points."napier.rack_sources"]
    myplanner = "my_package.module:SOURCE"

and enabled by name in racks/devices.yaml, so installing one never changes anything by itself:

    rack_source: myplanner
    rack: {url: "https://..."}        # passed to read() as settings
    planning: {url: "https://..."}    # optional: a planning rack, read the same way; modules on it you
                                      # don't own join the wishlist

A source that fetches over the network must be polite: check robots.txt, send an honest user agent,
fetch each page once per run (napier.sources has `robots_allows` and `_get` for that).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml

GROUP = "napier.rack_sources"
BUILTIN = "file"


class RackSource(Protocol):
    name: str

    def read(self, settings: dict, base: Path) -> dict: ...


class RackSourceError(RuntimeError):
    pass


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


class FileSource:
    """A rack written by hand. settings: {file: layout.yaml} (relative to the racks folder). The file:

        rack: {name: My Rack, rows: 6, hp: 208, modified: 2026-10-12}
        modules:
          - slug: make-noise-maths          # any stable id; ModularGrid slugs line up with catalog/
            vendor: Make Noise
            name: Maths
            hp: 20
            format: 3U                       # or 1U
            power: {plus12: 60, minus12: 50, plus5: 0}   # mA, optional
            at: ["row 2, hp 13"]             # one position per copy
    """
    name = BUILTIN

    def read(self, settings: dict, base: Path) -> dict:
        from napier.scenarios import parse_at
        f = Path(str(settings.get("file") or "layout.yaml")).expanduser()
        f = f if f.is_absolute() else base / f
        if not f.exists():
            raise RackSourceError(f"no rack file at {f} (see examples/racks/layout.yaml)")
        doc = yaml.safe_load(f.read_text()) or {}
        r = doc.get("rack") or {}
        rack = dict(id=str(r.get("id") or f.stem), name=str(r.get("name") or f.stem),
                    modified=str(r.get("modified") or "")[:10], rows=int(r.get("rows") or 0), hp=int(r.get("hp") or 0))
        mods = []
        for m in doc.get("modules") or []:
            if not m.get("slug"):
                raise RackSourceError(f"{f}: every module needs a slug ({m})")
            pw = m.get("power") or {}
            for a in m.get("at") or []:
                p = parse_at(a)
                if not p:
                    raise RackSourceError(f"{f}: {m['slug']}: can't read position {a!r} (use 'row N, hp N')")
                mods.append(dict(slug=m["slug"], vendor=str(m.get("vendor") or ""), name=str(m.get("name") or m["slug"]),
                                 hp=int(m.get("hp") or 0), is_1u=str(m.get("format") or "3U").upper() == "1U",
                                 power=dict(plus12=_int(pw.get("plus12")), minus12=_int(pw.get("minus12")),
                                            plus5=_int(pw.get("plus5"))),
                                 depth_mm=_int(m.get("depth_mm")), passive=bool(m.get("passive", False)),
                                 row=p[0], col=p[1]))
        return dict(rack=rack, modules=mods)


def installed() -> list[str]:
    """`file` plus the names of installed plug-ins (their entry points; nothing is loaded)."""
    from importlib.metadata import entry_points
    return [BUILTIN] + sorted(ep.name for ep in entry_points(group=GROUP) if ep.name != BUILTIN)


def get(name: str | None) -> RackSource:
    """The rack source called `name` (default: file)."""
    name = name or BUILTIN
    if name == BUILTIN:
        return FileSource()
    from importlib.metadata import entry_points
    for ep in entry_points(group=GROUP):
        if ep.name == name:
            try:
                src = ep.load()
            except Exception as e:  # noqa: BLE001
                raise RackSourceError(f"rack source {name!r} failed to load: {type(e).__name__}: {e}") from e
            if not callable(getattr(src, "read", None)):
                raise RackSourceError(f"rack source {name!r} has no read(settings, base)")
            return src
    raise RackSourceError(f"no rack source {name!r} installed (have: {', '.join(installed())})")
