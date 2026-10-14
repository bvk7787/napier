"""Tests for the parts that need no index or models: sources, text layer, grep/read, facts."""

import pytest
import yaml

from napier import facts as factsmod
from napier import text as tx
from napier.search import rrf
from napier.sources import Source, apply_stop, clean_gdoc


def test_printed_pages_and_cites():
    s = Source(id="m", device="d", kind="manual", title="T", version="v1", page_offset=7)
    assert s.printed(18) == 11
    assert s.printed(3) is None
    assert s.pdf_page(11) == 18
    assert s.cite_pages([18]) == "p. 11"
    assert s.cite_pages([18, 19]) == "pp. 11, 12"
    assert s.cite_pages([3]) == "PDF p. 3"
    assert s.label() == "T, v1"


def test_gdoc_cleanup_and_stop():
    md = "# Title {#title}\n![][image1]\ntext\n[image1]: <data:image/png;base64,AAAA>\n# Title\nold copy\n"
    out = apply_stop(clean_gdoc(md), {"regex": "^# Title", "nth": 2})
    assert "data:image" not in out and "{#" not in out and "old copy" not in out and "text" in out


def test_rrf_prefers_agreement():
    sc = rrf({"a": ["x", "y"], "b": ["x", "z"]})
    assert max(sc, key=sc.get) == "x"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    return tmp_path


def test_text_source_grep_and_sections(home, tmp_path):
    f = tmp_path / "log.txt"
    f.write_text("2026-09-13 - Version 6.6.3\n- Fix: a thing\n\n2026-08-20 - Version 6.6.1\n"
                 "- New: Song View - SELECT+EDIT a third time also clones instruments\n")
    s = Source(id="log", device="m8", kind="changelog", title="Log", format="text", path=str(f),
               heading=r"^\d{4}-\d{2}-\d{2} - Version")
    units = tx.build_units(s)
    assert [u["heading"] for u in units] == ["2026-09-13 - Version 6.6.3", "2026-08-20 - Version 6.6.1"]
    tx.save_units(s.id, units)
    hits = tx.grep("third time", [s])
    assert len(hits) == 1 and hits[0].cite == "§ 2026-08-20 - Version 6.6.1"
    assert len(tx.grep("SELECT + EDIT", [s])) == 1       # '+' matches with or without spaces
    assert len(tx.grep("select+edit", [s])) == 1
    assert tx.grep("SELECTEDIT", [s]) == [] and tx.grep("SELECT EDIT", [s]) == []  # '+' is literal
    assert len(tx.grep(r"SELECT\+EDIT", [s], regex=True)) == 1
    sec = tx.read_section(s, "6.6.1")
    assert "clones instruments" in sec["text"] and "a thing" not in sec["text"]


def test_markdown_section_levels(home, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# System\nintro\n## Live Mode Shortcuts\nHold Left\nand Play\n## Tap Tempo\ntap\n# Next\n")
    s = Source(id="doc", device="m8", kind="community", title="Doc", format="markdown", path=str(f))
    tx.save_units(s.id, tx.build_units(s))
    sec = tx.read_section(s, "live mode")
    assert "Hold Left" in sec["text"] and "Tap Tempo" not in sec["text"]
    sys_sec = tx.read_section(s, "system")
    assert "Tap Tempo" in sys_sec["text"] and "Next" not in sys_sec["text"]
    assert len(tx.grep("Left and", [s])) == 1               # a space matches a line break


def test_facts_add_and_verify(home):
    f = factsmod.add("m8_tracker", "REPITCH STEPS counts bars", status="community", cite="https://x")
    assert f["id"] == "m8-repitch-steps-counts-bars"
    again = factsmod.add("m8_tracker", "REPITCH STEPS counts bars")
    assert again["id"].endswith("-2")
    v = factsmod.set_status(f["id"], "hardware", note="help line says bars")
    assert v["status"] == "hardware" and "help line" in v["notes"]
    saved = yaml.safe_load(factsmod.facts_file("m8_tracker").read_text())
    assert saved[0]["status"] == "hardware" and "device" not in saved[0]
    with pytest.raises(ValueError):
        factsmod.add("m8_tracker", "x", status="maybe")


def test_cli_hardware_and_refuted_checks_need_a_note(home):
    from click.testing import CliRunner

    from napier import cli
    f = factsmod.add("m8_tracker", "SHIFT+PLAY stops a cued track", status="community", cite="https://x")
    run = lambda *a: CliRunner().invoke(cli.main, list(a))  # noqa: E731
    for flag in ("--hardware", "--refute"):
        r = run("facts", "verify", f["id"], flag)
        assert r.exit_code == 2 and "--note" in r.output
    assert run("facts", "add", "m8_tracker", "a claim", "--status", "refuted").exit_code == 2
    assert run("facts", "add", "no_such_device", "a claim").exit_code == 1
    assert run("facts", "verify", f["id"], "--hardware", "--note", "tried on 6.5").exit_code == 0


def test_html_to_md():
    from napier.htmlmd import html_to_md
    md = html_to_md("<html><head><title>T</title><script>x()</script></head><body><nav>menu</nav>"
                    "<h2><span>3</span><span>Inputs</span></h2><p>Gate <b>in</b> jack.</p>"
                    "<ul><li>One</li><li>Two</li></ul><table><tr><th>A</th><th>B</th></tr>"
                    "<tr><td>1</td><td>2</td></tr></table></body></html>")
    assert "## 3 Inputs" in md and "Gate in jack." in md and "- One" in md
    assert "| A | B |" in md and "| 1 | 2 |" in md
    assert "menu" not in md and "x()" not in md and "T\n" not in md


@pytest.mark.parametrize("ref, fmt", [
    ("https://docs.google.com/document/d/abc/edit", "gdoc"),
    ("https://github.com/maker/fw/releases", "github_releases"),
    ("https://maker.example/manual.PDF?v=2", "pdf"),
    ("https://drive.google.com/uc?id=abc", "pdf"),
    ("https://maker.example/notes.md", "markdown"),
    ("~/Documents/rig-notes.md", "markdown"),
    ("https://evil.example/github.com/releases", "text"),       # the host decides, not a substring
    ("https://maker.example/support/", "text"),
])
def test_source_add_guesses_the_format_from_host_and_extension(ref, fmt):
    from napier.cli import guess_format
    assert guess_format(ref) == fmt
