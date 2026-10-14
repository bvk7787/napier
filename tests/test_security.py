"""What a hostile source list, fact id, server or query can't do: reach outside napier's folders, fetch
anything but public http(s), download without limit, or hang a grep."""
import io
import urllib.request

import pytest

from napier import facts, paths, text
from napier import sources as sm


def write_sources(tmp_path, monkeypatch, body: str):
    f = tmp_path / "sources.yaml"
    f.write_text(body)
    monkeypatch.setenv("NAPIER_SOURCES", str(f))
    return f


@pytest.mark.parametrize("sid, device", [("../../etc/passwd", "box"), ("box", "../facts/x"), ("Box", "box"),
                                         ("a/b", "box"), ("box", "")])
def test_ids_and_devices_are_plain_names(tmp_path, monkeypatch, sid, device):
    write_sources(tmp_path, monkeypatch, f"- {{id: '{sid}', device: '{device}', url: 'https://x.test/a.pdf'}}\n")
    with pytest.raises(ValueError):
        sm.load_sources()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.test/a.pdf", "javascript:alert(1)"])
def test_only_http_urls_are_listed(tmp_path, monkeypatch, url):
    write_sources(tmp_path, monkeypatch, f"- {{id: box, device: box, url: '{url}'}}\n")
    with pytest.raises(ValueError, match="only http"):
        sm.load_sources()


def test_the_public_list_points_at_no_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)        # the list is the clone's own sources.yaml
    write_sources(tmp_path, monkeypatch, "- {id: box, device: box, format: text, path: /etc/passwd}\n")
    with pytest.raises(ValueError, match="overlay"):
        sm.load_sources()


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.pdf", "http://localhost/a.pdf", "http://10.0.0.8/a.pdf",
                                 "http://169.254.169.254/latest/meta-data", "http://[::1]/a.pdf", "file:///etc/passwd"])
def test_requests_go_only_to_public_addresses(url):
    with pytest.raises(ValueError):
        sm.check_url(url)


def test_a_redirect_to_a_private_address_is_refused():
    h = sm._Redirects(robots=False)
    req = urllib.request.Request("https://maker.example/manual.pdf")
    with pytest.raises(ValueError, match="private"):
        h.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8080/admin")


class _Endless(io.RawIOBase):
    """A response body that never ends."""
    def read(self, n=-1):
        return b"x" * (n if n and n > 0 else 1024)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_downloads_stop_at_the_size_cap(monkeypatch):
    monkeypatch.setattr(sm, "check_url", lambda url: None)
    monkeypatch.setattr(sm, "MAX_BYTES", 3 << 20)
    opener = type("O", (), {"open": lambda self, req, timeout: _Endless()})()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: opener)
    with pytest.raises(ValueError, match="larger than 3 MB"):
        sm._urlopen("https://maker.example/huge.pdf", 5, None)


@pytest.mark.parametrize("device", ["../../outside", "/etc/passwd", "a/b", "M8"])
def test_fact_files_stay_in_the_facts_folders(tmp_path, monkeypatch, device):
    monkeypatch.setenv("NAPIER_FACTS", str(tmp_path / "facts"))
    with pytest.raises(ValueError):
        facts.facts_file(device)
    with pytest.raises(ValueError):
        facts.add(device, "a claim", status="unverified")
    assert not (tmp_path / "outside.yaml").exists()


def test_text_files_stay_in_the_home_folder():
    with pytest.raises(ValueError):
        text.units_file("../../escape")


@pytest.mark.parametrize("q", ["(a+)+$", "(x*)*y", "(.*a){12}", "a" * 300, "(unclosed"])
def test_risky_or_broken_regexes_are_refused(q):
    with pytest.raises(ValueError):
        text.check_regex(q)


def test_ordinary_regexes_pass():
    assert text.check_regex(r"\[SHIFT\]\s*\+\s*\[(PLAY|EDIT)\]")
