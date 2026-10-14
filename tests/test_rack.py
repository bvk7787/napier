"""Tests for rack tracking: rack sources, snapshot diffs, the note, usage and challenges."""
import pytest
import yaml

from napier import rack, rack_sources


def layout(mods, name="Test Rack"):
    """A racks/layout.yaml for the built-in file source. mods: (slug, vendor, name, hp, is_1u, row, col)."""
    by = {}
    for s, v, n, hp, u, r, c in mods:
        e = by.setdefault((s, n), dict(slug=s, vendor=v, name=n, hp=hp, format="1U" if u else "3U", at=[]))
        e["at"].append(f"row {r}, hp {c}")
    return yaml.safe_dump(dict(rack=dict(name=name, rows=2, hp=104, modified="2026-09-27 05:03:57"),
                               modules=list(by.values())))


A = ("make-noise-maths", "Make Noise", "MATHS", 20, False, 2, 1)
B = ("intellijel-buff-mult-1u", "Intellijel", "Buff Mult 1U", 14, True, 1, 1)
B2 = ("intellijel-buff-mult-1u", "Intellijel", "Buff Mult 1U", 14, True, 1, 15)
C = ("mystery-module", "Somebody", "Mystery", 6, False, 2, 21)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPIER_RACKS", str(tmp_path / "racks"))
    monkeypatch.setenv("NAPIER_NOTES", str(tmp_path / "notes"))
    (tmp_path / "racks").mkdir()
    (tmp_path / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(
        devices={"make-noise-maths": "make_noise_maths", "intellijel-buff-mult-1u": "intellijel_buff_mult_1u"})))
    return tmp_path


def put(cfg, mods, fname="layout.yaml", name="Test Rack"):
    (cfg / "racks" / fname).write_text(layout(mods, name))


def test_first_sync_then_diff(cfg):
    put(cfg, [A, B])
    r1 = rack.sync()
    assert r1["changed"] and r1["source"] == "file" and len(r1["added"]) == 2 and not r1["unmapped"]
    snap = yaml.safe_load((cfg / "racks" / "test_rack.yaml").read_text())
    assert snap["rack"]["modified"] == "2026-09-27"
    md = (cfg / "notes" / "rack.md").read_text()
    assert "## Rack row 1 (1U row), left to right" in md and "## Rack row 2 (3U row)" in md
    assert "at HP 1: Make Noise MATHS, 20 HP (napier device `make_noise_maths`)" in md
    assert rack.load_snapshot()["rack"]["name"] == "Test Rack"     # layout.yaml is never read as a snapshot

    assert not rack.sync()["changed"]                               # same rack, nothing to write

    put(cfg, [B, B2, C])
    r3 = rack.sync()
    assert [m["slug"] for m in r3["added"]] == ["mystery-module"]
    assert [m["slug"] for m in r3["removed"]] == ["make-noise-maths"]
    assert r3["recount"][0]["count"] == 2 and r3["recount"][0]["was"] == 1
    assert [m["slug"] for m in r3["unmapped"]] == ["mystery-module"]
    assert "- 2x Intellijel Buff Mult 1U" in (cfg / "notes" / "rack.md").read_text()


def test_renamed_rack_replaces_its_snapshot_and_moves_are_reported(cfg):
    put(cfg, [A, B])
    rack.sync()
    A_moved = A[:5] + (2, 30)
    put(cfg, [A_moved, B], name="My Case")
    r = rack.sync()
    assert r["removed_snapshots"] == ["test_rack.yaml"] and not (cfg / "racks" / "test_rack.yaml").exists()
    assert not r["added"] and not r["removed"]                       # compared with the old snapshot
    assert [(m["slug"], m["was_at"], m["at"]) for m in r["moved"]] == [
        ("make-noise-maths", ["row 2, hp 1"], ["row 2, hp 30"])]
    assert rack.load_snapshot()["rack"]["name"] == "My Case"


def test_sync_reports_problems_in_the_actual_rack(cfg):
    on_top = ("intellijel-amps", "Intellijel", "Amps", 6, False, 2, 5)  # inside MATHS (hp 1-20)
    put(cfg, [A, on_top])
    r = rack.sync()
    assert any("overlaps" in p for p in r["problems"])


def test_dry_run_writes_nothing(cfg):
    put(cfg, [A])
    rack.sync(write=False)
    assert not (cfg / "notes" / "rack.md").exists()


def test_missing_layout_and_unknown_source(cfg):
    with pytest.raises(rack_sources.RackSourceError, match="no rack file"):
        rack.sync()
    (cfg / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(rack_source="nope")))
    with pytest.raises(rack_sources.RackSourceError, match="no rack source 'nope'"):
        rack.sync()


