"""Rack tracking: a snapshot of your rack, mapped to napier devices.

`napier rack sync` reads the rack from its rack source (racks/devices.yaml `rack_source`; the built-in
`file` source reads racks/layout.yaml, plug-ins can read a rack-planning site, see napier.rack_sources)
and writes:

  racks/<slug>.yaml   the snapshot: rack info, and every module with count, HP, position and device
  notes/rack.md       the same as prose, indexed as a `note` source so search knows what's racked

It reports modules added or removed since the last snapshot, and modules with no napier device yet.

The racks folder lives in the private overlay (local/racks, see napier.paths); without one, the
commands read examples/racks. racks/devices.yaml holds the rack source and its settings, the owner's
own `modules` mapping (on top of catalog/modules.yaml, which maps common module slugs to the napier
device whose docs cover them, a `role` and `tags` the viewer uses, and `parent` for expanders),
`off_rack` (owned modules that aren't in the rack, with their specs) and `wishlist` (modules the owner
does NOT own: planned or considered purchases, so their docs and specs are on hand for planning;
everything from it is marked owned: false and kept out of `rack export` unless --wishlist). A
`planning` rack read through the same source adds every module on it the owner doesn't own (more
copies than they own, for duplicates) to the wishlist. Hand-written `wishlist` entries add status notes
for those, or list modules that are only being considered.
Manual-cited power and jack lists live in specs/ (see napier.specs).

racks/usage.yaml is hand-written and never generated: how the owner actually uses each module (its job
in the rig, what it pairs with, what it has to sit near, whether it could ever go) plus rack-wide
placement rules. `napier rack usage` checks it and writes notes/rack-usage.md for search; export and
the MCP `rack` tool attach each module's entry as `usage`.
"""
from __future__ import annotations

import collections
import os
import re
import time
from pathlib import Path

import yaml

from napier import paths, rack_sources


def racks_dir() -> Path:
    return paths.racks_dir()


def notes_dir() -> Path:
    return paths.notes_dir()


def catalog_file() -> Path | None:
    env = os.environ.get("NAPIER_CATALOG")
    if env:
        return None if env.lower() == "none" else Path(env).expanduser()
    return paths.REPO_ROOT / "catalog" / "modules.yaml"


ROLES = ("voice", "filter", "effect", "rhythm", "sequencer", "modulation", "utility", "mixer", "midi", "expander")
CONFIG_FILES = ("devices.yaml", "usage.yaml", "challenges.yaml", "layout.yaml")   # hand-written, never a snapshot
CHALLENGE_OUTCOMES = ("open", "testing", "accepted", "partial", "rejected")
CHALLENGE_KINDS = ("layout", "swap", "role", "purchase", "sale")
CHALLENGE_FIELDS = ("id", "date", "kind", "title", "default", "hypothesis", "evidence", "costs", "test", "confidence",
                    "outcome", "response", "learned")
USAGE_STATUS = ("anchor", "keep", "candidate", "leaving", "planned", "considered")
USAGE_LISTS = ("pairs_with", "keep_near", "distance_ok", "notes", "open")
CASE_LISTS = ("layout", "notes", "open")
RAILS = ("plus12", "minus12", "plus5")
RAIL_LABELS = {"plus12": "+12V", "minus12": "-12V", "plus5": "+5V"}


def _catalog() -> dict:
    f = catalog_file()
    if not f or not f.exists():
        return {}
    return (yaml.safe_load(f.read_text()) or {}).get("modules") or {}


