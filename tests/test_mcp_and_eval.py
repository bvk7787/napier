"""MCP tool functions called directly, the eval gate with a stub searcher, and --help for every command."""
import asyncio
import sys
from dataclasses import dataclass

import click
import pytest
import yaml
from click.testing import CliRunner

from napier import cli, evaluate

# ---------------------------------------------------------------- MCP tools

SOURCES = """\
- id: box_log
  device: box
  kind: changelog
  format: text
  title: Box changelog
  path: log.txt
  heading: '^## '
"""


@pytest.fixture
def box(tmp_path, monkeypatch):
    (tmp_path / "log.txt").write_text("## 1.2\n- New: hold [SHIFT]+[PLAY] restarts\n## 1.1\n- Fix: clock drift\n")
    (tmp_path / "sources.yaml").write_text(SOURCES)
    monkeypatch.setenv("NAPIER_SOURCES", str(tmp_path / "sources.yaml"))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    assert "text box_log" in CliRunner().invoke(cli.main, ["ingest", "--text-only"]).output
    return tmp_path


def test_mcp_tools_grep_read_and_fact_guards(box):
    mcp = pytest.importorskip("napier.mcp_server")
    tools = asyncio.run(mcp.server.list_tools())
    for t in tools:                                    # the desktop bridge drops an argument named `device`
        schema = getattr(t, "input_schema", None) or t.inputSchema   # mcp 2.x / 1.x
        assert "device" not in (schema.get("properties") or {}), t.name
    st = mcp.status()["sources"]
    assert st == [dict(id="box_log", device="box", kind="changelog", title="Box changelog", version="",
                       file="ok", text=True, indexed=False)]
    out = mcp.grep("[shift]+[play]", device_id="box")
    assert [(h["source_id"], h["cite"]) for h in out["hits"]] == [("box_log", "Box changelog, § 1.2")]
    assert out["not_extracted"] == [] and "hint" not in out
    assert mcp.grep("clock drift", source="box_log")["hits"][0]["line"] == "- Fix: clock drift"
    assert [s["title"] for s in mcp.read("box", toc=True)] == ["1.2", "1.1"]
    assert "restarts" in mcp.read("box_log", section="1.2")["text"]
    # errors reach the assistant as ToolError with the reason, not "Error executing tool"
    with pytest.raises(mcp.ToolError, match="give page"):
        mcp.read("box_log")
    with pytest.raises(mcp.ToolError, match="needs notes"):
        mcp.add_fact("box", "restart combo works", status="hardware")
    f = mcp.add_fact("box", "SHIFT+PLAY restarts", status="changelog", cite="https://x.test/log")
    assert f["via"] == "mcp" and mcp.facts(device_id="box")[0]["id"] == f["id"]
    with pytest.raises(mcp.ToolError, match="needs a note"):
        mcp.verify_fact(f["id"], "refuted")
    with pytest.raises(mcp.ToolError, match="^no source or device 'nope'"):   # a click error reads plainly
        mcp.read("nope", page=1)
    with pytest.raises(mcp.ToolError, match="no device 'bx'; did you mean box"):
        mcp.grep("x", device_id="bx")
    with pytest.raises(mcp.ToolError, match="no device"):
        mcp.add_fact("not_a_device", "anything", status="community", cite="https://x.test")
    with pytest.raises(mcp.ToolError, match="no device '../../etc'"):
        mcp.add_fact("../../etc", "anything", status="community", cite="https://x.test")
    with pytest.raises(mcp.ToolError, match="public ledger"):     # no overlay here, so f is public
        mcp.verify_fact(f["id"], "hardware", note="tried on 1.2")
    v = mcp.verify_fact(f["id"], "refuted", note="gone in 1.3")
    assert v["status"] == "refuted" and mcp.facts(status="refuted")[0]["id"] == f["id"]


