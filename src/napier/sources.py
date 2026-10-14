"""Source documents: sources.yaml entries, fetching, file checks and printed-page offsets."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from napier import paths

KINDS = ("manual", "changelog", "community", "note", "code")
FORMATS = ("pdf", "text", "markdown", "html", "gdoc", "github_releases", "discourse")
EXT = {"pdf": "pdf", "text": "txt", "markdown": "md", "html": "md", "gdoc": "md", "github_releases": "md",
       "discourse": "md"}
from napier import __version__  # noqa: E402

UA = f"napier/{__version__} (+https://github.com/bvk7787/napier; fetches each listed document once per run)"


@dataclass(frozen=True)
class Source:
    id: str
    device: str
    kind: str
    title: str
    format: str = "pdf"
    version: str = ""
    url: str = ""
    path: str = ""              # local file instead of a download (absolute or ~)
    sha256: str = ""            # pin: fetch and check refuse any other file
    fetched: str = ""
    page_offset: int = 0        # printed page = PDF page - page_offset
    heading: str = ""           # regex for section headings in text sources
    stop_at: dict = field(default_factory=dict, hash=False, compare=False)  # {regex, nth}
    start_at: dict = field(default_factory=dict, hash=False, compare=False)  # {regex, nth}
    check: bool = True          # False: a snapshot, fetched once and never re-checked upstream
    notes: str = ""
    base: str = field(default="", hash=False, compare=False)   # folder a relative `path` is relative to

    @property
    def is_pdf(self) -> bool:
        return self.format == "pdf"

    @property
    def file(self) -> Path:
        if self.path:
            p = Path(self.path).expanduser()
            return p if p.is_absolute() else (Path(self.base) if self.base else paths.REPO_ROOT) / p
        paths.check_name("source id", self.id)
        return paths.inside(paths.home() / "files", paths.home() / "files" / f"{self.id}.{EXT[self.format]}")

    def printed(self, pdf_page: int | None) -> int | None:
        """Printed page number for a 1-based PDF page, or None for unnumbered front matter."""
        if not pdf_page:
            return None
        p = pdf_page - self.page_offset
        return p if p >= 1 else None

    def pdf_page(self, printed: int) -> int:
        return printed + self.page_offset

    def cite_pages(self, pdf_pages) -> str:
        """'p. 11', 'pp. 11, 12', or 'PDF p. 3' for unnumbered front matter."""
        printed = [self.printed(p) for p in pdf_pages or []]
        nums = [str(p) for p in printed if p]
        front = [str(pg) for pg, p in zip(pdf_pages or [], printed, strict=True) if not p]
        parts = []
        if nums:
            parts.append(("p. " if len(nums) == 1 else "pp. ") + ", ".join(nums))
        if front:
            parts.append("PDF p. " + ", ".join(front))
        return "; ".join(parts)

    def label(self) -> str:
        return f"{self.title}, {self.version}" if self.version else self.title


def load_sources(file: Path | None = None) -> list[Source]:
    """Every source: the private overlay's list (local/sources.yaml) first, then the public one, or just `file`.
    A relative `path` resolves against the folder of the list it came from."""
    files = [file] if file else paths.sources_files()
    out, seen = [], {}
    for f in files:
        for s in _load_one(f):
            if s.id in seen:
                raise ValueError(f"{f}: source id {s.id!r} is already defined in {seen[s.id]}")
            seen[s.id] = f
            out.append(s)
    return out


def file_of(sid: str) -> Path:
    """The source list that defines `sid` (so edits go back to the right file)."""
    for f in paths.sources_files():
        if f.exists() and any((d or {}).get("id") == sid for d in yaml.safe_load(f.read_text()) or []):
            return f
    raise KeyError(f"no source {sid!r} in {', '.join(str(f) for f in paths.sources_files())}")


def _load_one(file: Path) -> list[Source]:
    if not file.exists():
        return []
    out, seen = [], set()
    base = "" if file.resolve().parent == paths.REPO_ROOT.resolve() else str(file.resolve().parent)
    for d in yaml.safe_load(file.read_text()) or []:
        sid = d.get("id")
        if not sid or not d.get("device"):
            raise ValueError(f"{file}: every source needs an id and a device ({d})")
        paths.check_name(f"{file}: source id", sid)
        paths.check_name(f"{file}: {sid}: device", d["device"])
        if d.get("url"):
            from urllib.parse import urlsplit
            if urlsplit(str(d["url"])).scheme not in ("http", "https"):
                raise ValueError(f"{file}: {sid}: only http(s) URLs (use `path` in your overlay for a local file)")
        if d.get("path") and not base:
            raise ValueError(f"{file}: {sid}: local files (`path`) belong in your overlay's sources.yaml")
        if sid in seen:
            raise ValueError(f"{file}: duplicate source id {sid!r}")
        seen.add(sid)
        kind, fmt = d.get("kind", "manual"), d.get("format", "pdf")
        if kind not in KINDS:
            raise ValueError(f"{sid}: kind {kind!r} is not one of {', '.join(KINDS)}")
        if fmt not in FORMATS:
            raise ValueError(f"{sid}: format {fmt!r} is not one of {', '.join(FORMATS)}")
        out.append(Source(id=sid, device=d["device"], kind=kind, title=d.get("title", sid), format=fmt,
                          version=str(d.get("version", "")), url=d.get("url", ""), path=d.get("path", ""),
                          sha256=d.get("sha256", ""), fetched=str(d.get("fetched", "")),
                          page_offset=int(d.get("page_offset", 0) or 0), heading=d.get("heading", ""),
                          stop_at=d.get("stop_at") or {}, start_at=d.get("start_at") or {},
                          check=bool(d.get("check", True)), notes=d.get("notes", ""), base=base))
    return out


def source_map(file: Path | None = None) -> dict[str, Source]:
    return {s.id: s for s in load_sources(file)}


def suggest(name: str, known) -> str:
    """'; did you mean x, y?' for a mistyped id or device (prefix and fuzzy matches), or ''."""
    import difflib
    known = sorted(set(known))
    head = name.split("_")[0]
    ranked = ([k for k in known if k.startswith(name)] + [k for k in known if k.startswith(head + "_")]
              + difflib.get_close_matches(name, known, n=3, cutoff=0.6) + [k for k in known if name in k])
    near = list(dict.fromkeys(ranked))[:3]
    return f"; did you mean {', '.join(near)}?" if near else ""


def select(sources: list[Source], ids=(), device: str | None = None, kind: str | None = None):
    """Sources matching ids, device and kind. An id or device that isn't in any list is an error, so a
    typo doesn't read as "no matches"."""
    known_ids, known_devices = {s.id for s in sources}, {s.device for s in sources}
    unknown = [i for i in ids if i not in known_ids]
    if unknown:
        raise ValueError(f"no source {', '.join(map(repr, unknown))}{suggest(unknown[0], known_ids)} "
                         "(napier source list shows them all)")
    if device and device not in known_devices:
        raise ValueError(f"no device {device!r}{suggest(device, known_devices)} (napier source list shows them all)")
    return [s for s in sources if (not ids or s.id in ids) and (not device or s.device == device)
            and (not kind or s.kind == kind)]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_source(src: Source) -> str | None:
    """A problem description, or None when the file is present (and matches its pin)."""
    f = src.file
    if not f.exists():
        return f"missing (run `napier fetch --source {src.id}`)"
    if src.is_pdf:
        with open(f, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                return "not a PDF (saved error page?)"
    if src.sha256 and file_sha256(f) != src.sha256:
        return "sha256 differs from sources.yaml (new version? update the entry)"
    return None


# ---------------------------------------------------------------- fetching

SPACING = 2.0              # seconds between requests to the same host (more if robots.txt asks)
RETRY_AFTER_MAX = 300      # seconds; a site asking for a longer wait gets skipped this run
MAX_BYTES = 300 * 1024 * 1024   # the largest response napier reads (manuals run to tens of MB)
DEADLINE = 600             # seconds for one whole response, however slowly it arrives
_last_hit: dict[str, float] = {}
_delay: dict[str, float] = {}          # host -> seconds between requests (robots.txt Crawl-delay)
_robots: dict[str, tuple[str, str]] = {}   # robots.txt URL -> ("ok", body) | ("4xx", why) | ("err", why)


def _space(url: str) -> None:
    """Never hit the same host twice within SPACING seconds, or its robots.txt Crawl-delay if longer
    (every request goes through _get)."""
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc
    wait = _last_hit.get(host, 0) + max(SPACING, _delay.get(host, 0)) - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    """Seconds to wait from a Retry-After header (seconds or an HTTP date); 30 when there's none."""
    v = ((e.headers or {}).get("Retry-After", "") or "").strip()  # type: ignore[call-overload]
    if not v:
        return 30.0
    if v.isdigit():
        return float(v)
    try:
        import datetime as _dt
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(v)
        return max(0.0, (when - _dt.datetime.now(when.tzinfo)).total_seconds())
    except (TypeError, ValueError, IndexError):
        return None


def check_url(url: str) -> None:
    """Refuse anything but http(s) to a public address: no file://, no localhost, no private network.
    A host that doesn't resolve here is left to the request (a proxy may resolve it)."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"only http(s) URLs are fetched: {url}")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except (socket.gaierror, UnicodeError):
        return
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])  # type: ignore[union-attr]
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified:
            raise ValueError(f"refusing {url}: {u.hostname} is a local or private address ({ip})")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a public http(s) address, and only where robots.txt allows it."""

    def __init__(self, robots: bool):
        super().__init__()
        self.robots = robots

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urljoin
        newurl = urljoin(req.full_url, newurl)
        check_url(newurl)
        if self.robots:
            ok, why = robots_allows(newurl, cache=True)
            if not ok:
                raise urllib.error.HTTPError(newurl, 403, f"redirect not followed: {why}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen(url: str, timeout: float, headers: dict | None, robots: bool = True) -> bytes:
    """One request: public http(s) only, at most MAX_BYTES, within DEADLINE seconds."""
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    opener = urllib.request.build_opener(_Redirects(robots))
    start, chunks, size = time.monotonic(), [], 0
    with opener.open(req, timeout=timeout) as r:
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            size += len(block)
            if size > MAX_BYTES:
                raise ValueError(f"{url}: larger than {MAX_BYTES // (1024 * 1024)} MB; not downloaded")
            if time.monotonic() - start > DEADLINE:
                raise TimeoutError(f"{url}: took longer than {DEADLINE} s; not downloaded")
            chunks.append(block)
    return b"".join(chunks)


def _get(url: str, timeout: float = 60, headers: dict | None = None, tries: int = 3, robots: bool = True) -> bytes:
    """Every HTTP request napier makes: allowed by robots.txt (checked once per site per run), spaced
    per host, and backing off on 429/503 (honouring Retry-After up to RETRY_AFTER_MAX; a longer ask
    or a third refusal raises). robots=False only for fetching robots.txt itself."""
    if robots:
        ok, why = robots_allows(url, cache=True)
        if not ok:
            raise PermissionError(f"{url}: {why}")
    for n in range(tries):
        _space(url)
        try:
            return _urlopen(url, timeout, headers, robots)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or n == tries - 1:
                raise
            wait = _retry_after(e)
            if wait is None or wait > RETRY_AFTER_MAX:
                raise
            time.sleep(wait)
    raise RuntimeError("unreachable")


def direct_url(url: str) -> str:
    """Google Drive share links -> direct download."""
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def gdoc_export(url: str) -> str:
    m = re.search(r"docs\.google\.com/document/d/([\w-]+)", url)
    if not m:
        raise ValueError(f"not a Google Doc URL: {url}")
    return f"https://docs.google.com/document/d/{m.group(1)}/export?format=md"


def clean_gdoc(md: str) -> str:
    """Drop embedded images (base64 data refs) and heading anchors from a Google Docs export."""
    md = re.sub(r"!\[[^\]]*\]\[[^\]]*\]", "", md)
    md = re.sub(r"^\[[^\]]+\]:\s*<?data:image[^\n]*\n?", "", md, flags=re.M)
    md = re.sub(r"\s*\{#[^}\n]*\}\s*$", "", md, flags=re.M)
    return md


def apply_stop(text: str, stop_at: dict) -> str:
    """Cut the text at the nth line matching stop_at.regex (e.g. a repeated title that starts
    an old copy of the document in a second tab)."""
    if not stop_at or not stop_at.get("regex"):
        return text
    rx, nth, seen = re.compile(stop_at["regex"]), int(stop_at.get("nth", 1)), 0
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if rx.search(ln):
            seen += 1
            if seen == nth:
                return "".join(lines[:i])
    return text


def apply_start(text: str, start_at: dict) -> str:
    """Drop everything before the nth line matching start_at.regex (e.g. a product page's
    'Product Updates' section), so unrelated page churn like prices doesn't count as a change."""
    if not start_at or not start_at.get("regex"):
        return text
    rx, nth, seen = re.compile(start_at["regex"]), int(start_at.get("nth", 1)), 0
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if rx.search(ln):
            seen += 1
            if seen == nth:
                return "".join(lines[i:])
    return text


def crop(text: str, src: "Source") -> str:
    return apply_stop(apply_start(text, src.start_at), src.stop_at)


def discourse_md(url: str, timeout: float = 60, max_pages: int = 20, title: str = "") -> str:
    """A whole Discourse topic as markdown via /raw/<topic_id>?page=N (100 posts a page): one
    '## #N user (date)' heading per post. Only the topic's own pages are fetched; no links followed."""
    m = re.match(r"(https?://[^/]+)/t/(?:[^/]+/)?(\d+)", url)
    if not m:
        raise ValueError(f"not a Discourse topic URL: {url}")
    base, tid = m.group(1), m.group(2)
    head = re.compile(r"^(\S.*?) \| (\d{4}-\d{2}-\d{2})[^|]*\| #(\d+)\s*$", re.M)
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        raw = _get(f"{base}/raw/{tid}?page={page}", timeout).decode("utf-8", "replace")
        posts = head.findall(raw)
        new = [p for p in posts if p[2] not in seen]
        if not new:
            break
        seen |= {p[2] for p in posts}
        raw = re.sub(r"^-{25}\s*$", "", raw, flags=re.M)
        out.append(head.sub(lambda x: f"## #{x.group(3)} {x.group(1)} ({x.group(2)})", raw))
        if len(posts) < 100:
            break
    return f"# {title or url}\n\nForum thread: {url}\n\n" + "\n".join(out)


def github_releases_md(url: str, timeout: float = 60) -> str:
    """All releases of a GitHub repo as markdown, newest first: one '## tag (date)' per release."""
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", url) or re.match(r"github:([\w.-]+)/([\w.-]+)", url)
    if not m:
        raise ValueError(f"not a GitHub repo URL: {url}")
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    out, page = [f"# {owner}/{repo} releases\n"], 1
    while True:
        data = json.loads(_get(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100&page={page}",
                               timeout, headers))
        if not data:
            break
        for r in data:
            date = (r.get("published_at") or "")[:10]
            body = (r.get("body") or "").replace("\r\n", "\n").strip()
            body = re.sub(r"^(#{1,5})\s", lambda x: "#" * (len(x.group(1)) + 2) + " ", body, flags=re.M)
            out.append(f"## {r.get('name') or r['tag_name']} ({date})\n\n{body}\n")
        page += 1
    return "\n".join(out)


def download(src: Source, timeout: float = 60) -> bytes:
    if not src.url:
        raise ValueError(f"{src.id}: no url to fetch from")
    if src.format == "gdoc":
        text = clean_gdoc(_get(gdoc_export(src.url), timeout).decode("utf-8", "replace"))
        return crop(text, src).encode()
    if src.format == "github_releases":
        return crop(github_releases_md(src.url, timeout), src).encode()
    if src.format == "discourse":
        return crop(discourse_md(src.url, timeout, title=src.title), src).encode()
    if src.format == "html":
        from napier.htmlmd import html_to_md
        text = html_to_md(_get(direct_url(src.url), timeout).decode("utf-8", "replace"))
        return crop(text, src).encode()
    data = _get(direct_url(src.url), timeout)
    if src.format in ("text", "markdown") and (src.stop_at or src.start_at):
        data = crop(data.decode("utf-8", "replace"), src).encode()
    return data


def fetch_source(src: Source, timeout: float = 60, from_file: Path | None = None) -> Path:
    """Download to src.file (or take from_file, a copy the user downloaded in a browser), refusing a
    non-PDF for a PDF source and any file that breaks the pin."""
    if src.path:
        raise ValueError(f"{src.id}: local file source, nothing to fetch")
    data = Path(from_file).read_bytes() if from_file else download(src, timeout)
    if src.is_pdf and not data.startswith(b"%PDF-"):
        raise ValueError(f"{src.id}: {from_file or src.url} is not a PDF")
    if src.sha256 and hashlib.sha256(data).hexdigest() != src.sha256:
        raise ValueError(f"{src.id}: downloaded file sha256 differs from sources.yaml (new version?)")
    dest = src.file
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def robots_allows(url: str, timeout: float = 20, cache: bool = False) -> tuple[bool, str]:
    """(allowed, why) per the site's robots.txt for our user agent, as RFC 9309 says: a robots.txt
    that's unavailable (4xx) allows everything; one that's unreachable (5xx, or the request fails)
    disallows everything until it can be read. cache=True reuses a robots.txt already read this run
    (the fetch path); cache=False reads it again. A Crawl-delay longer than SPACING is honoured for that site."""
    import urllib.robotparser
    from urllib.parse import urlsplit
    u = urlsplit(direct_url(url))
    robots = f"{u.scheme}://{u.netloc}/robots.txt"
    got = _robots.get(robots) if cache else None
    if got is None:
        try:
            got = ("ok", _get(robots, timeout, robots=False).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            got = ("4xx", f"no robots.txt (HTTP {e.code})") if 400 <= e.code < 500 else \
                ("err", f"robots.txt unreachable (HTTP {e.code}); treated as disallowed until it can be read")
        except Exception as e:  # noqa: BLE001
            got = ("err", f"robots.txt unreachable ({type(e).__name__}); treated as disallowed until it can be read")
        _robots[robots] = got           # a later fetch from the same site this run reuses it
    if got[0] == "4xx":
        return True, got[1]
    if got[0] == "err":
        return False, got[1]
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(got[1].splitlines())
    delay = rp.crawl_delay(UA)
    if delay:
        _delay[u.netloc] = float(delay)
    ok = rp.can_fetch(UA, direct_url(url))
    return ok, f"robots.txt {'allows' if ok else 'disallows'} {u.path or '/'}"


# ---------------------------------------------------------------- page offsets

_num_only = re.compile(r"^(\d{1,4})$")
_num_first = re.compile(r"^(\d{1,4})\s+\D.{3,}$")
_num_last = re.compile(r"^.{3,}\D\s+(\d{1,4})$")
_num_prefixed = re.compile(r"^(?:pg\.?|page|p\.)\s*(\d{1,4})$", re.I)

# Invisible direction marks some PDF exporters wrap around text (Intellijel's Google Docs exports).
_BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# A detected offset is only trusted when enough pages carry a number and most of them agree.
# Below this, a stray number in a header (a figure, a part number, a TOC line) can win the vote.
MIN_NUMBERED = 3
MIN_AGREE = 0.5


def offset_trusted(agree: int, total: int) -> bool:
    """Whether detect_offset's answer is safe to write without a human check."""
    return total >= MIN_NUMBERED and agree / total >= MIN_AGREE


def page_number_in(lines: list[str]) -> int | None:
    """A printed page number in a page's footer or header.

    Footers are checked first, bottom line up, and prefer a trailing number ("Planar 2 Manual 11");
    headers are checked after, top line down, and prefer a leading number. Checking headers first let
    a wrapped product name ("Planar" / "2") win the vote.
    """
    def first_match(ln, order):
        ln = _BIDI.sub("", ln).strip()
        for rx in order:
            m = rx.match(ln)
            if m:
                return int(m.group(1))
        return None

    foot = (_num_only, _num_prefixed, _num_last, _num_first)
    head = (_num_only, _num_prefixed, _num_first, _num_last)
    for ln in reversed(lines[-3:]):
        n = first_match(ln, foot)
        if n is not None:
            return n
    for ln in lines[:3]:
        n = first_match(ln, head)
        if n is not None:
            return n
    return None


def detect_offset(pdf_path: Path) -> tuple[int, int, int]:
    """(offset, pages agreeing, pages with a number): printed = PDF page - offset."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    votes = collections.Counter()
    try:
        for i in range(len(pdf)):
            lines = pdf[i].get_textpage().get_text_range().strip().splitlines()
            n = page_number_in(lines)
            if n is not None:
                votes[(i + 1) - n] += 1
    finally:
        pdf.close()
    if not votes:
        return 0, 0, 0
    off, agree = votes.most_common(1)[0]
    return off, agree, sum(votes.values())


def entry_yaml(d: dict) -> str:
    """A sources.yaml entry as text, for appending without disturbing comments."""
    order = ["id", "device", "kind", "format", "title", "version", "url", "path", "fetched", "sha256",
             "page_offset", "heading", "start_at", "stop_at", "check", "notes"]
    keep = {k: d[k] for k in order if d.get(k) not in (None, "", {})}
    if keep.get("check") is True:
        keep.pop("check")            # the default; only write check: false
    body = yaml.safe_dump([keep],
                          sort_keys=False, allow_unicode=True, width=120)
    return "\n" + body