def load_config() -> dict:
    """racks/devices.yaml over catalog/modules.yaml, normalised: modules = {slug: {device, role, tags,
    parent, note}} (an entry in devices.yaml replaces the catalog's for that slug)."""
    f = racks_dir() / "devices.yaml"
    cfg = (yaml.safe_load(f.read_text()) if f.exists() else {}) or {}
    mods = {}
    for slug, v in list(_catalog().items()) + list((cfg.get("modules") or {}).items()):
        v = dict(v or {})
        mods[slug] = dict(device=v.get("device"), role=v.get("role"), tags=list(v.get("tags") or []),
                          parent=v.get("parent"), note=v.get("note"))
    own = cfg.get("modules") or {}
    for slug, dev in (cfg.get("devices") or {}).items():          # older flat form: slug: device
        if slug not in own:                                       # beats the catalog, not `modules`
            mods[slug] = dict(device=dev, role=None, tags=[], parent=None, note=(cfg.get("notes") or {}).get(slug))
    cfg["modules"] = mods
    cfg["off_rack"] = list(cfg.get("off_rack") or [])
    cfg["wishlist"] = list(cfg.get("wishlist") or [])
    return cfg


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def snapshot(parsed: dict, modules: dict, url: str, off_rack: list | None = None,
             wishlist: list | None = None) -> dict:
    by = collections.OrderedDict()
    for m in sorted(parsed["modules"], key=lambda m: (m["vendor"].lower(), m["name"].lower(), m["row"], m["col"])):
        cfg = modules.get(m["slug"]) or {}
        e = by.get(m["slug"])
        if e is None:
            e = by[m["slug"]] = dict(
                slug=m["slug"], mg_id=m.get("mg_id"), vendor=m["vendor"], name=m["name"], hp=m["hp"],
                format="1U" if m.get("is_1u") else "3U", power=m.get("power") or {}, depth_mm=m.get("depth_mm"),
                passive=m.get("passive", False), count=0, device=cfg.get("device"), role=cfg.get("role"),
                tags=cfg.get("tags") or [], parent=cfg.get("parent"), at=[])
        e["count"] += 1
        e["at"].append(f"row {m['row']}, hp {m['col']}")
    snap = dict(rack=dict(parsed["rack"], url=url), modules=list(by.values()))
    if off_rack:
        snap["off_rack"] = [dict(o) for o in off_rack]
    if wishlist:
        snap["wishlist"] = [dict(w) for w in wishlist]
    return snap


def future_wishlist(parsed: dict, modules: dict, owned_counts: dict) -> list[dict]:
    """Modules on the planning rack the owner doesn't own (or owns fewer copies of), as wishlist entries."""
    want = collections.OrderedDict()
    for m in sorted(parsed["modules"], key=lambda m: (m["vendor"].lower(), m["name"].lower(), m["row"], m["col"])):
        e = want.get(m["slug"])
        if e is None:
            cfg = modules.get(m["slug"]) or {}
            e = want[m["slug"]] = dict(
                slug=m["slug"], mg_id=m.get("mg_id"), vendor=m["vendor"], name=m["name"], hp=m["hp"],
                format="1U" if m.get("is_1u") else "3U", power=m.get("power") or {}, depth_mm=m.get("depth_mm"),
                passive=m.get("passive", False), count=0, device=cfg.get("device"), role=cfg.get("role"),
                tags=cfg.get("tags") or [], parent=cfg.get("parent"),
                status=f"on the {parsed['rack']['name']} planning rack", from_rack=True)
        e["count"] += 1
    out = []
    for slug, e in want.items():
        extra = e["count"] - owned_counts.get(slug, 0)
        if extra > 0:
            out.append(dict(e, count=extra))
    return out


def merge_wishlist(auto: list[dict], manual: list[dict]) -> list[dict]:
    """Planning-rack entries plus hand-written ones; a hand-written entry with the same slug and name
    overrides fields (status, notes, device) of the rack entry, and anything else is added as is."""
    out = [dict(a) for a in auto]
    for m in manual:
        hit = next((a for a in out if a["slug"] == m["slug"] and a.get("from_rack")
                    and (m.get("name") in (None, a["name"]))), None)
        if hit:
            hit.update({k: v for k, v in m.items() if v is not None})
        else:
            out.append(dict(m, count=m.get("count", 1)))
    return out


def diff(old: dict | None, new: dict, modules: dict) -> dict:
    o = {m["slug"]: m for m in (old or {}).get("modules", [])}
    n = {m["slug"]: m for m in new["modules"]}
    added = [n[s] for s in n if s not in o]
    removed = [o[s] for s in o if s not in n]
    recount = [dict(n[s], was=o[s]["count"]) for s in n if s in o and o[s]["count"] != n[s]["count"]]
    moved = [dict(n[s], was_at=list(o[s].get("at") or [])) for s in n
             if s in o and o[s]["count"] == n[s]["count"] and sorted(o[s].get("at") or []) != sorted(n[s].get("at") or [])]
    unmapped = [n[s] for s in n if s not in modules]
    ow = {(w["slug"], w["name"]) for w in (old or {}).get("wishlist", [])}
    nw = {(w["slug"], w["name"]): w for w in new.get("wishlist", [])}
    wishlist_added = [w for k, w in nw.items() if k not in ow] if old is not None else []
    wishlist_removed = [w for w in (old or {}).get("wishlist", []) if (w["slug"], w["name"]) not in nw]
    wishlist_unmapped = [w for w in nw.values() if w.get("from_rack") and not w.get("device") and w["slug"] not in modules]
    return dict(added=added, removed=removed, recount=recount, moved=moved, unmapped=unmapped,
                wishlist_added=wishlist_added, wishlist_removed=wishlist_removed,
                wishlist_unmapped=wishlist_unmapped)


