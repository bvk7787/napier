# The rack planner

The rack commands keep your Eurorack rack next to the manuals. You describe what's racked, each
case's power supply and how you use each module, then try out layouts before moving anything. It's
all YAML in a racks folder: `local/racks` in your [overlay](../README.md#your-own-data), or the
read-only `examples/racks` until you set one up.

```
racks/
  devices.yaml        where the rack comes from, its geometry, off-rack modules, wishlist
  layout.yaml         the rack itself, when you write it by hand (rack_source: file)
  <rack>.yaml         the snapshot `napier rack sync` writes; don't edit it
  usage.yaml          how you use each module, case modes, rules (hand-written)
  challenges.yaml     challenges to your defaults and how they were answered (hand-written)
  scenarios/*.yaml    what-if layouts (hand-written)
```

To start, copy the example into your overlay and edit `layout.yaml` and `devices.yaml`:

```bash
napier init --rack
```

Your first `napier rack sync` replaces the copied snapshot (`example_rack.yaml`), and if you rename
the rack later, sync removes the old snapshot.

Module slugs follow ModularGrid's style: maker and module name in lowercase, joined by hyphens, as
in the module page's URL (`make-noise-maths`). Some have a trailing hyphen or a variant suffix
(`intellijel-quadrax-`, `make-noise-maths-black-panel`); copy those as they are. If the module is in
`catalog/modules.yaml`, use the slug from there so its manual, specs and facts attach. Any stable id
works for a module that isn't listed, and sync reports it as unmapped.

## Commands

| Command | What it does |
|---|---|
| `napier rack sync` | Reads the rack from its rack source, writes the snapshot and `notes/rack.md`, and reports modules that were added, removed, moved or unmapped, plus any overlaps |
| `napier rack sources` | Lists the installed rack sources and which one `devices.yaml` uses |
| `napier rack usage` | Checks `usage.yaml` and `challenges.yaml` against the rack and writes `notes/rack-usage.md` |
| `napier rack scenarios` | Checks the actual rack and every what-if layout, and exits non-zero if any has a problem |
| `napier rack power` | Shows each case's load against its supply limits |
| `napier rack check` | Shows where the rack source's power figures disagree with the manual |
| `napier rack export` | Prints all of the above as JSON, for scripts and agents |
| `napier rack view --open` | Draws the rack and every scenario as one HTML page that works offline (`--web-fonts` loads the display fonts) |

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
former:                    # modules you've sold or traded; only challenges.yaml can still name them
  - {slug: ..., vendor: ..., name: ..., left: 2026-10-17}
```

Rows are numbered from the top across all cases, and HP from the left edge of the whole rack. A 2x2
grid of 104 HP cases, each with a 1U row over two 3U rows, is 6 rows by 208 HP. napier uses the
geometry to work out which case a module is in, to add up power per case, and to measure the
distance between two modules. That distance is Manhattan distance from row centre to row centre plus
the gap in HP, using 39.65 mm for a 1U row, 128.5 mm for a 3U row and 5.08 mm per HP.

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

`examples/racks/layout.yaml` is a complete example.

## usage.yaml, challenges.yaml and scenarios

You write these by hand to record what the rack is for. `examples/racks` has one of each.

`usage.yaml` has a `stance` (how to treat the file), placement `rules` with the modules each one
covers, and `cases` with each case's supply `limits` in mA per rail, its `mode` and a row-by-row
`layout`. Under `modules`, each entry has a `job` and a `status` (anchor, keep, candidate, leaving,
planned or considered). It can also list `pairs_with`, `keep_near`, `distance_ok` for pairs whose
distance you've accepted, `notes`, and `open` questions. Only write down what you've decided, and
put anything unsettled under `open`.

`challenges.yaml` logs each challenge to one of your defaults: the hypothesis, the outcome (open,
testing, accepted, partial or rejected) and your response. Read it before raising a new one. A
rejected challenge needs new evidence before it comes back.

`scenarios/<id>.yaml` starts from the actual rack, lists slugs to `remove`, and lists slugs to
`place` with their full positions. `napier rack scenarios` reports overlaps, modules crossing a case
seam, 1U modules in 3U rows (and the reverse), power per case against `limits`, and case rows where
the free space is split into slivers. It also flags `pairs_with` and `keep_near` pairs that are more
than 20 cm apart or in different cases, unless they're marked `distance_ok`.

## Writing a rack source plug-in

A rack source turns a rack described somewhere else, like a page on a rack-planning site or an
export from another tool, into the structure napier reads. It's any object with a `name` and a
`read` method:

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

Installing a plug-in does nothing until `devices.yaml` names it. `napier rack sync --set KEY=VALUE`
passes a one-off setting to the source for a single run, which is handy for testing against a saved
copy of a page.

A plug-in that fetches over the network should be as polite as napier: check robots.txt, send an
honest user agent and fetch each page once per run. `napier.sources` has `robots_allows` and `_get`
for this. Read a site's terms before automating it. Keep a plug-in that reads data from your own
account on a service private, in your overlay.
