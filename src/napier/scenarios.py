"""What-if rack layouts: racks/scenarios/*.yaml (hand-written, one file per scenario).

A scenario starts from the actual rack (the rack snapshot) and says what changes:

    name: Planned (Core + ceithir)
    date: 2026-10-10
    description: one line on what this layout is for
    remove: [squarp-instruments-hermod-5v-mode, wmd-metron-black]
    place:
      - slug: squarp-instruments-core
        at: ["row 5, hp 71"]
      - slug: intellijel-stereo-line-out-1u      # `at` lists every copy's position in the scenario
        at: ["row 4, hp 177", "row 1, hp 1"]
    notes: [anything worth remembering about this layout]

`place` sets the full position list for that module (moving it, adding copies, or bringing in a
module from the off-rack or wishlist lists). `remove` takes every copy out. Modules not mentioned keep
their actual positions. resolve() checks the result: unknown modules, positions off the rack, a module
crossing the seam between two cases, 1U modules in 3U rows (and the reverse) and overlaps.

Scenarios are working drafts for theoretical builds, not decisions: the challenge log records decisions.
`napier rack view` draws them. checks() adds what a planner wants to see for a layout: power per case
against the supplies, how far each `pairs_with`/`keep_near` pair sits apart, and free space per case row.
"""
from __future__ import annotations

import re

import yaml

AT_RE = re.compile(r"row\s*(\d+)\s*,\s*hp\s*(\d+)", re.IGNORECASE)


def scenarios_dir():
    from napier.rack import racks_dir
    return racks_dir() / "scenarios"