def _label(m: dict) -> str:
    return f"{m['vendor']} {m['name']}".strip()


def render_md(snap: dict, parsed: dict, modules: dict) -> str:
    r = snap["rack"]
    total = sum(m["count"] for m in snap["modules"])
    where = r.get("url") or "the rack file"
    L = [f"# Modular rack: {r['name']}", "",
         f"Snapshot of {where} (rack last modified {r['modified'] or 'unknown'}): {r['hp']} HP wide, {r['rows']} rows, "
         f"{total} modules ({len(snap['modules'])} different). Generated by `napier rack sync`; "
         "edit the rack at its source, not this file.", ""]
    rows = collections.defaultdict(list)
    for m in parsed["modules"]:
        rows[m["row"]].append(m)
    dev = {m["slug"]: m["device"] for m in snap["modules"]}
    for row in sorted(rows):
        mods = sorted(rows[row], key=lambda m: m["col"])
        kind = "1U row" if all(m["is_1u"] for m in mods) else "3U row"
        used = sum(m["hp"] for m in mods)
        L += [f"## Rack row {row} ({kind}), left to right", "",
              f"Row {row} of the {r['name']} holds {len(mods)} modules using {used} HP:", ""]
        for m in mods:
            d = dev.get(m["slug"])
            L.append(f"- at HP {m['col']}: {_label(m)}, {m['hp']} HP" + (f" (napier device `{d}`)" if d else ""))
        L.append("")
    L += ["## Modules in the rack by maker", ""]
    for m in snap["modules"]:
        rowset = sorted({a.split(",")[0] for a in m["at"]})
        n = f"{m['count']}x " if m["count"] > 1 else ""
        line = f"- {n}{_label(m)} ({m['hp']} HP, {', '.join(rowset)})"
        if m["device"]:
            line += f": napier device `{m['device']}`"
        elif (modules.get(m["slug"]) or {}).get("note"):
            line += f": {modules[m['slug']]['note']}"
        L.append(line)
    L.append("")
    if snap.get("off_rack"):
        L += ["## Owned modules not in the rack", "",
              "Owned but not placed in the rack (kept for planning; may be sold):", ""]
        for o in snap["off_rack"]:
            line = f"- {o['vendor']} {o['name']} ({o['hp']} HP)"
            if o.get("status"):
                line += f", {o['status']}"
            if o.get("device"):
                line += f": napier device `{o['device']}`"
            L.append(line)
        L.append("")
    if snap.get("wishlist"):
        src = snap.get("wishlist_rack")
        intro = f"Modules {paths.owner()} does not own: planned or considered purchases, indexed for planning and comparison"
        if src:
            intro += f" (from the {src['name']} planning rack" + (f", {src['url']}" if src.get("url") else "") + \
                ", plus hand-written entries)"
        L += ["## Wishlist (not owned)", "", intro + ":", ""]
        for w in snap["wishlist"]:
            line = f"- {w['vendor']} {w['name']} ({w['hp']} HP), not owned"
            if w.get("status"):
                line += f", {w['status']}"
            if w.get("device"):
                line += f": napier device `{w['device']}`"
            L.append(line)
        L.append("")
    return "\n".join(L)


def rack_settings(cfg: dict) -> tuple[str, dict, dict | None]:
    """(source name, rack settings, planning settings or None) from racks/devices.yaml. Older files with
    `rack_url` / `wishlist_url` and no `rack_source` read as {url: ...} for whatever source is named."""
    name = cfg.get("rack_source") or rack_sources.BUILTIN
    rack = dict(cfg.get("rack") or {})
    if cfg.get("rack_url") and "url" not in rack:
        rack["url"] = cfg["rack_url"]
    planning = dict(cfg["planning"]) if cfg.get("planning") else None
    if planning is None and cfg.get("wishlist_url"):
        planning = dict(url=cfg["wishlist_url"])
    return name, rack, planning


