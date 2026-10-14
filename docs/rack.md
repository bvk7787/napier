# The rack planner

napier's rack commands keep your Eurorack rack next to the manuals: what's racked, how you use each
module, power per case, and what-if layouts checked before you move anything. Everything here is
plain YAML in a racks folder: `local/racks` in your [overlay](../README.md#your-own-data), or
`examples/racks` (read only) until you have one.

```
racks/
  devices.yaml        where the rack comes from, its geometry, off-rack modules, wishlist
  layout.yaml         the rack itself, when you write it by hand (rack_source: file)
  <rack>.yaml         the snapshot `napier rack sync` writes; don't edit it
  usage.yaml          how you use each module, case modes, rules (hand-written)
  challenges.yaml     challenges to your defaults and how they were answered (hand-written)
  scenarios/*.yaml    what-if layouts (hand-written)
```

Start by copying `examples/racks` to `local/racks` (`mkdir -p local && cp -r examples/racks local/racks`)
and editing `layout.yaml` and `devices.yaml`. The copied snapshot (`example_rack.yaml`) is replaced
on your first `napier rack sync`; if you rename the rack, sync removes the old snapshot.

**Finding a module's slug.** Slugs follow ModularGrid's style: lowercase maker and module name joined
by hyphens, as in the module page's URL (`make-noise-maths`). Some carry a trailing hyphen or a
variant suffix (`intellijel-quadrax-`, `make-noise-maths-black-panel`), copied as is. Use the slug
from `catalog/modules.yaml` when the module is there, so its manual, specs and facts attach; any
stable id works for a module that isn't (sync reports it as unmapped).

## Commands

| Command | What it does |
|---|---|
| `napier rack sync` | Read the rack from its rack source, write the snapshot and `notes/rack.md`, report added, removed, moved and unmapped modules and any overlaps |
| `napier rack sources` | Rack sources installed, and which one `devices.yaml` enables |
| `napier rack usage` | Check `usage.yaml` and `challenges.yaml` against the rack; write `notes/rack-usage.md` |
| `napier rack scenarios` | Check the actual rack and every what-if layout (below); exits non-zero when any has a problem |
| `napier rack power` | Each case's load against its supply limits |
| `napier rack check` | Where the rack source's power figures disagree with the manual's |
| `napier rack export` | Everything above as JSON, for scripts and agents |
| `napier rack view --open` | Draw the rack and every scenario as one HTML page that loads nothing from the network (`--web-fonts` for the display fonts) |

## devices.yaml

```yaml
rack_source: file          # which rack source reads the rack (napier rack sources lists them)
rack:                      # settings handed to that source
  file: layout.yaml
planning:                  # optional: a planning rack, read the same way; modules on it that you
  file: future.yaml        # don't own join the wishlist
geometry:
  grid: [2, 1]             # cases across, cases down (default [1, 1]: one case)
  case_rows: [1U, 3U, 3U]  # each case's rows, top to bottom (default: all 3U)
  names: [left, right]     # optional; default main / left, right / top-left ... / r1c1 ...
modules:                   # optional: map a slug to a napier device, or override catalog/modules.yaml
  maker-module-slug: {device: maker_module, role: filter, tags: [filter]}
off_rack:                  # modules you own that aren't in the rack (scenarios can still place them)
  - {slug: ..., vendor: ..., name: ..., hp: 8, format: 3U, power: {plus12: 50, minus12: 10, plus5: 0}}
wishlist:                  # modules you don't own; scenarios can place them, nothing treats them as owned
  - {slug: ..., name: ..., hp: 16, status: "considered"}
```

Rows are numbered from the top across all cases, and HP from the left edge of the whole rack, so a
2x2 grid of 104 HP cases with a 1U row over two 3U rows is 6 rows by 208 HP. napier uses the
geometry to say which case a module is in, to add up power per case, and to measure how far apart
two modules sit: Manhattan distance, row centre to row centre plus the gap in HP (1U tiles 39.65 mm
tall, 3U panels 128.5 mm, one HP 5.08 mm).

Module slugs follow ModularGrid's style (`make-noise-maths`), which `catalog/modules.yaml` maps to
napier devices so each racked module's manual, specs and facts attach to it.

## layout.yaml (the built-in `file` source)

```yaml
rack: {name: My Rack, rows: 3, hp: 104, modified: 2026-10-12}
modules:
  - slug: make-noise-maths
    vendor: Make Noise
    name: Maths
    hp: 20
    format: 3U                                     # or 1U
    power: {plus12: 60, minus12: 50, plus5: 0}    # mA, from the maker
    at: ["row 2, hp 43"]                           # one position per copy
```

`examples/racks/layout.yaml` is a complete one.

## usage.yaml, challenges.yaml and scenarios

These three record what the rack is for. napier never generates them.

- **usage.yaml**: `stance` (how to treat the file), `rules` (placement rules, each with the modules it
  covers), `cases` (each case's supply `limits` in mA per rail, `mode`, row-by-row `layout`) and
  `modules`. Each module entry has a `job`, a `status` (anchor, keep, candidate, leaving, planned,
  considered), and optionally `pairs_with`, `keep_near`, `distance_ok` (pairs whose distance you've
  accepted), `notes` and `open` questions. Only write what you've decided; open questions go under
  `open`.
- **challenges.yaml**: every challenge to a default, with its hypothesis, outcome (open, testing,
  accepted, partial, rejected) and your response. Read it before raising one; a rejected challenge
  needs new evidence before it comes back.
- **scenarios/<id>.yaml**: start from the actual rack, `remove` slugs and `place` slugs at full
  position lists. `napier rack scenarios` reports overlaps, modules crossing a case seam, 1U modules
  in 3U rows and the reverse, power per case against `limits`, `pairs_with` and `keep_near` pairs
  farther than 20 cm or in different cases (unless `distance_ok`), and case rows whose free space is
  split into slivers.

`examples/racks` has one of each.

## Writing a rack source plug-in

A rack source turns some description of a rack (a page on a rack-planning site, an export from
another tool) into one plain structure. It's any object with a `name` and a `read` method:

```python
# my_package/source.py
from pathlib import Path


class MyPlanner:
    name = "myplanner"

    def read(self, settings: dict, base: Path) -> dict:
        """settings: the `rack:` (or `planning:`) mapping from devices.yaml.
        base: the racks folder, for relative paths."""
        ...
        return {
            "rack": {"id": "123", "name": "My Rack", "modified": "2026-10-12", "rows": 6, "hp": 208},
            "modules": [
                {"slug": "make-noise-maths", "vendor": "Make Noise", "name": "Maths", "hp": 20,
                 "is_1u": False, "power": {"plus12": 60, "minus12": 50, "plus5": 0},
                 "depth_mm": 25, "passive": False, "row": 2, "col": 43},   # one entry per copy
            ],
        }


SOURCE = MyPlanner()
```

Register it under the `napier.rack_sources` entry-point group in your package's `pyproject.toml`,
install it into napier's environment, and enable it by name:

```toml
[project.entry-points."napier.rack_sources"]
myplanner = "my_package.source:SOURCE"
```

```yaml
# racks/devices.yaml
rack_source: myplanner
rack: {url: "https://..."}
```

Installing a plug-in changes nothing until `devices.yaml` names it. `napier rack sync --set KEY=VALUE`
passes one-off settings to the source for a run (for example a saved copy of a page, for testing).
A plug-in that fetches over the network must be polite the way napier is: check robots.txt, send an
honest user agent and fetch each page once per run. `napier.sources` has `robots_allows` and `_get`
for that. Read a site's terms before automating it; a plug-in that reads your own data from a
service you use is usually best kept private, in your overlay.