def test_plugin_source_is_used_only_when_named(cfg, monkeypatch):
    class Fake:
        name = "fake"

        def read(self, settings, base):
            assert settings == {"url": "https://example.test/rack/1", "token": "x"} and base == cfg / "racks"
            return dict(rack=dict(id="1", name="Fake Rack", modified="", rows=2, hp=104),
                        modules=[dict(slug="make-noise-maths", vendor="Make Noise", name="MATHS", hp=20, is_1u=False,
                                      power={}, depth_mm=None, passive=False, row=2, col=1)])

    class EP:
        name, value = "fake", "x:y"

        def load(self):
            return Fake()

    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [EP()] if group == rack_sources.GROUP else [])
    assert rack_sources.installed() == ["file", "fake"]
    (cfg / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(
        rack_source="fake", rack=dict(url="https://example.test/rack/1"))))
    r = rack.sync(settings={"token": "x"})
    assert r["source"] == "fake" and (cfg / "racks" / "fake_rack.yaml").exists()
    assert "Snapshot of https://example.test/rack/1" in (cfg / "notes" / "rack.md").read_text()


def test_planning_rack_feeds_the_wishlist(cfg):
    (cfg / "racks" / "devices.yaml").write_text(yaml.safe_dump(dict(
        planning=dict(file="future.yaml"),
        devices={"make-noise-maths": "make_noise_maths", "intellijel-buff-mult-1u": "intellijel_buff_mult_1u"},
        wishlist=[dict(slug="mystery-module", vendor="Somebody", name="Mystery", hp=6, status="planned purchase"),
                  dict(slug="only-considered", vendor="Other", name="Maybe", hp=4, status="considered")])))
    put(cfg, [A, B])
    put(cfg, [A, B, B2, C], fname="future.yaml", name="Future")   # MATHS owned; Buff Mult owned once, planned twice
    r = rack.sync()
    snap = yaml.safe_load((cfg / "racks" / "test_rack.yaml").read_text())
    wl = {w["slug"]: w for w in snap["wishlist"]}
    assert "make-noise-maths" not in wl                # owned, so not wishlist
    assert wl["intellijel-buff-mult-1u"]["count"] == 1  # one more than owned
    assert wl["mystery-module"]["status"] == "planned purchase" and wl["mystery-module"]["hp"] == 6
    assert wl["mystery-module"]["from_rack"] and wl["only-considered"]["status"] == "considered"
    assert [w["slug"] for w in r["wishlist_unmapped"]] == ["mystery-module"]
    md = (cfg / "notes" / "rack.md").read_text()
    assert "Future planning rack" in md and "Somebody Mystery (6 HP), not owned" in md
    # an unreadable planning rack keeps the last snapshot's entries
    (cfg / "racks" / "future.yaml").unlink()
    r2 = rack.sync()
    assert r2["wishlist_error"] and not r2["wishlist_removed"]


def test_catalog_maps_slugs_and_devices_yaml_wins(cfg, tmp_path, monkeypatch):
    cat = tmp_path / "modules.yaml"
    cat.write_text(yaml.safe_dump(dict(modules={
        "make-noise-maths": dict(device="catalog_maths", role="modulation", tags=["lfo"]),
        "mystery-module": dict(device="mystery", role="voice")})))
    monkeypatch.setenv("NAPIER_CATALOG", str(cat))
    mods = rack.load_config()["modules"]
    assert mods["mystery-module"]["device"] == "mystery" and mods["mystery-module"]["role"] == "voice"
    assert mods["make-noise-maths"]["device"] == "make_noise_maths"    # devices.yaml (flat form) wins