def sync(write: bool = True, log=None, settings: dict | None = None, planning_settings: dict | None = None) -> dict:
    """Read the rack from its rack source, snapshot, diff against the last snapshot, and write the files.
    With a `planning` rack configured, also read it and fold the modules the owner doesn't own into the
    wishlist. `settings` / `planning_settings` add to (override) the configured ones, e.g. a saved page
    for a plug-in to read. Returns dict(changed, added, removed, recount, unmapped, wishlist_added,
    wishlist_removed, wishlist_unmapped, wishlist_error, snapshot_file, notes_file)."""
    if paths.using_examples() and write:
        raise PermissionError("no rack of your own is set up: create local/racks/devices.yaml "
                              "(start from examples/racks), or set NAPIER_RACKS")
    cfg = load_config()
    name, rset, pset = rack_settings(cfg)
    rset.update(settings or {})
    if pset is not None or planning_settings:
        pset = dict(pset or {}, **(planning_settings or {}))
    src = rack_sources.get(name)
    parsed = src.read(rset, racks_dir())
    url = rset.get("url") or ""
    snap = snapshot(parsed, cfg["modules"], url, cfg["off_rack"])
    slug = re.sub(r"[^a-z0-9]+", "_", parsed["rack"]["name"].lower()).strip("_") or parsed["rack"]["id"]
    snap_file = racks_dir() / f"{slug}.yaml"
    if snap_file.name in CONFIG_FILES or (snap_file.exists() and snap_file not in snapshot_files()):
        snap_file = racks_dir() / f"snapshot_{slug}.yaml"      # never overwrite a hand-written file
    prev = snap_file if snap_file.exists() else next(iter(snapshot_files()), None)   # renamed: the last one
    old = yaml.safe_load(prev.read_text()) if prev else None
    auto, wishlist_error = [], None
    if pset:
        try:
            if url and pset.get("url"):
                time.sleep(2)                                   # polite: space requests to one host
            wparsed = src.read(pset, racks_dir())
            owned = collections.Counter()
            for m in snap["modules"]:
                owned[m["slug"]] += m["count"]
            for o in cfg["off_rack"]:
                owned[o["slug"]] += 1
            auto = future_wishlist(wparsed, cfg["modules"], owned)
            snap["wishlist_rack"] = dict(wparsed["rack"], url=pset.get("url") or "")
        except Exception as e:  # noqa: BLE001  keep the last known planning-rack entries
            wishlist_error = f"{type(e).__name__}: {e}"
            auto = [w for w in (old or {}).get("wishlist", []) if w.get("from_rack")]
            if (old or {}).get("wishlist_rack"):
                snap["wishlist_rack"] = old["wishlist_rack"]  # type: ignore[index]
    wl = merge_wishlist(auto, cfg["wishlist"])
    if wl:
        snap["wishlist"] = wl
    d = diff(old, snap, cfg["modules"])
    text = f"{GENERATED}. Edit the rack at its source, not this file.\n" + \
        yaml.safe_dump(snap, sort_keys=False, allow_unicode=True, width=120)
    md = render_md(snap, parsed, cfg["modules"])
    from napier import scenarios as scenmod
    problems = scenmod.resolve({}, snap["modules"], dict(snap["rack"], geometry=geometry_spec()))["problems"]
    notes_file = notes_dir() / "rack.md"
    changed = (not snap_file.exists() or snap_file.read_text() != text
               or not notes_file.exists() or notes_file.read_text() != md)
    stale = [f for f in snapshot_files() if f.resolve() != snap_file.resolve()]
    if write and (changed or stale):
        snap_file.parent.mkdir(parents=True, exist_ok=True)
        snap_file.write_text(text)
        notes_file.parent.mkdir(parents=True, exist_ok=True)
        notes_file.write_text(md)
        for f in stale:                      # the rack was renamed: one snapshot, so every command reads this one
            f.unlink()
    if log:
        for f in stale:
            log(f"removed  the old snapshot {f.name} (the rack's name changed)")
        for m in d["moved"]:
            log(f"moved    {_label(m)} ({m['slug']}): {'; '.join(m['was_at'])} -> {'; '.join(m['at'])}")
        for pr in problems:
            log(f"problem  {pr}")
        for k in ("added", "removed", "recount", "unmapped", "wishlist_added", "wishlist_removed", "wishlist_unmapped"):
            for m in d[k]:
                log(f"{k:8s} {_label(m)} ({m['slug']})")
        if wishlist_error:
            log(f"planning rack not read ({wishlist_error}); kept the last snapshot's entries")
    return dict(changed=changed, snapshot_file=str(snap_file), notes_file=str(notes_file),
                wishlist_error=wishlist_error, source=name, problems=problems,
                removed_snapshots=[f.name for f in stale], **d)


GENERATED = "# Generated by `napier rack sync`"


def snapshot_files() -> list[Path]:
    """Snapshots `rack sync` wrote (they start with the GENERATED line), newest first."""
    out = []
    for f in racks_dir().glob("*.yaml"):
        if f.name not in CONFIG_FILES:
            with open(f, encoding="utf-8") as fh:
                if fh.readline().startswith(GENERATED):
                    out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime, reverse=True)


