"""End to end through the CLI: source add (fake HTTP) -> fetch -> ingest --text-only -> grep -> read,
on a generated PDF whose printed page numbers start on PDF page 3 (offset 2)."""
import json

import pytest
import yaml
from click.testing import CliRunner

from napier import cli
from napier import sources as sm


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal valid PDF, one text line per entry; lines run top to bottom."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        ops = "".join(f"BT /F1 12 Tf 72 {740 - 20 * i} Td ({ln}) Tj ET\n" for i, ln in enumerate(lines))
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}endstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R "
                    "/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


PDF = make_pdf([
    ["Example Box Manual", "Version 2.0"],                          # PDF p. 1: cover, unnumbered
    ["Contents", "Transport ...... 2"],                              # PDF p. 2: unnumbered
    ["Introduction", "Thanks for buying the box.", "1"],             # printed 1
    ["Transport", "Hold [SHIFT]+[PLAY] to restart the pattern.", "2"],
    ["Filters", "Filter Depth  0-18", "pg 3"],
    ["Specs", "Power: 60mA @ +12V", "Example Box Manual 4"],
])
URL = "https://maker.example/files/box-manual.pdf"


@pytest.fixture
def env(tmp_path, monkeypatch):
    srcs = tmp_path / "sources.yaml"
    srcs.write_text("# test sources\n")
    monkeypatch.setenv("NAPIER_SOURCES", str(srcs))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    calls = []

    def fake_urlopen(url, timeout, headers, robots=True):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nDisallow: /private/\n"
        if url == URL:
            return PDF
        raise AssertionError(f"unexpected request {url}")

    monkeypatch.setattr(sm, "_urlopen", fake_urlopen)
    monkeypatch.setattr(sm, "SPACING", 0)
    return srcs, calls


def run(*args, code=0):
    r = CliRunner().invoke(cli.main, list(args), catch_exceptions=False)
    assert r.exit_code == code, r.output
    return r.output


def test_add_ingest_grep_read_cite_printed_pages(env):
    srcs, calls = env
    out = run("source", "add", URL, "--id", "box_manual", "--device", "box", "--version", "2.0")
    assert "page offset 2 (4/5 numbered pages agree)" in out   # the TOC line ending in 2 votes wrong
    assert calls == ["https://maker.example/robots.txt", URL]
    entry = yaml.safe_load(srcs.read_text())[0]
    assert entry["page_offset"] == 2 and len(entry["sha256"]) == 64 and entry["url"] == URL

    assert "box_manual: ok" in run("fetch", "--all")                       # already here and matches its pin
    assert "no text yet" in run("grep", "restart")          # before ingest: says so, no crash
    assert "text box_manual: 6 units" in run("ingest", "--text-only")

    hits = json.loads(run("grep", "[shift] + [play]", "--json"))["hits"]
    assert [(h["source_id"], h["cite"]) for h in hits] == [("box_manual", "p. 2")]
    assert json.loads(run("grep", "Filter Depth", "--device", "box", "--json"))["hits"][0]["cite"] == "p. 3"

    page = json.loads(run("read", "box", "--page", "4", "--json"))    # device id resolves to its manual
    assert page["cite"] == "p. 4" and "60mA @ +12V" in page["text"] and page["title"] == "box_manual, 2.0"
    assert json.loads(run("read", "box_manual", "--pdf-page", "2", "--json"))["cite"] == "PDF p. 2"
    assert "no page 9" in run("read", "box_manual", "--page", "9", code=1)
    assert "give --page" in run("read", "box_manual", code=2)
    assert "detected offset 2 (4/5" in run("source", "offset", "box_manual")
    st = json.loads(run("status", "--json"))["sources"][0]
    assert st["file"] == "ok" and st["text"] == 6 and st["page_offset"] == 2


def test_robots_disallow_refuses_and_writes_nothing(env):
    srcs, calls = env
    out = run("source", "add", "https://maker.example/private/m.pdf", "--id", "x", "--device", "x", code=1)
    assert "disallows" in out and calls == ["https://maker.example/robots.txt"]
    assert srcs.read_text() == "# test sources\n"


def test_unknown_ids_and_missing_source_list_are_errors(env, monkeypatch, tmp_path):
    assert "no device 'nope'" in run("grep", "x", "--device", "nope", code=1)
    assert "no source or device 'nope'" in run("read", "nope", "--page", "1", code=1)
    monkeypatch.setenv("NAPIER_SOURCES", str(tmp_path / "missing.yaml"))
    assert "no source list at" in run("status", code=1)
    monkeypatch.delenv("NAPIER_SOURCES")                 # installed from a package: no clone around it
    monkeypatch.setattr(cli.paths, "REPO_ROOT", tmp_path / "site-packages")
    assert "git clone https://github.com/bvk7787/napier" in run("status", code=1)