def test_usage_attaches_to_export_and_flags_unknown_slugs(cfg, monkeypatch, tmp_path):
    put(cfg, [A, B])
    rack.sync()
    (cfg / "racks" / "usage.yaml").write_text(yaml.safe_dump(dict(
        stance="Defaults, not axioms.",
        rules=[dict(id="maths-up-top", text="MATHS stays in the top row.", modules=["make-noise-maths"])],
        cases={"top-left": dict(power="Gen1", limits=dict(plus12=3000, minus12=3000, plus5=1500), mode="voices",
                                layout=["row 2: oscillators"]),
               "bottom-left": dict(limits=dict(plus12=-5, sideways=1)),
               "middle": dict(mode="?")},
        modules={"make-noise-maths": dict(job="envelopes for transients", status="anchor",
                                          pairs_with=["intellijel-buff-mult-1u"], open=["which row?"]),
                 "not-a-module": dict(job="?", status="maybe")})))
    (cfg / "racks" / "challenges.yaml").write_text(yaml.safe_dump(dict(challenges=[
        dict(id="c001", date="2026-10-07", kind="layout", title="Move MATHS", hypothesis="shorter cables", outcome="rejected",
             response="likes it there", modules=["make-noise-maths"]),
        dict(id="c001", title="dup", outcome="maybe", modules=["nope"])])))
    assert rack.load_snapshot()["rack"]["name"] == "Test Rack"       # usage.yaml is never read as a snapshot
    cprobs = rack.check_challenges()
    assert any("duplicate id" in p for p in cprobs) and any("outcome 'maybe'" in p for p in cprobs)
    assert any("unknown slug nope" in p for p in cprobs)
    probs = rack.check_usage()
    assert any("not-a-module" in p and "not a racked" in p for p in probs)
    assert any("status 'maybe'" in p for p in probs)
    assert any("cases.middle" in p for p in probs)
    assert any("bottom-left.limits.plus12" in p for p in probs) and any("unknown rail sideways" in p for p in probs)
    monkeypatch.setattr("napier.specs.by_slug", lambda: {})
    monkeypatch.setattr("napier.specs.compare", lambda mods, *a: [])
    monkeypatch.setattr("napier.sources.load_sources", lambda: [])
    ex = rack.export()
    maths = next(m for m in ex["modules"] if m["slug"] == "make-noise-maths")
    assert maths["usage"]["job"] == "envelopes for transients" and maths["usage"]["status"] == "anchor"
    assert ex["usage_rules"][0]["id"] == "maths-up-top" and ex["usage_stance"] == "Defaults, not axioms."
    assert ex["usage_cases"]["top-left"]["layout"] == ["row 2: oscillators"]
    out, changed = rack.write_usage_md()
    md = out.read_text()
    assert changed and "## Never firing" in md and "Not settled yet: which row?" in md
    assert "### Top left case (Gen1)" in md and "Mode: voices." in md
    assert "Supply limits: +12V 3000mA, -12V 3000mA, +5V 1500mA." in md
    assert "## How to treat this" in md and "## Working defaults (challengeable)" in md
    assert "## Challenge log" in md and "c001 (2026-10-07, layout, rejected): Move MATHS." in md
    assert "The owner: likes it there." in md
    assert ex["challenges"][0]["id"] == "c001"
    toml = tmp_path / "napier.toml"
    toml.write_text('owner = "sam"\nrack_title = "Sam\'s Rack"\n')
    monkeypatch.setenv("NAPIER_CONFIG", str(toml))
    md = rack.render_usage_md(rack.load_usage(), rack.known_slugs(), rack.load_challenges())
    assert md.startswith("# How sam uses the modular rack") and "Sam: likes it there." in md
    ex = rack.export()
    assert ex["title"] == "Sam's Rack" and ex["owner"] == "sam"




def test_case_power_sums_conservative_draw_per_case():
    rack_info = {"rows": 6, "hp": 208, "geometry": {"grid": [2, 2], "case_rows": ["1U", "3U", "3U"]}}
    mods = [
        dict(at=["row 2, hp 1"], power={"plus12": 100, "minus12": 50}, power_manual={"plus12": 120, "minus12": 40}),
        dict(at=["row 5, hp 105", "row 6, hp 150"], power={"plus12": 200, "minus12": 10, "plus5": 30}),
        dict(at=["row 4, hp 104"], power={"plus12": 7}),
    ]
    cases = {"bottom-right": {"limits": {"plus12": 6000, "minus12": 5000, "plus5": 2000}}}
    cp = rack.case_power(mods, rack_info, cases)
    assert cp["top-left"]["load"] == {"plus12": 120, "minus12": 50, "plus5": 0}
    assert cp["bottom-right"]["load"] == {"plus12": 400, "minus12": 20, "plus5": 60}
    assert cp["bottom-right"]["modules"] == 2 and cp["bottom-right"]["pct"]["plus12"] == 7
    assert cp["bottom-left"]["load"]["plus12"] == 7 and cp["bottom-left"]["pct"] == {}
    assert rack.case_of("row 3, hp 105", rack_info) == "top-right"


def test_a_rack_named_like_a_config_file_never_overwrites_it(cfg):
    put(cfg, [A, B], name="Layout")
    r = rack.sync()
    assert r["snapshot_file"].endswith("snapshot_layout.yaml")
    assert yaml.safe_load((cfg / "racks" / "layout.yaml").read_text())["rack"]["name"] == "Layout"
    put(cfg, [A, B], name="Usage")
    (cfg / "racks" / "usage.yaml").write_text("modules: {}\n")
    assert rack.sync()["snapshot_file"].endswith("snapshot_usage.yaml")
    assert (cfg / "racks" / "usage.yaml").read_text() == "modules: {}\n"