def load_snapshot() -> dict | None:
    """The snapshot sync wrote last (or, failing that, the first other racks/*.yaml, for hand-made ones)."""
    gen = snapshot_files()
    for f in gen[:1] or sorted(racks_dir().glob("*.yaml")):
        if f.name not in CONFIG_FILES:
            snap = yaml.safe_load(f.read_text()) or {}
            spec = geometry_spec()
            if spec and isinstance(snap.get("rack"), dict):
                snap["rack"]["geometry"] = spec
            return snap
    return None


def export(include_wishlist: bool = False) -> dict:
    """Everything a rack planner needs, from files only (no fetch): each owned module with its
    rack-source specs, manual-cited power and jacks (from specs/), napier docs, role and tags.
    `napier rack view` draws from it. Every entry carries `owned`; wishlist modules
    (owned: false) are only included when include_wishlist is set, so nothing plans them as owned."""
    from napier import specs as specmod
    from napier.sources import load_sources
    snap = load_snapshot()
    if not snap:
        raise ValueError(f"no rack snapshot in {racks_dir()} yet (run `napier rack sync`)")
    cfg = load_config()
    usage = load_usage()
    docs = collections.defaultdict(list)
    order = {"manual": 0, "changelog": 1, "note": 2, "code": 3, "community": 4}
    for s in sorted(load_sources(), key=lambda s: order.get(s.kind, 9)):
        docs[s.device].append(dict(id=s.id, kind=s.kind, title=s.title, version=s.version))
    specs = specmod.by_slug()
    mods = [dict(m, racked=True, owned=True) for m in snap["modules"]]
    for o in cfg["off_rack"]:
        mods.append(dict(o, count=1, at=[], parent=o.get("parent"), passive=o.get("passive", False), racked=False,
                         owned=True))
    if include_wishlist:
        for w in (snap.get("wishlist") if "wishlist" in snap else cfg["wishlist"]):  # type: ignore[union-attr]
            mods.append(dict(w, count=w.get("count", 1), at=[], parent=w.get("parent"),
                             passive=w.get("passive", False), racked=False, owned=False))
    out = []
    for m in mods:
        e = {k: m.get(k) for k in ("slug", "mg_id", "vendor", "name", "count", "racked", "hp", "format", "depth_mm",
                                   "passive", "device", "role", "tags", "parent", "at", "status", "owned")}
        e["power"] = m.get("power") or {}
        s = specs.get(m["slug"])  # type: ignore[assignment]
        if s:
            pw = s.get("power") or {}  # type: ignore[attr-defined]
            e["power_manual"] = {k: pw.get(k) for k in specmod.RAILS + ("page",)} if pw else None
            e["spec_source"] = s.get("source")  # type: ignore[attr-defined]
            e["jacks"] = s.get("jacks") or []  # type: ignore[attr-defined]
            e["io"] = specmod.io_counts(s)  # type: ignore[arg-type]
        else:
            e["power_manual"], e["spec_source"], e["jacks"], e["io"] = None, None, [], {}
        e["docs"] = docs.get(m.get("device"), []) if m.get("device") else []  # type: ignore[arg-type]
        e["usage"] = usage["modules"].get(m["slug"])
        out.append(e)
    racked = [e for e in out if e.get("racked") and e.get("owned")]
    pool = list(out)
    if not include_wishlist:
        for w in (snap.get("wishlist") if "wishlist" in snap else cfg["wishlist"]):  # type: ignore[union-attr]
            pool.append(dict(w, at=[], owned=False))
    return dict(rack=snap["rack"], title=paths.rack_title() or snap["rack"].get("name") or "Rack",
                owner=str(paths.config().get("owner") or ""),
                modules=out, usage_stance=usage["stance"], usage_rules=usage["rules"],
                usage_cases=usage["cases"], challenges=load_challenges(),
                case_power=case_power(racked, snap["rack"], usage["cases"]),
                power_mismatches=specmod.compare(snap["modules"]),
                geometry=rack_geometry(snap["rack"]),
                problems=_actual_problems(racked, snap["rack"]),   # in the actual rack
                scenarios=scenarios_with_checks(pool, snap["rack"], usage))


def _actual_problems(racked: list[dict], rack: dict) -> list[str]:
    from napier import scenarios as scenmod
    return scenmod.resolve({}, racked, rack)["problems"]


def scenarios_with_checks(pool: list[dict], rack: dict, usage: dict) -> dict:
    """Resolve every scenario and attach planner checks: power per case against the supplies,
    pairs_with/keep_near distances and free space per case row (scenarios.checks)."""
    from napier import scenarios as scenmod
    draw: dict[str, dict] = {}
    for e in pool:
        if e["slug"] in draw and not e.get("at"):
            continue
        mg, man = e.get("power") or {}, e.get("power_manual") or {}
        draw[e["slug"]] = {k: max(_int(mg.get(k)) or 0, _int(man.get(k)) or 0) for k in RAILS}
    out = scenmod.resolve_all(pool, rack, usage["modules"])
    for s in out.values():
        s["checks"] = scenmod.checks(s, draw, rack, usage["modules"], usage["cases"])
    return out