def parse_at(at) -> tuple[int, int] | None:
    m = AT_RE.search(str(at or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _case_names(across: int, down: int) -> list[str]:
    """Row-major case names: 'main' for one case, left/right and top/bottom words up to 2x2, else r1c1..."""
    if across == 1 and down == 1:
        return ["main"]
    h = ["left", "right"] if across == 2 else [f"c{i}" for i in range(1, across + 1)]
    v = ["top", "bottom"] if down == 2 else [f"r{i}" for i in range(1, down + 1)]
    if down == 1:
        return h
    if across == 1:
        return v
    return [f"{a}-{b}" if across == 2 and down == 2 else f"{a}{b}" for a in v for b in h]


def geometry(rack: dict, spec: dict | None = None) -> dict:
    """The rack as a grid of cases. `spec` (racks/devices.yaml `geometry:`, or rack["geometry"]):

        grid: [2, 2]            cases across, cases down (default [1, 1]: the whole rack is one case)
        case_rows: [1U, 3U, 3U] each case's rows, top to bottom (default: every row 3U)
        names: [...]            optional case names, row-major (default: main; left/right; top-left...)

    Rows run 1..rows from the top across all cases; columns 1..hp from the left. Cases split the width
    evenly. A spec that doesn't fit the rack's rows falls back to one case."""
    spec = dict(spec or rack.get("geometry") or {})
    rows, width = int(rack.get("rows") or 0), int(rack.get("hp") or 0)
    across, down = (list(spec.get("grid") or [1, 1]) + [1, 1])[:2]
    across, down = max(int(across), 1), max(int(down), 1)
    per_case = rows // down if rows else 0
    fmts = [str(x).upper() for x in (spec.get("case_rows") or [])]
    if not fmts or len(fmts) != per_case or per_case * down != rows:
        if fmts and per_case * down == rows and rows:
            fmts = []  # wrong length: ignore the formats, keep the grid
        if not rows or per_case * down != rows:
            across, down, per_case = 1, 1, rows
        fmts = fmts or ["3U"] * per_case
    fmt = {r: fmts[(r - 1) % per_case] for r in range(1, rows + 1)} if per_case else {}
    case_hp = width // across if across else width
    names = [str(n) for n in (spec.get("names") or [])]
    if len(names) != across * down:
        names = _case_names(across, down)
    cases, i = {}, 0
    for vi in range(down):
        for hi in range(across):
            hp_hi = width if hi == across - 1 else (hi + 1) * case_hp
            cases[names[i]] = dict(rows=list(range(vi * per_case + 1, (vi + 1) * per_case + 1)),
                                   hp=[hi * case_hp + 1, hp_hi])
            i += 1
    return dict(rows=rows, hp=width, case_hp=case_hp, grid=[across, down], row_format=fmt, cases=cases,
                order=list(cases))


def load_scenarios() -> dict:
    """{id: raw dict} for every racks/scenarios/*.yaml; id is the file stem."""
    d = scenarios_dir()
    out = {}
    if d.is_dir():
        for f in sorted(d.glob("*.yaml")):
            out[f.stem] = yaml.safe_load(f.read_text()) or {}
    return out


def _meta(m: dict, usage: dict) -> dict:
    u = (usage or {}).get(m["slug"]) or {}
    return dict(slug=m["slug"], name=m.get("name"), vendor=m.get("vendor"), hp=int(m.get("hp") or 0),
                format=m.get("format"), role=m.get("role"), owned=bool(m.get("owned")),
                status=u.get("status"))


def resolve(scn: dict, modules: list[dict], rack: dict, usage: dict | None = None) -> dict:
    """Apply a scenario to the actual rack. `modules` is every module napier knows (racked, off-rack and
    wishlist); the first entry per slug supplies name, HP and format. Returns
    dict(name, date, description, notes, modules=[...], removed=[...], problems=[...]) where each module
    carries `at` (its scenario positions) and `change`: kept | moved | new."""
    geo = geometry(rack)
    by_slug: dict[str, dict] = {}
    actual: dict[str, list[tuple[int, int]]] = {}
    for m in modules:
        by_slug.setdefault(m["slug"], m)
        for a in m.get("at") or []:
            p = parse_at(a)
            if p:
                actual.setdefault(m["slug"], []).append(p)
        if m.get("at") and m["slug"] in by_slug and not by_slug[m["slug"]].get("at"):
            by_slug[m["slug"]] = m      # prefer the racked entry's specs over a wishlist duplicate
    problems: list[str] = []
    pos = {s: list(v) for s, v in actual.items()}
    for s in scn.get("remove") or []:
        if s not in by_slug:
            problems.append(f"remove: unknown module {s}")
        pos.pop(s, None)
    for p in scn.get("place") or []:
        s = (p or {}).get("slug")
        if s not in by_slug:
            problems.append(f"place: unknown module {s}")
            continue
        ats = []
        for a in p.get("at") or []:
            xy = parse_at(a)
            if xy is None:
                problems.append(f"{s}: can't read position {a!r} (use 'row N, hp N')")
            else:
                ats.append(xy)
        pos[s] = ats
    out, occupied = [], {}
    for s, ats in pos.items():
        if not ats:
            continue
        m = by_slug[s]
        e = _meta(m, usage)  # type: ignore[arg-type]
        w = e["hp"]
        before = sorted(actual.get(s, []))
        e["change"] = "kept" if sorted(ats) == before else ("new" if not before else "moved")
        e["at"] = [f"row {r}, hp {h}" for r, h in ats]
        for r, h in ats:
            where = f"{e['name']} at row {r}, hp {h}"
            if not 1 <= r <= geo["rows"]:
                problems.append(f"{where}: no such row (rack has {geo['rows']})")
                continue
            if h < 1 or h + w - 1 > geo["hp"]:
                problems.append(f"{where}: runs off the rack ({w} HP, rack is {geo['hp']} wide)")
            elif h <= geo["case_hp"] < h + w - 1:
                problems.append(f"{where}: crosses the seam between the left and right cases")
            rf = geo["row_format"].get(r)
            if e["format"] in ("1U", "3U") and rf and e["format"] != rf:
                problems.append(f"{where}: a {e['format']} module in a {rf} row")
            for c in range(h, h + w):
                other = occupied.get((r, c))
                if other and other != where:
                    problems.append(f"{where} overlaps {other}")
                    break
                occupied[(r, c)] = where
        out.append(e)
    removed = []
    for s, before in actual.items():
        now = pos.get(s) or []
        if len(now) < len(before):
            e = _meta(by_slug[s], usage)  # type: ignore[arg-type]
            e["at"] = [f"row {r}, hp {h}" for r, h in before if (r, h) not in now]
            removed.append(e)
    out.sort(key=lambda e: [parse_at(a) for a in e["at"]])
    return dict(name=scn.get("name"), date=str(scn.get("date") or ""), description=scn.get("description"),
                notes=list(scn.get("notes") or []), modules=out, removed=removed,
                problems=list(dict.fromkeys(problems)))


def resolve_all(modules: list[dict], rack: dict, usage: dict | None = None) -> dict:
    return {sid: resolve(raw, modules, rack, usage) for sid, raw in load_scenarios().items()}


# Physical sizes for distance checks. Intellijel 1U tiles are 39.65 mm tall, Eurorack 3U panels 128.5 mm;
# one HP is 5.08 mm. Distances are Manhattan (row centre to row centre, plus the HP gap between edges).
ROW_CM = {"1U": 3.965, "3U": 12.85}
HP_CM = 0.508
RAILS = ("plus12", "minus12", "plus5")


def case_at(geo: dict, row: int, hp: int) -> str | None:
    for name, c in geo["cases"].items():
        if row in c["rows"] and c["hp"][0] <= hp <= c["hp"][1]:
            return name
    return None


def _row_centres(geo: dict) -> dict[int, float]:
    y, out = 0.0, {}
    for r in range(1, geo["rows"] + 1):
        h = ROW_CM.get(geo["row_format"].get(r), ROW_CM["3U"])
        out[r] = y + h / 2
        y += h
    return out


def checks(res: dict, power: dict, rack: dict, usage: dict | None = None, cases: dict | None = None,
           far_cm: float = 20.0, min_gap: int = 2) -> dict:
    """Planner checks for one resolved scenario.

    power: {slug: {plus12, minus12, plus5}} per copy (the conservative draw). usage: usage.yaml modules
    (for pairs_with/keep_near). cases: usage.yaml cases (for supply limits). Returns
      power      {case: {load, limits, pct}}
      pairs      every pair placed in the scenario, farthest first: a, b, cm, cross_case, keep_near, accepted,
                 a_at, b_at (accepted: either side lists the other in usage `distance_ok`)
      far_pairs  pairs farther than far_cm or in different cases, not accepted
      accepted_far  pairs that would be far but whose distance the owner has accepted
      free       {case: {row: [[from, to], ...]}} free HP blocks of at least min_gap
      fragmented ["case row N: a-b, c-d"] case rows with more than one such block
      warnings   readable lines for anything over a supply limit or at 90% and up
    """
    geo = geometry(rack)
    yc = _row_centres(geo)
    spans: dict[str, list[tuple[int, int, int]]] = {}
    names = {}
    for m in res["modules"]:
        names[m["slug"]] = m.get("name") or m["slug"]
        for a in m["at"]:
            p = parse_at(a)
            if p:
                spans.setdefault(m["slug"], []).append((p[0], p[1], p[1] + int(m.get("hp") or 0) - 1))
    # power per case
    load = {c: {k: 0 for k in RAILS} for c in geo["cases"]}
    for s, ats in spans.items():
        d = power.get(s) or {}
        for r, h, _ in ats:
            c = case_at(geo, r, h)
            if c:
                for k in RAILS:
                    load[c][k] += int(d.get(k) or 0)
    pw, warnings = {}, []
    for c, ld in load.items():
        lim = ((cases or {}).get(c) or {}).get("limits") or {}
        pct = {k: round(100 * ld[k] / lim[k]) for k in RAILS if lim.get(k)}
        pw[c] = dict(load=ld, limits=lim, pct=pct)
        for k, v in pct.items():
            if v > 100:
                warnings.append(f"{c} {k}: {ld[k]} mA is over the {lim[k]} mA supply ({v}%)")
            elif v >= 90:
                warnings.append(f"{c} {k}: {ld[k]} of {lim[k]} mA ({v}%), low headroom")
    # pair distances
    pairs, seen = [], set()
    for s, ats in spans.items():
        u = (usage or {}).get(s) or {}
        for o in list(u.get("pairs_with") or []) + list(u.get("keep_near") or []):
            if o == s or o not in spans or frozenset((s, o)) in seen:
                continue
            seen.add(frozenset((s, o)))
            best = None
            for a in ats:
                for b in spans[o]:
                    gap = max(0, max(a[1], b[1]) - min(a[2], b[2]) - 1)
                    d = abs(yc[a[0]] - yc[b[0]]) + gap * HP_CM
                    if best is None or d < best[0]:
                        best = (d, a, b)
            d, a, b = best  # type: ignore[misc]
            kn = o in (u.get("keep_near") or []) or s in ((((usage or {}).get(o) or {}).get("keep_near")) or [])
            ok = o in (u.get("distance_ok") or []) or s in ((((usage or {}).get(o) or {}).get("distance_ok")) or [])
            pairs.append(dict(a=s, b=o, a_name=names[s], b_name=names[o], cm=round(d, 1),
                              cross_case=case_at(geo, a[0], a[1]) != case_at(geo, b[0], b[1]), keep_near=kn, accepted=ok,
                              a_at=f"row {a[0]}, hp {a[1]}", b_at=f"row {b[0]}, hp {b[1]}"))
    pairs.sort(key=lambda p: -p["cm"])
    far_all = [p for p in pairs if p["cm"] > far_cm or p["cross_case"]]
    far = [p for p in far_all if not p["accepted"]]
    accepted_far = [p for p in far_all if p["accepted"]]
    # free space per case row
    occ = set()
    for ats in spans.values():
        for r, h0, h1 in ats:
            occ.update((r, c) for c in range(h0, h1 + 1))
    free, fragmented = {}, []
    for name, c in geo["cases"].items():
        for r in c["rows"]:
            blocks, start = [], None
            for col in range(c["hp"][0], c["hp"][1] + 2):
                empty = col <= c["hp"][1] and (r, col) not in occ
                if empty and start is None:
                    start = col
                if not empty and start is not None:
                    if col - start >= min_gap:
                        blocks.append([start, col - 1])
                    start = None
            if blocks:
                free.setdefault(name, {})[r] = blocks
            if len(blocks) > 1:
                fragmented.append(f"{name} row {r}: " + ", ".join(f"{a}-{b}" for a, b in blocks))
    return dict(power=pw, pairs=pairs, far_pairs=far, accepted_far=accepted_far, free=free, fragmented=fragmented,
                warnings=warnings)
