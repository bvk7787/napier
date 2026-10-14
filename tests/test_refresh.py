"""Tests for refresh: in-place edits of sources.yaml and facts files, and fact rechecks."""
import pytest
import yaml

from napier import facts as factsmod
from napier import refresh
from napier import text as tx


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    return tmp_path


SOURCES = """\
# sources for napier
- id: a_manual
  device: a
  kind: manual
  format: pdf
  title: A manual
  version: v1
  url: https://example.com/a.pdf
  sha256: aaa
  page_offset: 0

# a hand comment between entries
- id: b_manual
  device: b
  kind: manual
  format: pdf
  title: B manual
  version: v1
  url: https://example.com/b.pdf
  page_offset: 2
"""


def test_update_source_entry_keeps_neighbours(tmp_path):
    f = tmp_path / "sources.yaml"
    f.write_text(SOURCES)
    refresh.update_source_entry("a_manual", {"version": "v2", "sha256": "bbb", "fetched": "2026-10-04"}, f)
    text = f.read_text()
    assert text.startswith("# sources for napier\n") and "# a hand comment between entries" in text
    rows = yaml.safe_load(text)
    assert rows[0]["version"] == "v2" and rows[0]["sha256"] == "bbb" and rows[0]["fetched"] == "2026-10-04"
    assert rows[1] == yaml.safe_load(SOURCES)[1]
    assert "page_offset: 0\n\n# a hand comment" in text      # blank line before the comment kept


def test_recheck_finds_moved_and_missing(home, tmp_path, monkeypatch):
    src_file = tmp_path / "sources.yaml"
    src_file.write_text(SOURCES)
    monkeypatch.setenv("NAPIER_SOURCES", str(src_file))
    tx.save_units("a_manual", [
        {"n": 1, "page": 1, "printed": 1, "heading": "", "md": "Intro text.", "raw": ""},
        {"n": 2, "page": 2, "printed": 2, "heading": "", "md": "The CYCLE button makes it loop.", "raw": ""},
        {"n": 3, "page": 3, "printed": 3, "heading": "", "md": "Range is +/-10V across the", "raw": ""},
        {"n": 4, "page": 4, "printed": 4, "heading": "", "md": "whole input.", "raw": ""},
    ])
    ff = factsmod.facts_file("a")
    ff.parent.mkdir(parents=True, exist_ok=True)
    ff.write_text("# hand header\n\n"
                  "- id: a-cycle\n  claim: c\n  status: manual\n  source: a_manual\n  pages: [5]\n"
                  "  q: q\n  anchors: [\"CYCLE button makes it loop\"]\n"
                  "# keep me\n"
                  "- id: a-range\n  claim: c\n  status: manual\n  source: a_manual\n  pages: [3]\n"
                  "  q: q\n  anchors: [\"across the whole input\"]\n"
                  "- id: a-gone\n  claim: c\n  status: manual\n  source: a_manual\n  pages: [1]\n"
                  "  q: q\n  anchors: [\"a sentence that was removed\"]\n")
    res = {r.id: r for r in refresh.recheck("a")}
    assert res["a-cycle"].problem == "page-moved" and res["a-cycle"].found_pages == [2]
    assert res["a-range"].problem == "ok"                    # found across the page break
    assert res["a-gone"].problem == "anchor-missing"
    refresh.set_fact_pages("a-cycle", [2])
    text = ff.read_text()
    assert text.startswith("# hand header\n") and "# keep me\n- id: a-range" in text
    assert {f["id"]: f for f in factsmod.load("a")}["a-cycle"]["pages"] == [2]
