"""Tests for manual-cited specs: anchor and jack checks, power comparison, and the rack export."""

import pytest
import yaml

from napier import rack, specs
from napier import text as tx

SOURCES = """\
- id: m_manual
  device: m
  kind: manual
  format: pdf
  title: M manual
  url: https://example.com/m.pdf
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, d in (("NAPIER_HOME", "home"), ("NAPIER_FACTS", "facts"), ("NAPIER_SPECS", "specs"),
                 ("NAPIER_RACKS", "racks"), ("NAPIER_NOTES", "notes")):
        monkeypatch.setenv(k, str(tmp_path / d))
        (tmp_path / d).mkdir()
    (tmp_path / "sources.yaml").write_text(SOURCES)
    monkeypatch.setenv("NAPIER_SOURCES", str(tmp_path / "sources.yaml"))
    tx.save_units("m_manual", [
        {"n": 1, "page": 1, "printed": 1, "heading": "", "md": "Power: 60mA @ +12V, 50mA @ -12V", "raw": ""},
        {"n": 2, "page": 2, "printed": 2, "heading": "", "md": "Panel: Ch. 1 Signal IN, EOR out, Unity", "raw": ""},
    ])
    return tmp_path


def write_spec(env, **over):
    s = dict(device="m", slugs=["make-noise-m"], source="m_manual",
             power=dict(plus12=60, minus12=50, plus5=0, page=1, anchor="60mA @ +12V"),
             jacks=[dict(name="Ch. 1 Signal IN", dir="in", type="audio", page=2),
                    dict(name="EOR", dir="out", type="gate", page=2)])
    s.update(over)
    (env / "specs" / "m.yaml").write_text(yaml.safe_dump(s))


def test_check_passes_and_counts(env):
    write_spec(env)
    res = specs.check()
    assert res.specs == 1 and res.jacks == 2 and res.powered == 1 and not res.problems
    assert specs.io_counts(specs.load_all()["m"]) == {"audio_in": 1, "gate_out": 1}


def test_check_catches_wrong_page_and_missing_jack(env):
    write_spec(env, power=dict(plus12=60, page=2, anchor="60mA @ +12V"),
               jacks=[dict(name="Ch. 4 Signal IN", dir="in", type="audio", page=2),
                      dict(name="EOR", dir="sideways", type="gate", page=2)])
    what = sorted((p.what, p.detail[:20]) for p in specs.check().problems)
    assert any(w == "power" and "60mA" in d for w, d in what)
    assert any(w == "jack" and "Ch. 4" in d for w, d in what)
    assert any(w == "jack" and "EOR" in d for w, d in what)        # bad dir


def test_compare_flags_power_mismatch(env):
    write_spec(env)
    mods = [dict(slug="make-noise-m", vendor="Make Noise", name="M", power=dict(plus12=60, minus12=10, plus5=0))]
    m = specs.compare(mods)
    assert m and m[0]["diffs"] == {"minus12": {"rack_source": 10, "manual": 50}}
    mods[0]["power"]["minus12"] = 52
    assert not specs.compare(mods)                                  # within tolerance


def test_export_joins_snapshot_specs_and_off_rack(env):
    write_spec(env)
    (env / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(
        modules={"make-noise-m": dict(device="m", role="modulation", tags=["lfo"])},
        off_rack=[dict(slug="x-off", vendor="X", name="Off", hp=10, format="3U", power=dict(plus12=20),
                       device=None, role="rhythm", tags=[], status="owned, off the rack")])))
    (env / "racks" / "layout.yaml").write_text(yaml.safe_dump(dict(
        rack=dict(name="R", modified="2026-01-01", rows=1, hp=84),
        modules=[dict(slug="make-noise-m", vendor="Make Noise", name="M", hp=20, format="3U", depth_mm=25,
                      power=dict(plus12=60, minus12=10), at=["row 1, hp 1"])])))
    rack.sync()
    ex = rack.export()
    m = {x["slug"]: x for x in ex["modules"]}
    assert m["make-noise-m"]["power"] == {"plus12": 60, "minus12": 10, "plus5": None}
    assert m["make-noise-m"]["power_manual"]["minus12"] == 50 and m["make-noise-m"]["io"] == {"audio_in": 1, "gate_out": 1}
    assert [d["id"] for d in m["make-noise-m"]["docs"]] == ["m_manual"]
    assert m["x-off"]["racked"] is False and m["x-off"]["role"] == "rhythm"
    assert ex["power_mismatches"][0]["slug"] == "make-noise-m"


def test_wishlist_is_marked_not_owned_and_kept_out_of_plain_export(env):
    write_spec(env)
    (env / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(
        modules={"make-noise-m": dict(device="m", role="modulation", tags=["lfo"])},
        off_rack=[dict(slug="x-off", vendor="X", name="Off", hp=10, format="3U", power=dict(plus12=20),
                       device=None, role="rhythm", tags=[], status="owned, off the rack")],
        wishlist=[dict(slug="y-want", vendor="Y", name="Want", hp=6, format="3U", power=dict(plus12=5),
                       device="y_want", role="midi", tags=[], status="planned purchase")])))
    (env / "racks" / "layout.yaml").write_text(yaml.safe_dump(dict(
        rack=dict(name="R", modified="2026-01-01", rows=1, hp=84),
        modules=[dict(slug="make-noise-m", vendor="Make Noise", name="M", hp=20, format="3U", depth_mm=25,
                      power=dict(plus12=60, minus12=10), at=["row 1, hp 1"])])))
    rack.sync()
    plain = {x["slug"]: x for x in rack.export()["modules"]}
    assert "y-want" not in plain                                   # a plain export never sees it
    assert plain["make-noise-m"]["owned"] is True and plain["x-off"]["owned"] is True
    full = {x["slug"]: x for x in rack.export(include_wishlist=True)["modules"]}
    assert full["y-want"]["owned"] is False and full["y-want"]["racked"] is False
    md = (env / "notes" / "rack.md").read_text()
    owned_part, wish_part = md.split("## Wishlist (not owned)")
    assert "Want" not in owned_part and "Y Want (6 HP), not owned, planned purchase" in wish_part
