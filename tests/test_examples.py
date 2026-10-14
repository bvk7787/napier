"""The shipped example rack (examples/racks) must stay consistent: it's what a fresh checkout shows."""
import shutil

import pytest
import yaml

from napier import paths, rack


@pytest.fixture
def shipped(monkeypatch):
    monkeypatch.delenv("NAPIER_CATALOG", raising=False)   # use catalog/modules.yaml
    monkeypatch.delenv("NAPIER_RACKS", raising=False)
    monkeypatch.delenv("NAPIER_NOTES", raising=False)
    assert paths.using_examples()


def test_example_usage_and_challenges_check_clean(shipped):
    assert rack.check_usage() == []
    assert rack.case_names() == ["main"]


def test_example_export_scenarios_and_power(shipped):
    ex = rack.export()
    assert ex["rack"]["name"] == "Example Rack" and len(ex["modules"]) == 16
    assert all(m["device"] for m in ex["modules"]), "every example module maps to a device in the catalog"
    scn = ex["scenarios"]["add-step-8"]
    assert scn["problems"] == []
    assert ex["case_power"]["main"]["load"]["plus12"] > 0


def test_example_snapshot_matches_layout(shipped, tmp_path, monkeypatch):
    """The committed snapshot is what `rack sync` would write from layout.yaml (regenerate it if this fails)."""
    racks = tmp_path / "racks"
    shutil.copytree(paths.examples_dir() / "racks", racks)
    (racks / "example_rack.yaml").unlink()
    monkeypatch.setenv("NAPIER_RACKS", str(racks))
    monkeypatch.setenv("NAPIER_NOTES", str(tmp_path / "notes"))
    rack.sync()
    new = yaml.safe_load((racks / "example_rack.yaml").read_text())
    old = yaml.safe_load((paths.examples_dir() / "racks/example_rack.yaml").read_text())
    assert new["modules"] == old["modules"] and new["rack"] == old["rack"]


def test_sync_refuses_to_write_the_example(shipped):
    with pytest.raises(PermissionError):
        rack.sync()


def test_rack_usage_writes_nothing_into_the_example(shipped, monkeypatch):
    from click.testing import CliRunner

    from napier import cli
    written = []
    monkeypatch.setattr(rack, "write_usage_md", lambda *a, **k: written.append(1) or (None, False))
    r = CliRunner().invoke(cli.main, ["rack", "usage"])
    assert r.exit_code == 0 and "the example rack" in r.output and not written