def load_usage() -> dict:
    """racks/usage.yaml, normalised: {stance, rules: [...], cases: {...}, modules: {slug: {...}}}.

    Everything here is a working default, not a constraint: `stance` says so in the owner's terms. Rules,
    case modes and keep_near are there to be challenged with a clear hypothesis for an alternative.

    rules: rack-wide placement and patching rules, each {id, text, modules: [slugs]}.
    cases: per case (top-left, top-right, bottom-left, bottom-right): `power` (supply, as text),
      `limits` (the supply's rail capacity in mA: plus12, minus12, plus5; the viewer and `rack scenarios` read these), `mode`
      (what the case is for, in the owner's words), `layout` (row-by-row intent), `notes`, `open`.
    modules: keyed by module slug (as in devices.yaml and the catalog), each with
      job        what the module does in the rig, in the owner's terms
      status     anchor (never fire) | keep | candidate (could go) | leaving (being sold) |
                 planned (buying, not owned yet) | considered (not owned, maybe someday)
      pairs_with modules it's normally patched with (slugs)
      keep_near  modules the owner prefers it next to (slugs); a soft preference; `rack scenarios` reports how far apart they sit
      distance_ok  partners whose distance the owner has accepted (slugs): `rack scenarios` lists those pairs as
                 accepted instead of flagging them as far apart
      notes      anything else the owner has said about it
      open       questions not yet answered; ask the owner, never fill these in by guessing"""
    f = racks_dir() / "usage.yaml"
    raw = (yaml.safe_load(f.read_text()) if f.exists() else None) or {}
    mods = {}
    for slug, v in (raw.get("modules") or {}).items():
        v = dict(v or {})
        e = dict(job=v.get("job"), status=v.get("status"))
        for k in USAGE_LISTS:
            e[k] = list(v.get(k) or [])
        mods[slug] = e
    cases = {}
    for name, v in (raw.get("cases") or {}).items():
        v = dict(v or {})
        lim = v.get("limits")
        e = dict(power=v.get("power"), limits=dict(lim) if isinstance(lim, dict) else lim, mode=v.get("mode"))
        for k in CASE_LISTS:
            e[k] = list(v.get(k) or [])
        cases[name] = e
    return dict(stance=raw.get("stance"), rules=list(raw.get("rules") or []), cases=cases, modules=mods)


def geometry_spec() -> dict | None:
    """racks/devices.yaml `geometry:` (how the rack splits into cases; see scenarios.geometry)."""
    f = racks_dir() / "devices.yaml"
    cfg = (yaml.safe_load(f.read_text()) if f.exists() else {}) or {}
    return cfg.get("geometry")


def rack_geometry(rack: dict) -> dict:
    from napier import scenarios as scenmod
    return scenmod.geometry(rack, rack.get("geometry") or geometry_spec())


def case_names(rack: dict | None = None) -> list[str]:
    """The rack's case names in reading order (from the snapshot's rack when none is given)."""
    if rack is None:
        snap = load_snapshot()
        rack = (snap or {}).get("rack") or {}
    return rack_geometry(rack)["order"]


def case_of(at: str, rack: dict) -> str | None:
    """'row 5, hp 105' -> the case it falls in ('bottom-right' on a 2x2 grid)."""
    from napier import scenarios as scenmod
    m = re.match(r"row (\d+), hp (\d+)", at or "")
    if not m or not rack.get("rows") or not rack.get("hp"):
        return None
    return scenmod.case_at(rack_geometry(rack), int(m.group(1)), int(m.group(2)))


def case_power(modules: list[dict], rack: dict, cases: dict) -> dict:
    """Per-case load vs. supply limits. Each racked copy counts once at its position; each rail uses
    the larger of the manual and rack-source figures (the same conservative rule the scenario checks and viewer use)."""
    out = {c: dict(load={k: 0 for k in RAILS}, limits=(cases.get(c) or {}).get("limits"), modules=0)
           for c in case_names(rack)}
    for m in modules:
        mg, man = m.get("power") or {}, m.get("power_manual") or {}
        draw = {k: max(int(mg.get(k) or 0), int(man.get(k) or 0)) for k in RAILS}
        for at in m.get("at") or []:
            c = case_of(at, rack)
            if c not in out:
                continue
            out[c]["modules"] += 1  # type: ignore[operator]
            for k in RAILS:
                out[c]["load"][k] += draw[k]  # type: ignore[index]
    for e in out.values():
        lim = e["limits"] if isinstance(e["limits"], dict) else {}
        e["pct"] = {k: round(e["load"][k] / lim[k] * 100) for k in RAILS if lim.get(k)}  # type: ignore[index]
    return out


