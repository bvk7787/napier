"""The private overlay (local/): extra sources and facts, your racks and notes, napier.toml."""
import pytest
import yaml

from napier import facts, paths, refresh
from napier.sources import file_of, load_sources


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    pub = tmp_path / "public"
    loc = tmp_path / "local"
    (pub / "facts").mkdir(parents=True)
    (loc / "facts").mkdir(parents=True)
    (loc / "racks").mkdir()
    (pub / "sources.yaml").write_text(yaml.safe_dump([dict(id="pub_manual", device="dev", url="https://x.test/m.pdf")],
                                                     sort_keys=False))
    (loc / "sources.yaml").write_text(yaml.safe_dump([dict(id="my_notes", device="my_rig", kind="note",
                                                           format="markdown", path="notes/rig.md")], sort_keys=False))
    monkeypatch.setenv("NAPIER_SOURCES", str(pub / "sources.yaml"))
    monkeypatch.setenv("NAPIER_FACTS", str(pub / "facts"))
    monkeypatch.setenv("NAPIER_LOCAL", str(loc))
    monkeypatch.delenv("NAPIER_CONFIG")
    return pub, loc


def test_sources_merge_and_local_paths_resolve_in_the_overlay(overlay):
    pub, loc = overlay
    assert [s.id for s in load_sources()] == ["my_notes", "pub_manual"]    # the owner's own sources first
    srcs = {s.id: s for s in load_sources()}
    assert srcs["my_notes"].file == loc / "notes" / "rig.md"
    assert file_of("my_notes") == loc / "sources.yaml" and file_of("pub_manual") == pub / "sources.yaml"
    refresh.update_source_entry("my_notes", {"version": "v2"})          # edits land in the overlay's list
    assert "version: v2" in (loc / "sources.yaml").read_text()
    assert "version" not in (pub / "sources.yaml").read_text()


def test_duplicate_ids_across_lists_are_refused(overlay):
    pub, loc = overlay
    (loc / "sources.yaml").write_text(yaml.safe_dump([dict(id="pub_manual", device="dev", url="https://y.test")]))
    with pytest.raises(ValueError, match="already defined"):
        load_sources()


def test_new_facts_go_to_the_overlay_when_there_is_one(overlay, monkeypatch):
    pub, loc = overlay
    facts.add("dev", "a claim from the manual", status="manual", source="pub_manual", pages=[3])
    facts.add("my_rig", "private claim", status="hardware")
    assert (loc / "facts" / "dev.yaml").exists() and not (pub / "facts" / "dev.yaml").exists()
    assert (loc / "facts" / "my_rig.yaml").exists()
    monkeypatch.setenv("NAPIER_LOCAL", "none")                      # no overlay: public, for a pull request
    facts.add("dev", "another claim", status="manual", source="pub_manual", pages=[4])
    assert (pub / "facts" / "dev.yaml").exists()


def test_a_device_can_have_facts_in_both_folders(overlay):
    pub, loc = overlay
    (pub / "facts" / "dev.yaml").write_text("# public header\n- id: dev-pub\n  claim: p\n  status: manual\n")
    (loc / "facts" / "dev.yaml").write_text(yaml.safe_dump([dict(id="dev-mine", claim="m", status="unverified")]))
    assert [f["id"] for f in facts.load("dev")] == ["dev-pub", "dev-mine"]
    assert {f["device"] for f in facts.load("dev")} == {"dev"}
    facts.set_status("dev-pub", "manual", note="rechecked the page")    # edits stay in the file that has the fact
    facts.set_status("dev-mine", "hardware", note="tried it")
    assert yaml.safe_load((pub / "facts" / "dev.yaml").read_text())[0]["notes"].endswith("rechecked the page")
    assert yaml.safe_load((loc / "facts" / "dev.yaml").read_text())[0]["status"] == "hardware"
    assert facts.file_of("dev-pub") == pub / "facts" / "dev.yaml"
    refresh.set_fact_pages("dev-pub", [7])
    assert facts.find("dev-pub")["pages"] == [7] and len(facts.load("dev")) == 2


def test_racks_notes_and_config_come_from_the_overlay(overlay, monkeypatch):
    pub, loc = overlay
    monkeypatch.delenv("NAPIER_RACKS", raising=False)
    monkeypatch.delenv("NAPIER_NOTES", raising=False)
    assert paths.racks_dir() == loc / "racks" and paths.notes_dir() == loc / "notes"
    assert not paths.using_examples() and paths.owner() == "the owner"
    (loc / "napier.toml").write_text('owner = "Sam"\nrack_title = "Sam\'s Rack"\n')
    assert paths.owner() == "Sam" and paths.rack_title() == "Sam's Rack"
    monkeypatch.setenv("NAPIER_LOCAL", "none")
    assert paths.using_examples() and paths.local_root() is None and paths.racks_dir() == paths.REPO_ROOT / "examples" / "racks"


def test_facts_list_sorts_by_file_name_across_folders(overlay):
    pub, loc = overlay
    (pub / "facts" / "a_dev.yaml").write_text(yaml.safe_dump([dict(id="a-1", claim="a", status="manual")]))
    (loc / "facts" / "b_rig.yaml").write_text(yaml.safe_dump([dict(id="b-1", claim="b", status="hardware")]))
    (pub / "facts" / "c_dev.yaml").write_text(yaml.safe_dump([dict(id="c-1", claim="c", status="manual")]))
    assert [f["id"] for f in facts.load()] == ["a-1", "b-1", "c-1"]      # as if one folder


def test_manual_facts_need_citations_and_mcp_writes_are_stamped(overlay):
    with pytest.raises(ValueError, match="names its source"):
        facts.add("dev", "a claim", status="manual")
    with pytest.raises(ValueError, match="printed pages"):
        facts.add("dev", "a claim", status="manual", source="pub_manual")
    f = facts.add("dev", "a claim", status="manual", source="pub_manual", pages=[4], via="mcp")
    assert f["via"] == "mcp"
    g = facts.set_status(f["id"], "hardware", note="seen on the device, firmware 1.2", via="mcp")
    assert g["via"] == "mcp" and "firmware 1.2" in g["notes"]
    h = facts.set_status(f["id"], "hardware", note="checked again from the CLI")
    assert "via" not in h                                          # the CLI's own check clears the stamp


def test_refresh_reports_only_public_items_in_public_commits(overlay, monkeypatch):
    from napier import auto
    pub, loc = overlay
    monkeypatch.setenv("NAPIER_SPECS", str(pub / "specs"))
    rep = dict(date="2026-10-13", outcome="", model="m", updated=[
        dict(id="pub_manual", device="dev", old_version="v1", new_version="v2"),
        dict(id="my_notes", device="my_rig", old_version="", new_version="x")],
        reworded=[], pages_fixed=[], eval=None, rack={"added": ["Secret Module"]}, local_commit="abc",
        review=[dict(kind="source-error", id="my_notes", detail="HTTP 403 at https://docs.google.com/private?token=x"),
                dict(kind="source-gone", id="pub_manual", detail="404"),
                dict(kind="rack-unmapped", id="secret-module", detail="Secret Module")])
    pub_rep = auto.public_report(rep)
    text = auto.render(pub_rep)
    assert "pub_manual" in text
    for private in ("my_notes", "token=x", "Secret Module", "secret-module", "abc"):
        assert private not in text, private
    assert "my_notes" in auto.render(rep)                             # the local report keeps everything