def test_mcp_rack_tool_keeps_wishlist_flagged(monkeypatch):
    mcp = pytest.importorskip("napier.mcp_server")
    monkeypatch.delenv("NAPIER_CATALOG")                # the shipped example rack + catalog
    full = mcp.rack()
    owned = mcp.rack(include_wishlist=False)
    assert all(m["owned"] for m in owned["modules"])
    assert len(full["modules"]) >= len(owned["modules"]) and full["rack"]["name"] == "Example Rack"
    clocked = mcp.rack(jack_type="clock", jack_dir="in")
    assert all(any(j["type"] == "clock" or "clock" in (j.get("also") or []) for j in m["jacks"])
               for m in clocked["modules"])


# ---------------------------------------------------------------- eval gate


@dataclass
class H:
    text: str
    source_id: str
    printed: list


class StubSearcher:
    def __init__(self, rerank_model=None):
        self.sources = {}

    def search(self, q, device=None, kind=None, top=10, **kw):
        return {"found": [H("noise", "m", [1]), H("Hold SHIFT and PLAY to restart", "m", [7])],
                "wrongpage": [H("Hold SHIFT and PLAY to restart", "m", [9])],
                "missing": [H("nothing useful", "m", [1])]}[q][:top]


def fact(fid, q, pages=(7,)):
    return dict(id=fid, device="d", source="m", q=q, anchors=["SHIFT and PLAY", "restart"], pages=list(pages))


def test_evaluate_ranks_and_checks_cited_page():
    r = evaluate.evaluate(StubSearcher(), [fact("a", "found"), fact("b", "wrongpage"), fact("c", "missing")])
    assert r.ranks == {"a": 2, "b": 1, "c": None}
    assert r.page_ok == {"a": True, "b": False, "c": False}
    assert r.hit(1) == pytest.approx(1 / 3) and r.hit(3) == pytest.approx(2 / 3)
    assert "cited page correct 1/3" in r.summary()


def test_eval_command_exit_code_follows_the_gate(tmp_path, monkeypatch):
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "d.yaml").write_text(yaml.safe_dump([fact("a", "found"), fact("c", "missing")]))
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    stub = type("M", (), {"Searcher": StubSearcher, "RERANK_MODEL": None})
    monkeypatch.setattr(cli, "_need", lambda m: evaluate if m == "evaluate" else stub)
    r = CliRunner().invoke(cli.main, ["eval", "--show-misses"])
    assert r.exit_code == 1 and "hit@3 50% is below the 90% gate" in r.output and "c " in r.output
    assert CliRunner().invoke(cli.main, ["eval", "--min-hit3", "0.5"]).exit_code == 0


def test_missing_index_extra_is_one_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "lancedb", None)        # as if the [index] extra weren't installed
    for args in (["search", "anything"], ["eval"], ["ingest"]):
        r = CliRunner().invoke(cli.main, args)
        assert r.exit_code == 1 and "need the index extra" in r.output and "Traceback" not in r.output, args


# ---------------------------------------------------------------- every command's --help


def _commands(group, prefix=()):
    for name, cmd in group.commands.items():
        yield prefix + (name,)
        if isinstance(cmd, click.Group):
            yield from _commands(cmd, prefix + (name,))


@pytest.mark.parametrize("path", list(_commands(cli.main)), ids=" ".join)
def test_every_command_has_help(path):
    r = CliRunner().invoke(cli.main, [*path, "--help"])
    assert r.exit_code == 0 and "Usage:" in r.output, r.output


def test_mcp_search_says_which_sources_it_could_not_search(box, monkeypatch):
    mcp = pytest.importorskip("napier.mcp_server")
    hit = type("Hit", (), dict(source_id="box_log", cite="Box changelog, § 1.2", kind="changelog", headings="1.2",
                               text="hold [SHIFT]+[PLAY] restarts"))
    monkeypatch.setattr(mcp, "_searcher", type("S", (), {"search": lambda self, q, **kw: [hit]})())
    out = mcp.search("how do I restart", device_id="box")
    assert out["hits"][0]["source_id"] == "box_log"
    assert out["not_indexed"] == ["box_log"] and "napier ingest --device box" in out["hint"]   # text only so far
