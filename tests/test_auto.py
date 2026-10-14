"""Tests for the parts of the auto refresh that need no network, models or git."""
import pytest
import yaml

from napier import auto
from napier import facts as factsmod


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    return tmp_path


def test_set_fact_fields_touches_one_block(home):
    f = factsmod.facts_file("x")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# hand header\n- id: x-one\n  claim: a\n  status: manual\n  q: old q\n  anchors: [\"aa\"]\n"
                 "# section two\n- id: x-two\n  claim: b\n  status: manual\n  q: other\n  anchors: [\"bb\"]\n")
    auto.set_fact_fields("x-one", q="new q")
    text = f.read_text()
    assert text.startswith("# hand header\n") and "# section two\n- id: x-two" in text
    rows = {r["id"]: r for r in yaml.safe_load(text)}
    assert rows["x-one"]["q"] == "new q" and rows["x-two"]["q"] == "other"


def test_render_lists_review_items():
    rep = dict(date="2026-10-04", model="m", outcome="updated 1 sources, PR open", pages_fixed=[],
               updated=[dict(id="a_manual", old_version="v1", new_version="v2")], reworded=[],
               review=[dict(kind="anchor-missing", id="a-fact", detail="gone")], eval=dict(hit1=0.8, hit3=1.0, facts=5))
    md = auto.render(rep)
    assert "| a_manual | v1 | v2 |" in md and "anchor-missing: `a-fact`" in md and "hit@3 100%" in md


def test_overlay_tests_gate_public_pushes(tmp_path):
    assert auto.overlay_tests(None) == "" and auto.overlay_tests(tmp_path) == ""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_guard.py").write_text("def test_ok():\n    assert True\n")
    assert auto.overlay_tests(tmp_path) == ""
    (tmp_path / "tests" / "test_guard.py").write_text("def test_leak():\n    assert False, 'private word found'\n")
    assert "private word found" in auto.overlay_tests(tmp_path)


def test_a_failing_refresh_still_reports_and_stays_on_main(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-q",
                                                  "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    monkeypatch.setattr(auto.paths, "REPO_ROOT", repo)
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(auto, "keep_awake", lambda: None)
    monkeypatch.setattr(auto, "notify", lambda *a, **k: None)
    monkeypatch.setattr(auto, "load_sources", lambda: [])

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(auto.refresh, "check", boom)
    rep = auto.run(push=False, log=lambda *_: None)
    assert rep["outcome"].startswith("failed: RuntimeError: network down")
    assert (tmp_path / "home" / "reports" / "latest.md").exists()
    assert auto.git("branch", "--show-current") == "main"