def load_challenges() -> list[dict]:
    """racks/challenges.yaml: the log of challenges to rack defaults and the owner's responses (hand-written).
    Each entry: id, date, kind (layout | swap | role | purchase | sale), title, default, hypothesis, evidence, costs,
    test, confidence, outcome (open | testing | accepted | partial | rejected), response (the owner's reason), learned,
    modules (slugs).
    Read it before proposing a challenge; a rejected one needs new evidence to come back."""
    f = racks_dir() / "challenges.yaml"
    raw = (yaml.safe_load(f.read_text()) if f.exists() else None) or {}
    out = []
    for c in raw.get("challenges") or []:
        c = dict(c or {})
        e = {k: c.get(k) for k in CHALLENGE_FIELDS}
        e["date"] = str(e["date"]) if e["date"] else None
        e["modules"] = list(c.get("modules") or [])
        out.append(e)
    return out


def check_challenges(challenges: list | None = None, slugs=None) -> list[str]:
    """Problems in challenges.yaml: missing or duplicate ids, a bad outcome, unknown module slugs."""
    challenges = load_challenges() if challenges is None else challenges
    slugs = known_slugs() if slugs is None else slugs
    probs, seen = [], set()
    for i, c in enumerate(challenges):
        cid = c.get("id") or f"[{i}]"
        if not c.get("id") or not c.get("title"):
            probs.append(f"challenges.{cid}: needs id and title")
        if c.get("id") in seen:
            probs.append(f"challenges.{cid}: duplicate id")
        seen.add(c.get("id"))
        if c.get("outcome") not in CHALLENGE_OUTCOMES:
            probs.append(f"challenges.{cid}: outcome {c.get('outcome')!r} is not one of {', '.join(CHALLENGE_OUTCOMES)}")
        if c.get("kind") and c["kind"] not in CHALLENGE_KINDS:
            probs.append(f"challenges.{cid}: kind {c['kind']!r} is not one of {', '.join(CHALLENGE_KINDS)}")
        probs += [f"challenges.{cid}: unknown slug {s}" for s in c["modules"] if s not in slugs]
    return probs


def known_slugs() -> dict:
    """slug -> display name for every module napier knows: racked, off-rack and wishlist."""
    snap = load_snapshot() or {}
    cfg = load_config()
    out = {}
    for m in list(snap.get("modules") or []) + list(cfg["off_rack"]) + \
            list(snap.get("wishlist") if "wishlist" in snap else cfg["wishlist"]):  # type: ignore[arg-type]
        if m.get("slug"):
            out.setdefault(m["slug"], f"{m.get('vendor') or ''} {m.get('name') or m['slug']}".strip())
    return out


def check_usage(usage: dict | None = None, slugs=None) -> list[str]:
    """Problems in usage.yaml: slugs napier doesn't know, a bad status, rules missing id/text."""
    usage = usage or load_usage()
    slugs = known_slugs() if slugs is None else slugs
    probs = []
    for slug, u in usage["modules"].items():
        if slug not in slugs:
            probs.append(f"modules.{slug}: not a racked, off-rack or wishlist module")
        if u["status"] and u["status"] not in USAGE_STATUS:
            probs.append(f"modules.{slug}: status {u['status']!r} is not one of {', '.join(USAGE_STATUS)}")
        for k in ("pairs_with", "keep_near", "distance_ok"):
            probs += [f"modules.{slug}.{k}: unknown slug {s}" for s in u[k] if s not in slugs]
    snap = load_snapshot()
    if snap:
        names = case_names(snap["rack"])
        probs += [f"cases.{c}: not one of the rack's cases ({', '.join(names)}; set `geometry:` in devices.yaml)"
                  for c in usage.get("cases", {}) if c not in names]
    for c, e in usage.get("cases", {}).items():
        lim = e.get("limits")
        if lim is None:
            continue
        if not isinstance(lim, dict):
            probs.append(f"cases.{c}.limits: should map {', '.join(RAILS)} to mA")
            continue
        for k, v in lim.items():
            if k not in RAILS:
                probs.append(f"cases.{c}.limits: unknown rail {k} (use {', '.join(RAILS)})")
            elif not isinstance(v, int) or v <= 0:
                probs.append(f"cases.{c}.limits.{k}: {v!r} is not a positive mA value")
    for i, r in enumerate(usage["rules"]):
        if not (r.get("id") and r.get("text")):
            probs.append(f"rules[{i}]: needs id and text")
        probs += [f"rules.{r.get('id')}: unknown slug {s}" for s in (r.get("modules") or []) if s not in slugs]
    return probs


