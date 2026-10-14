"""Tests for polite fetching: cropping, Discourse topics, robots.txt, snapshots and backoff."""
import urllib.error

import pytest

from napier import refresh
from napier import sources as sm


def test_crop_start_and_stop():
    text = "Buy now $299\nCart\nProduct Updates\n1.76 Firmware Update\nfix\nRelated products\nX\n"
    src = sm.Source(id="x", device="d", kind="changelog", title="t", format="html",
                    start_at={"regex": "^Product Updates$"}, stop_at={"regex": "^Related products$"})
    assert sm.crop(text, src) == "Product Updates\n1.76 Firmware Update\nfix\n"
    assert sm.apply_start(text, {"regex": "^nope$"}) == text          # no match: keep everything


RAW = """alice | 2025-06-01 10:00:00 UTC | #1

First post.

-------------------------

bob | 2025-06-02 11:00:00 UTC | #2

Reply with a | pipe.
"""


def test_discourse_md(monkeypatch):
    calls = []

    def fake_get(url, timeout=60, headers=None, **kw):
        calls.append(url)
        return RAW.encode()

    monkeypatch.setattr(sm, "_get", fake_get)
    md = sm.discourse_md("https://www.elektronauts.com/t/some-topic/213312")
    assert calls == ["https://www.elektronauts.com/raw/213312?page=1"]   # one page: fewer than 100 posts
    assert "## #1 alice (2025-06-01)" in md and "## #2 bob (2025-06-02)" in md
    assert "-----" not in md and "Reply with a | pipe." in md


def test_robots(monkeypatch):
    body = "User-agent: *\nDisallow: /uc\nDisallow: /search\n"
    monkeypatch.setattr(sm, "_get", lambda url, timeout=20, headers=None, **kw: body.encode())
    assert sm.robots_allows("https://example.com/manual.pdf")[0]
    assert not sm.robots_allows("https://example.com/uc?export=download&id=1")[0]

    def boom(url, timeout=20, headers=None, **kw):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    monkeypatch.setattr(sm, "_get", boom)
    assert sm.robots_allows("https://example.com/x")[0]                   # no robots.txt (4xx): allowed

    def down(url, timeout=20, headers=None, **kw):
        raise urllib.error.HTTPError(url, 503, "down", {}, None)
    monkeypatch.setattr(sm, "_get", down)
    assert not sm.robots_allows("https://example.com/x")[0]               # unreachable (5xx): disallowed

    def offline(url, timeout=20, headers=None, **kw):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(sm, "_get", offline)
    assert not sm.robots_allows("https://example.com/x")[0]               # request failed: disallowed


def test_snapshot_not_fetched(monkeypatch):
    monkeypatch.setattr(sm, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    src = sm.Source(id="t", device="d", kind="community", title="t", format="discourse",
                    url="https://x/t/1", check=False)
    assert refresh.check_one(src).status == "snapshot"


@pytest.fixture
def net(monkeypatch):
    """A fake network: robots.txt per host from `robots`, documents from `docs`; records sleeps."""
    state = dict(robots={}, docs={}, calls=[], slept=[])
    monkeypatch.setattr(sm.time, "sleep", lambda s: state["slept"].append(s))
    for name in ("_last_hit", "_robots", "_delay"):
        monkeypatch.setattr(sm, name, {})

    def fake(url, timeout, headers, robots=True):
        state["calls"].append(url)
        if url.endswith("/robots.txt"):
            host = url.split("/")[2]
            if host not in state["robots"]:
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            return state["robots"][host].encode()
        v = state["docs"][url]
        if isinstance(v, Exception):
            raise v
        if callable(v):
            return v()
        return v
    monkeypatch.setattr(sm, "_urlopen", fake)
    return state


def test_every_request_is_spaced_and_backs_off(net):
    """_get carries the politeness for fetch, check, multi-page pulls and robots.txt alike."""
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] == 1:
            raise urllib.error.HTTPError("u", 429, "slow down", {"Retry-After": "7"}, None)
        return b"ok"

    net["docs"]["https://y.example/a.txt"] = flaky
    assert sm._get("https://y.example/a.txt") == b"ok"
    assert 7 in net["slept"]                                  # honoured Retry-After
    assert any(0 < s <= sm.SPACING for s in net["slept"])     # and spaced requests to the same host
    assert net["calls"].count("https://y.example/robots.txt") == 1


def test_robots_txt_is_checked_on_fetch_once_per_site(net):
    net["robots"]["d.example"] = "User-agent: *\nDisallow: /uc\n"
    net["docs"]["https://d.example/ok.pdf"] = b"%PDF-1"
    assert sm._get("https://d.example/ok.pdf") == b"%PDF-1"
    with pytest.raises(PermissionError, match="disallows"):
        sm._get("https://d.example/uc?id=1")
    assert net["calls"].count("https://d.example/robots.txt") == 1


def test_crawl_delay_is_honoured(net):
    net["robots"]["slow.example"] = "User-agent: *\nCrawl-delay: 5\n"
    net["docs"]["https://slow.example/a"] = b"a"
    net["docs"]["https://slow.example/b"] = b"b"
    sm._get("https://slow.example/a")
    sm._get("https://slow.example/b")
    assert any(s > sm.SPACING for s in net["slept"])


def test_too_long_a_retry_after_gives_up(net):
    net["docs"]["https://z.example/c.txt"] = urllib.error.HTTPError(
        "u", 503, "busy", {"Retry-After": str(sm.RETRY_AFTER_MAX + 1)}, None)
    with pytest.raises(urllib.error.HTTPError):
        sm._get("https://z.example/c.txt")


def test_retry_after_as_an_http_date():
    e = urllib.error.HTTPError("u", 503, "busy", {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, None)
    assert sm._retry_after(e) == 0.0                        # a date in the past: retry now


def test_only_public_http_urls_are_fetched():
    for bad in ("file:///etc/passwd", "ftp://example.com/x", "http://127.0.0.1:8000/x", "http://localhost/x",
                "http://10.0.0.5/manual.pdf", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(ValueError):
            sm.check_url(bad)


def test_fetch_goes_through_the_polite_path(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sm, "_get", lambda url, timeout=60, headers=None, **kw: calls.append(url) or b"text")
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path))
    src = sm.Source(id="t", device="d", kind="changelog", title="t", format="text", url="https://y.example/a.txt")
    sm.fetch_source(src)
    assert calls == ["https://y.example/a.txt"]


def test_entry_yaml_writes_only_check_false():
    assert "check" not in sm.entry_yaml(dict(id="a", device="d", check=True))
    assert "check: false" in sm.entry_yaml(dict(id="a", device="d", check=False))