def render_usage_md(usage: dict, names: dict, challenges: list | None = None) -> str:
    """notes/rack-usage.md: usage.yaml as prose, so search can answer 'how does the owner use X'."""
    nm = lambda s: names.get(s, s)
    who = paths.owner()
    Who = who[:1].upper() + who[1:]
    L = [f"# How {who} uses the modular rack", "",
         f"Written from racks/usage.yaml (hand-maintained with {who}). Each module's job in the rig, what it "
         f"pairs with, what {who} likes it near, and whether it could ever leave. Lines under 'Not settled yet' "
         "are open questions, not facts.", ""]
    if usage.get("stance"):
        L += ["## How to treat this", "", usage["stance"].strip(), ""]
    if usage["rules"]:
        L += ["## Working defaults (challengeable)", ""]
        for r in usage["rules"]:
            mods = ", ".join(nm(s) for s in r.get("modules") or [])  # type: ignore[misc]
            L.append(f"- {r['text']}" + (f" (modules: {mods})" if mods else ""))
        L.append("")
    if usage.get("cases"):
        order = case_names()
        L += ["## The cases" if len(order) > 1 else "## The case", ""]
        for c in list(order) + [c for c in usage["cases"] if c not in order]:
            e = usage["cases"].get(c)
            if not e:
                continue
            L.append(f"### {c.replace('-', ' ').capitalize()} case" + (f" ({e['power']})" if e["power"] else ""))
            L.append("")
            if e["mode"]:
                L.append(f"Mode: {e['mode']}.".replace("..", "."))
            if isinstance(e.get("limits"), dict):
                L.append("Supply limits: " + ", ".join(f"{RAIL_LABELS[k]} {e['limits'][k]}mA"
                                                       for k in RAILS if k in e["limits"]) + ".")
            L += [f"- {x}" for x in e["layout"] + e["notes"]]
            if e["open"]:
                L.append("- Not settled yet: " + "; ".join(e["open"]))
            L.append("")
    label = dict(anchor="Never firing", keep="Keeping", candidate="Could go", leaving="Leaving the rack",
                 planned="Planned purchases (not owned yet)", considered="Considered (not owned)",
                 unset="Not classified yet")
    groups = collections.defaultdict(list)
    for slug, u in usage["modules"].items():
        groups[u["status"] or "unset"].append((nm(slug), u))
    for st in USAGE_STATUS + ("unset",):
        if not groups.get(st):
            continue
        L += [f"## {label[st]}", ""]
        for name, u in sorted(groups[st], key=lambda x: x[0].lower()):  # type: ignore[union-attr]
            line = f"- {name}: {u['job'] or 'job not recorded yet'}."
            if u["pairs_with"]:
                line += f" Pairs with {', '.join(nm(s) for s in u['pairs_with'])}."  # type: ignore[misc]
            if u["keep_near"]:
                line += f" Keep near {', '.join(nm(s) for s in u['keep_near'])}."  # type: ignore[misc]
            if u["notes"]:
                line += " " + " ".join(n.rstrip(".") + "." for n in u["notes"])
            L.append(line.replace("..", "."))
            if u["open"]:
                L.append("  - Not settled yet: " + "; ".join(u["open"]))
        L.append("")
    if challenges:
        L += ["## Challenge log", "",
              f"Challenges to these defaults and {who}'s responses, oldest first. A rejected challenge needs "
              "new evidence before it comes back.", ""]
        for c in challenges:
            meta = ", ".join(x for x in (c["date"] or "undated", c.get("kind"), c["outcome"]) if x)
            head = f"- {c['id']} ({meta}): {c['title']}."
            parts = [head]
            if c.get("hypothesis"):
                parts.append(f"Hypothesis: {c['hypothesis'].rstrip('.')}.")
            if c.get("evidence"):
                parts.append(f"Evidence: {c['evidence'].rstrip('.')}.")
            if c.get("response"):
                parts.append(f"{Who}: {c['response'].rstrip('.')}.")
            if c.get("learned"):
                parts.append(f"Learned: {c['learned'].rstrip('.')}.")
            L.append(" ".join(parts))
        L.append("")
    return "\n".join(L)


def write_usage_md() -> tuple[Path, bool]:
    """Write notes/rack-usage.md; returns (path, changed)."""
    out = notes_dir() / "rack-usage.md"
    text = render_usage_md(load_usage(), known_slugs(), load_challenges())
    changed = not out.exists() or out.read_text() != text
    if changed:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return out, changed
