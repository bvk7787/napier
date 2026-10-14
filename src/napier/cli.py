"""napier: look things up in device manuals, changelogs and community docs.

\b
  napier fetch --device ID | --all            download sources
  napier ingest [--text-only] [--device ID]   text for grep, index for search
  napier status                               what you have, per device
  napier search "<question>" [--device ID]    meaning-based, needs the index
  napier grep "<text>" [--device ID]          exact text, no index needed
  napier read <source|device> --page N | --section "<title>" | --toc
  napier facts list | add | verify | show
  napier eval                                 test search against the facts
  napier source list | add | offset | check | apply
  napier rack sync | view | scenarios | ...   your rack (see docs/rack.md)
  napier mcp                                  the same tools, for assistants
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.table import Table

from napier import facts as factsmod
from napier import paths
from napier.sources import (
    FORMATS,
    KINDS,
    Source,
    check_source,
    detect_offset,
    entry_yaml,
    fetch_source,
    file_sha256,
    load_sources,
    offset_trusted,
    robots_allows,
)
from napier.sources import (
    select as _select_sources,
)

console = Console()
say = lambda m: console.print(m, markup=False, highlight=False, soft_wrap=True)  # noqa: E731  (the terminal wraps)


def emit(obj):
    click.echo(json.dumps(obj, indent=1, ensure_ascii=False, default=str))


INDEX_DEPS = ("lancedb", "sentence_transformers", "docling")


def _need(module: str):
    """Import an optional napier module and, for the index ones, the index extra's packages, so a missing
    extra is one clear error instead of a traceback halfway through."""
    import importlib
    try:
        mod = importlib.import_module(f"napier.{module}")
        if module in ("search", "evaluate", "store", "parse"):
            for dep in INDEX_DEPS:
                importlib.import_module(dep)
        return mod
    except ImportError as e:
        raise click.ClickException(f"{e}. Search, eval and full ingest need the index extra: "
                                   f"{paths.install_hint('index,mcp')}") from e


def resolve(ref: str, sources: list[Source]) -> Source:
    """A source id, or a device id (its manual, or its only source)."""
    by_id = {s.id: s for s in sources}
    if ref in by_id:
        return by_id[ref]
    dev = [s for s in sources if s.device == ref]
    manuals = [s for s in dev if s.kind == "manual"]
    if len(manuals) == 1 or len(dev) == 1:
        return (manuals or dev)[0]
    if dev:
        raise click.ClickException(f"{ref} has several sources; pick one: {', '.join(s.id for s in dev)}")
    raise click.ClickException(f"no source or device {ref!r} (see `napier source list`)")


CLONE_HINT = ("napier runs from a clone of its repository: its sources, facts, specs and catalog are data you "
              "read and edit there. git clone https://github.com/bvk7787/napier && cd napier && "
              "uv tool install -e . (or pip install -e . in a virtual environment).")


@click.group(help=__doc__)
@click.version_option(package_name="napier", message="%(prog)s %(version)s (" + (
    f"from {paths.REPO_ROOT}" if (paths.REPO_ROOT / "sources.yaml").exists() else
    "not run from a clone; see https://github.com/bvk7787/napier#try-it") + ")")
def main():
    if not paths.sources_file().exists():
        if os.environ.get("NAPIER_SOURCES"):
            raise click.ClickException(f"no source list at {paths.sources_file()} (NAPIER_SOURCES)")
        raise click.ClickException(f"this napier wasn't installed from a clone. {CLONE_HINT}")


# ---------------------------------------------------------------- status / fetch / ingest

@main.command()
@click.option("--device", default=None, help="Only this device's sources")
@click.option("--wide", is_flag=True, help="One row per source instead of one per device")
@click.option("--json", "as_json", is_flag=True)
def status(device, wide, as_json):
    """What's downloaded, extracted and indexed, per device (--wide: per source)."""
    from napier.store import load_state
    state = load_state()
    rows = []
    for s in select(load_sources(), (), device):
        st = state.get(s.id, {})
        rows.append(dict(id=s.id, device=s.device, kind=s.kind, version=s.version, file=check_source(s) or "ok",
                         text=st.get("text_units"), chunks=st.get("chunks"), page_offset=s.page_offset,
                         ingested=st.get("ingested")))
    if as_json:
        return emit(dict(home=str(paths.home()), sources=rows,
                         embed_models=sorted({v["embed_model"] for v in state.values() if v.get("embed_model")})))
    if wide:
        t = Table(title=f"napier sources ({paths.home()})", box=box.SIMPLE)
        for col in ("id", "device", "kind", "version", "file", "text", "index", "offset"):
            t.add_column(col, no_wrap=col in ("id", "device", "kind"))
        for r in rows:
            t.add_row(r["id"], r["device"], r["kind"], r["version"],
                      "[green]ok[/green]" if r["file"] == "ok" else f"[red]{r['file']}[/red]",
                      str(r["text"] or "-"), f"{r['chunks']} chunks" if r["chunks"] else "-", str(r["page_offset"]))
        console.print(t)
        return
    by_dev: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_dev[r["device"]].append(r)
    frac = lambda n, d: f"[green]{n}/{d}[/green]" if n == d else (f"[dim]0/{d}[/dim]" if n == 0 else f"{n}/{d}")  # noqa: E731
    t = Table(box=box.SIMPLE, pad_edge=False)
    for col in ("device", "files", "text", "index"):
        t.add_column(col, no_wrap=True, justify="left" if col == "device" else "right")
    for dev, rs in sorted(by_dev.items()):
        n = len(rs)
        t.add_row(dev, frac(sum(r["file"] == "ok" for r in rs), n), frac(sum(bool(r["text"]) for r in rs), n),
                  frac(sum(bool(r["chunks"]) for r in rs), n))
    console.print(t)
    n = len(rows)
    files, text, index = (sum(r["file"] == "ok" for r in rows), sum(bool(r["text"]) for r in rows),
                          sum(bool(r["chunks"]) for r in rows))
    plural = lambda k, word: f"{k} {word}{'' if k == 1 else 's'}"  # noqa: E731
    say(f"{plural(n, 'source')} for {plural(len(by_dev), 'device')} in {paths.home()}: {files} downloaded, "
        f"{text} extracted, {index} indexed.")
    if files < n:
        say("Next: napier fetch --device ID (or --all), then napier ingest. --wide shows each source.")
    elif text < n or index < n:
        say("Next: napier ingest (--text-only skips the search index). --wide shows each source.")


@main.command()
@click.option("--source", "ids", multiple=True, help="Only these source ids")
@click.option("--device", default=None, help="Only this device's sources (e.g. m8_tracker)")
@click.option("--all", "fetch_all", is_flag=True, help="Every source in the lists (about 150, several hundred MB)")
@click.option("--force", is_flag=True, help="Download again even if the file is already here")
@click.option("--from", "from_file", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Use a file you downloaded yourself (one --source; checked against its pin)")
def fetch(ids, device, fetch_all, force, from_file):
    """Download sources that aren't here yet. Pinned files (sha256) must match exactly; files already
    present are left alone (`napier source check` looks for upstream changes, politely)."""
    if from_file:
        if len(ids) != 1:
            raise click.UsageError("--from takes exactly one --source")
        s = select(load_sources(), ids)[0]
        try:
            f = fetch_source(s, from_file=Path(from_file))
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        say(f"{s.id}: {from_file} checks out -> {f}")
        return
    if not ids and not device and not fetch_all:
        raise click.UsageError("say what to fetch: --device ID, --source ID, or --all for every source "
                               "(see `napier source list`)")
    failed = 0
    for s in select(load_sources(), ids, device):
        if s.path:
            say(f"{s.id}: local file ({check_source(s) or 'ok'})")
            continue
        if check_source(s) is None and not force:
            say(f"{s.id}: ok")
            continue
        try:
            f = fetch_source(s)
            say(f"{s.id}: downloaded -> {f}")
        except PermissionError as e:
            failed += 1
            console.print(f"[red]{s.id}: not downloaded: {e}[/red]")
            say(f"  The site's robots.txt doesn't allow automated downloads of this file. Download it in a "
                f"browser from {s.url} and run: napier fetch --source {s.id} --from <the file>")
        except Exception as e:  # noqa: BLE001
            failed += 1
            msg = str(e)
            console.print(f"[red]{msg if msg.startswith(s.id) else f'{s.id}: {msg}'}[/red]")
    if failed:
        raise click.ClickException(f"{failed} source{'s' if failed != 1 else ''} not downloaded")


@main.command()
@click.option("--source", "ids", multiple=True, help="Only these source ids")
@click.option("--device", default=None, help="Only this device's sources (e.g. m8_tracker)")
@click.option("--force", is_flag=True, help="Redo even if unchanged")
@click.option("--text-only", is_flag=True, help="Only the text layer (grep/read), no embeddings")
@click.option("--embed-model", default=None, help="Embedding model (Hugging Face id); changing it rebuilds the index")
def ingest(ids, device, force, text_only, embed_model):
    """Extract text (for grep/read) and index chunks (for search). Unchanged sources are skipped."""
    if not text_only:
        _need("store")
    from napier.store import EMBED_MODEL, Store
    allsrc = load_sources()
    srcs = select(allsrc, ids, device)
    rep = Store().ingest(srcs, embed_model=embed_model or EMBED_MODEL, force=force, text_only=text_only,
                         all_sources=allsrc, log=say)
    for sid, n in rep.text.items():
        console.print(f"[green]text[/green] {sid}: {n} units")
    for sid, n in rep.added.items():
        console.print(f"[green]indexed[/green] {sid}: {n} chunks")
    if rep.skipped:
        say(f"unchanged: {', '.join(rep.skipped)}")
    for sid in rep.removed:
        console.print(f"[yellow]removed[/yellow] {sid} (no longer in sources.yaml)")
    for sid, why in rep.problems.items():
        console.print(f"[red]{sid}: {why}[/red]")


# ---------------------------------------------------------------- search / grep / read

@main.command()
@click.argument("query")
@click.option("--device", default=None, help="Device id, e.g. m8_tracker")
@click.option("--kind", type=click.Choice(KINDS), default=None, help="Only this kind of source")
@click.option("--top", default=5, show_default=True, help="How many results")
@click.option("--no-rerank", is_flag=True, help="Skip the cross-encoder (faster)")
@click.option("--full", is_flag=True, help="Whole chunks")
@click.option("--json", "as_json", is_flag=True)
def search(query, device, kind, top, no_rerank, full, as_json):
    """Meaning-based search; each result cites title, version and printed pages."""
    sm = _need("search")
    s = sm.Searcher(rerank_model=None if no_rerank else sm.RERANK_MODEL)
    hits = s.search(query, device=device, kind=kind, top=top, rerank=not no_rerank)
    if as_json:
        return emit([h.as_dict() for h in hits])
    for i, h in enumerate(hits, 1):
        text = h.text if full else (h.text[:600] + (" ..." if len(h.text) > 600 else ""))
        where = f" > {h.headings}" if h.headings else ""
        console.print(f"[bold]{i}. {h.cite}[/bold] [dim]{h.kind}{where}[/dim]", highlight=False)
        say(text)
        say("")


@main.command()
@click.argument("text")
@click.option("--device", default=None, help="Only this device's sources (e.g. m8_tracker)")
@click.option("--source", "ids", multiple=True, help="Only these source ids")
@click.option("--kind", type=click.Choice(KINDS), default=None, help="Only this kind of source")
@click.option("--regex", is_flag=True, help="TEXT is a regular expression")
@click.option("--case", is_flag=True, help="Case-sensitive")
@click.option("-C", "context", default=1, show_default=True, help="Lines of context")
@click.option("--max", "max_hits", default=40, show_default=True, help="Stop after this many hits")
@click.option("--json", "as_json", is_flag=True)
def grep(text, device, ids, kind, regex, case, context, max_hits, as_json):
    """Exact text search over the text layer. A space matches any whitespace; + matches with or without spaces around it."""
    from napier.text import grep as do_grep
    from napier.text import has_text
    srcs = select(load_sources(), ids, device, kind)
    missing = [s.id for s in srcs if not has_text(s.id)]
    try:
        hits = do_grep(text, [s for s in srcs if has_text(s.id)], regex, not case, context, max_hits)
    except ValueError as e:  # a regular expression that won't compile, or one napier refuses
        raise click.ClickException(str(e)) from e
    if as_json:
        return emit(dict(hits=[h.as_dict() for h in hits], not_extracted=missing))
    for h in hits:
        head = f" [dim]{h.heading}[/dim]" if h.heading and h.heading not in h.cite else ""
        console.print(f"[bold]{h.source_id}[/bold] {h.cite}{head}", highlight=False)
        for ln in h.before:
            say(f"    {ln}")
        say(f"  > {h.line}")
        for ln in h.after:
            say(f"    {ln}")
    if not hits:
        say("no matches")
    if len(hits) >= max_hits:
        say(f"(stopped at {max_hits}; raise --max)")
    if missing:
        shown = ", ".join(missing[:8]) + (f" and {len(missing) - 8} more" if len(missing) > 8 else "")
        console.print(f"[yellow]not searched, no text yet: {shown}[/yellow]", soft_wrap=True)
        if device and not ids:
            fetch_args = ingest_args = f" --device {device}"
        elif len(missing) <= 3:
            fetch_args = ingest_args = "".join(f" --source {i}" for i in missing)
        else:
            fetch_args, ingest_args = " --all", ""
        say(f"  napier fetch{fetch_args} && napier ingest --text-only{ingest_args}")


@main.command()
@click.argument("ref")
@click.option("--page", type=int, help="Printed page number")
@click.option("--pdf-page", type=int, help="PDF page index (1-based)")
@click.option("--section", help="Heading text (case-insensitive substring)")
@click.option("--nth", default=1, show_default=True, help="Which match, when several headings match")
@click.option("--toc", is_flag=True, help="List headings")
@click.option("--raw", is_flag=True, help="PDF text layer instead of Docling markdown")
@click.option("--max-chars", default=8000, show_default=True, help="Cut a long section after this many characters")
@click.option("--json", "as_json", is_flag=True)
def read(ref, page, pdf_page, section, nth, toc, raw, max_chars, as_json):
    """Read a page or a whole section. REF is a source id, or a device id for its manual."""
    from napier import text as tx
    src = resolve(ref, load_sources())
    if not tx.has_text(src.id):
        raise click.ClickException(f"{src.id} isn't extracted yet: napier ingest --source {src.id} --text-only")
    try:
        if toc:
            out = tx.sections(src)
            if as_json:
                return emit(out)
            for s in out:
                say(f"{'  ' * max(0, s['level'] - 1)}{s['title']}  [{s['cite']}]")
            return
        if section:
            out = tx.read_section(src, section, max_chars, nth)
        elif page or pdf_page:
            out = tx.read_page(src, page, pdf_page, raw)
        else:
            raise click.UsageError("give --page, --pdf-page, --section or --toc")
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if as_json:
        return emit(out)
    console.print(f"[bold]{out['title']}, {out['cite']}[/bold]", highlight=False)
    if out.get("matches", 1) > 1:
        say(f"({out['matches']} headings match; showing #{nth}, use --nth)")
    say(out["text"])


# ---------------------------------------------------------------- sources

@main.group()
def source():
    """List, add, or check sources."""


@source.command("list")
@click.option("--device", default=None, help="Only this device's sources")
@click.option("--json", "as_json", is_flag=True)
def source_list(device, as_json):
    """Every source: id, device, kind, title and version."""
    srcs = select(load_sources(), device=device)
    if as_json:
        return emit([{k: v for k, v in s.__dict__.items() if k != "base"} | {"file": str(s.file)} for s in srcs])
    for s in srcs:
        say(f"{s.id:28s} {s.device:16s} {s.kind:10s} {s.format:16s} {s.version}")


def guess_format(ref: str) -> str:
    r = ref.lower()
    if "docs.google.com/document" in r:
        return "gdoc"
    if "github.com" in r and ("/releases" in r or r.startswith("github:")):
        return "github_releases"
    if r.split("?")[0].endswith(".pdf") or "drive.google.com" in r:
        return "pdf"
    if r.split("?")[0].endswith((".md", ".markdown")):
        return "markdown"
    return "text"


@source.command("add")
@click.argument("ref")
@click.option("--id", "sid", required=True, help="Source id: lowercase, digits, underscores (e.g. maker_module_manual)")
@click.option("--device", required=True, help="Device id it documents (e.g. maker_module); new devices are fine")
@click.option("--kind", type=click.Choice(KINDS), default="manual", show_default=True, help="What it is")
@click.option("--format", "fmt", type=click.Choice(FORMATS), default=None, help="Default: guessed from REF")
@click.option("--title", default=None, help="Title used in citations (default: the id)")
@click.option("--version", default="", help="Version as printed, e.g. 'v2.1 (2026-03)'")
@click.option("--heading", default="", help="Section heading regex for text sources")
@click.option("--no-pin", is_flag=True, help="Don't pin sha256 (for documents that update in place)")
@click.option("--start-at", default="", help="Regex: drop text before the first matching line (html/text)")
@click.option("--stop-at", default="", help="Regex: cut text at the first matching line")
@click.option("--no-check", is_flag=True, help="A one-time snapshot: `source check` never re-fetches it")
@click.option("--ignore-robots", is_flag=True, help="Fetch even if robots.txt disallows it (don't, normally)")
@click.option("--local", "to_local", is_flag=True, help="Add it to the private overlay (local/sources.yaml)")
def source_add(ref, sid, device, kind, fmt, title, version, heading, no_pin, start_at, stop_at, no_check,
               ignore_robots, to_local):
    """Add a URL or local file to sources.yaml (or the overlay's, with --local): fetch it, pin it, and
    detect the page offset."""
    target = paths.local_sources_file() if to_local else paths.sources_file()
    if target is None:
        raise click.ClickException("--local needs a private overlay: create local/ (or set NAPIER_LOCAL)")
    if any(s.id == sid for s in load_sources()):
        raise click.ClickException(f"source {sid} already exists")
    fmt = fmt or guess_format(ref)
    local = Path(ref).expanduser()
    d = dict(id=sid, device=device, kind=kind, format=fmt, title=title or sid, version=version,
             heading=heading, fetched=dt.date.today().isoformat(),
             start_at={"regex": start_at} if start_at else {}, stop_at={"regex": stop_at} if stop_at else {},
             check=not no_check)
    if local.exists():
        try:
            d["path"] = str(local.resolve().relative_to(target.resolve().parent))
        except ValueError:
            d["path"] = str(local.resolve())
        d.pop("fetched")
    else:
        d["url"] = ref
        ok, why = robots_allows(ref)
        if not ok and not ignore_robots:
            raise click.ClickException(f"{why}; not fetching (napier only reads what sites allow)")
        say(why)
    src = Source(**{k: v for k, v in d.items() if k in Source.__dataclass_fields__})
    f = src.file if src.path else fetch_source(src)
    if fmt == "pdf" and not no_pin:
        d["sha256"] = file_sha256(f)
    if fmt == "pdf":
        off, agree, total = detect_offset(f)
        if offset_trusted(agree, total):
            d["page_offset"] = off
            say(f"page offset {off} ({agree}/{total} numbered pages agree)")
        else:
            d["page_offset"] = 0
            console.print(f"[yellow]page offset: detector unsure ({agree}/{total} numbered pages agree, "
                          f"best guess {off}); wrote 0. Check printed page numbers by hand.[/yellow]")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as fh:
        fh.write(entry_yaml(d))
    say(f"added {sid} -> {target}; next: napier ingest --source {sid}")


@source.command("offset")
@click.argument("ref")
def source_offset(ref):
    """Detect printed page = PDF page - offset from page headers and footers."""
    src = resolve(ref, load_sources())
    if not src.is_pdf or check_source(src):
        raise click.ClickException(f"{src.id}: needs a fetched PDF ({check_source(src) or src.format})")
    off, agree, total = detect_offset(src.file)
    sure = "" if offset_trusted(agree, total) else " [unsure: check by hand]"
    say(f"{src.id}: detected offset {off} ({agree}/{total} numbered pages agree){sure}; "
        f"sources.yaml has {src.page_offset}")



@source.command("check")
@click.option("--source", "ids", multiple=True, help="Only these source ids")
@click.option("--device", default=None, help="Only this device's sources")
@click.option("--kind", type=click.Choice(KINDS), default=None, help="Only this kind of source")
@click.option("--json", "as_json", is_flag=True)
def source_check(ids, device, kind, as_json):
    """Download sources again and compare with the pin or local copy. Changed downloads wait in
    ~/.napier/pending for `napier source apply`."""
    from napier import refresh
    srcs = select(load_sources(), ids, device, kind)
    colors = dict(same="green", changed="yellow", missing="yellow", gone="red", error="red", local="dim",
                  snapshot="dim")
    log = None if as_json else (lambda c: console.print(
        f"[{colors[c.status]}]{c.status:8s}[/{colors[c.status]}] {c.id}  {c.detail}"))
    res = refresh.check(srcs, log=log)
    if as_json:
        return emit([r.__dict__ for r in res])
    n = {k: sum(1 for r in res if r.status == k) for k in colors}
    say(", ".join(f"{v} {k}" for k, v in n.items() if v))
    if n["changed"] or n["missing"]:
        say("next: napier source apply <id> [--version ...], then napier ingest --source <id> and napier facts recheck")


@source.command("apply")
@click.argument("ref")
@click.option("--url", default=None, help="Take the document from this URL instead (a renamed or newer manual)")
@click.option("--version", default=None, help="New version label for sources.yaml, e.g. 'firmware 1.5 (2026.11.02)'")
@click.option("--title", default=None, help="New title for sources.yaml")
def source_apply(ref, url, version, title):
    """Swap in a source's new version: file, pin, fetched date and page offset in sources.yaml."""
    from napier import refresh
    src = resolve(ref, load_sources())
    rep = refresh.apply(src.id, url=url, version=version, title=title)
    say(f"{src.id}: updated ({rep['old_sha'][:8] or 'unpinned'} -> {rep['new_sha'][:8]})")
    if "offset" in rep:
        say(f"page offset {rep['offset']} ({rep['agree']}/{rep['numbered']} numbered pages agree), was {rep['old_offset']}")
    if rep.get("offset_note"):
        console.print(f"[yellow]{rep['offset_note']}[/yellow]")
    say(f"next: napier ingest --source {src.id} && napier facts recheck --source {src.id}")


# ---------------------------------------------------------------- facts

@main.group()
def facts():
    """The facts ledger: claims with where they came from and how far they've been checked."""


def known_device(device: str) -> str:
    """device, if any source list or fact file knows it; else an error with near matches."""
    from napier.sources import suggest
    known = {s.device for s in load_sources()} | {f["device"] for f in factsmod.load()}
    if device not in known:
        raise click.ClickException(f"no device {device!r}{suggest(device, known)} (napier source list shows them all)")
    return device


@facts.command("list")
@click.option("--device", default=None, help="Only this device's facts")
@click.option("--status", type=click.Choice(factsmod.STATUSES), default=None, help="Only facts with this status")
@click.option("--json", "as_json", is_flag=True)
def facts_list(device, status, as_json):
    """Facts with their status and where they came from."""
    if device:
        known_device(device)
    rows = [f for f in factsmod.load(device) if not status or f.get("status") == status]
    if as_json:
        return emit(rows)
    t = Table(box=box.SIMPLE)
    for col in ("id", "status", "claim", "where"):
        t.add_column(col, overflow="fold")
    for f in rows:
        where = f.get("source", "")
        if f.get("pages"):
            where += " p. " + ", ".join(map(str, f["pages"]))
        t.add_row(f["id"], f.get("status", ""), f.get("claim", ""), where or f.get("cite", ""))
    console.print(t)


@facts.command("show")
@click.argument("fid")
def facts_show(fid):
    """One fact in full, as JSON."""
    try:
        emit(factsmod.find(fid))
    except KeyError as e:
        raise click.ClickException(str(e)) from e


@facts.command("add")
@click.argument("device")
@click.argument("claim")
@click.option("--status", type=click.Choice(factsmod.STATUSES), default="unverified", show_default=True,
              help="How far the claim has been checked")
@click.option("--source", default="", help="Source id the claim comes from")
@click.option("--pages", default="", help="Printed pages, comma-separated")
@click.option("--cite", default="", help="URL for community or changelog claims")
@click.option("--notes", default="", help="Needed for hardware and refuted: what you checked")
@click.option("--id", "fid", default="", help="Fact id (default: made from the device and claim)")
def facts_add(device, claim, status, source, pages, cite, notes, fid):
    """Add a claim about DEVICE to its facts file."""
    known_device(device)
    if status in ("hardware", "refuted") and not notes.strip():
        raise click.UsageError(f"a {status} fact needs --notes saying what you checked")
    try:
        pg = [int(p) for p in pages.replace(" ", "").split(",") if p]
        f = factsmod.add(device, claim, status, source, pg, cite, notes, fid)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    say(f"added {f['id']} ({f['status']}) to {factsmod.facts_file(device)}")


@facts.command("verify")
@click.argument("fid")
@click.option("--hardware", "mode", flag_value="hardware", help="Confirmed on the device")
@click.option("--refute", "mode", flag_value="refuted", help="Checked and wrong")
@click.option("--status", "status", type=click.Choice(factsmod.STATUSES), default=None,
              help="Set this status instead (e.g. manual, after checking the page)")
@click.option("--note", default="", help="What you checked, and on which firmware")
@click.option("--cite", default="", help="Where you checked it (a URL), if not the cited source")
def facts_verify(fid, mode, status, note, cite):
    """Record a check: --hardware (confirmed on the device), --refute, or any --status."""
    st = status or mode
    if not st:
        raise click.UsageError("give --hardware, --refute or --status")
    if st in ("hardware", "refuted") and not note.strip():
        raise click.UsageError(f"a {st} check needs --note saying what you checked (and on which firmware)")
    try:
        f = factsmod.set_status(fid, st, note, cite)
    except KeyError as e:
        raise click.ClickException(str(e)) from e
    say(f"{f['id']}: {f['status']} ({f['verified']})")


# ---------------------------------------------------------------- eval / mcp

@facts.command("recheck")
@click.option("--device", default=None, help="Only this device's facts")
@click.option("--source", default=None, help="Only facts citing this source")
@click.option("--fix-pages", is_flag=True, help="Update `pages` for facts whose anchor moved to another page")
@click.option("--all", "show_all", is_flag=True, help="List facts that are fine too")
@click.option("--json", "as_json", is_flag=True)
def facts_recheck(device, source, fix_pages, show_all, as_json):
    """Look for every fact's anchors in its source's current text: what moved, what vanished."""
    from napier import refresh
    res = refresh.recheck(device, source)
    if fix_pages:
        for r in res:
            if r.problem == "page-moved" and r.found_pages:
                refresh.set_fact_pages(r.id, r.found_pages)
                r.detail += " (fixed)"
    if as_json:
        return emit([r.__dict__ for r in res])
    colors = {"ok": "green", "unanchored": "dim", "page-moved": "yellow", "alt-only": "yellow",
              "anchor-missing": "red", "no-text": "red"}
    for r in res:
        if show_all or r.problem not in ("ok", "unanchored"):
            console.print(f"[{colors[r.problem]}]{r.problem:14s}[/{colors[r.problem]}] {r.id}  {r.detail}")
    counts = {k: sum(1 for r in res if r.problem == k) for k in colors}
    say(", ".join(f"{v} {k}" for k, v in counts.items() if v))


@main.command("eval")
@click.option("--device", default=None, help="Only this device's questions")
@click.option("--k", default=10, show_default=True, help="Results looked at per question")
@click.option("--no-rerank", is_flag=True, help="Skip the cross-encoder (faster, a few points lower)")
@click.option("--min-hit3", default=None, type=float, help="Fail below this hit@3 (default 0.90)")
@click.option("--show-misses", is_flag=True, help="List the questions that missed")
@click.option("--json", "as_json", is_flag=True)
def eval_cmd(device, k, no_rerank, min_hit3, show_misses, as_json):
    """Ask each fact's question; exits non-zero when hit@3 is below the gate."""
    ev, sm = _need("evaluate"), _need("search")
    cases = factsmod.eval_cases(device)
    if not cases:
        raise click.ClickException("no facts with q + anchors to test")
    s = sm.Searcher(rerank_model=None if no_rerank else sm.RERANK_MODEL)
    res = ev.evaluate(s, cases, k=k, rerank=not no_rerank)
    if as_json:
        emit(res.as_dict())
    else:
        say(res.summary())
        if show_misses:
            for f in cases:
                r = res.ranks[f["id"]]
                if not r or r > 3 or res.page_ok[f["id"]] is False:
                    say(f"  {f['id']:32s} rank {r or '-':>2}  page {res.page_ok[f['id']]}  {f['q']}")
    gate = ev.MIN_HIT3 if min_hit3 is None else min_hit3
    if res.hit(3) < gate:
        raise click.ClickException(f"hit@3 {res.hit(3):.0%} is below the {gate:.0%} gate")


@main.command("refresh")
@click.option("--merge", is_flag=True, help="Merge the PR when the eval gate and tests pass")
@click.option("--no-push", is_flag=True, help="Apply locally only; no branch, commit or PR")
@click.option("--model", default=None, help="Local Ollama model (default qwen3.5:9b, or NAPIER_LOCAL_MODEL)")
def refresh_cmd(merge, no_push, model):
    """Unattended update pass for maintainers and forks: check sources, apply changes, recheck facts,
    let a local Ollama model reword questions for changed sources, eval, and open a PR on your clone's
    origin. Needs a git clone on main, the index extra, pytest, and (unless --no-push) the GitHub CLI
    signed in. Keeps a Mac awake while it runs (the display may sleep). The report goes to
    ~/.napier/reports/latest.md."""
    import importlib.util
    import shutil
    if not (paths.REPO_ROOT / ".git").exists():
        raise click.ClickException(f"refresh works on a git clone; {paths.REPO_ROOT} isn't one")
    _need("search")
    if importlib.util.find_spec("pytest") is None:
        raise click.ClickException(f"refresh runs the tests before committing and needs pytest: "
                                   f"{paths.install_hint('index,mcp,dev')}")
    if not no_push and shutil.which("gh") is None:
        raise click.ClickException("refresh opens a pull request with the GitHub CLI (https://cli.github.com); "
                                   "install it and run `gh auth login`, or use --no-push")
    from napier import auto
    if model:
        auto.MODEL = model
    rep = auto.run(merge=merge, push=not no_push, log=say)
    say(f"report: {paths.home() / 'reports' / 'latest.md'}")
    if rep["review"]:
        say(f"{len(rep['review'])} item(s) need review: see ~/.napier/reports/latest.md")


@main.group()
def rack():
    """Your rack: what's racked, how you use it, what-if layouts, and which napier device documents each module."""


def select(sources, ids=(), device=None, kind=None):
    try:
        return _select_sources(sources, ids, device, kind)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def _rack_export(include_wishlist: bool = False) -> dict:
    """rack.export, with "no snapshot yet" as a clean error instead of a traceback."""
    from napier import rack as rackmod
    try:
        return rackmod.export(include_wishlist=include_wishlist)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def _note_hint(name: str) -> str:
    """'next: napier ingest --source <id>' for the note source that indexes notes/<name>, if any."""
    ids = [s.id for s in load_sources() if s.path and s.path.replace("\\", "/").endswith(f"notes/{name}")]
    if ids:
        return f"next: napier ingest --source {ids[0]}"
    import os
    f = paths.notes_dir() / name
    try:
        rel = os.path.relpath(f)
    except ValueError:
        rel = str(f)
    sid = "my_" + re.sub(r"[^a-z0-9]+", "_", Path(name).stem.lower()).strip("_")
    return (f"next, so grep and search can read it: napier source add {rel} --local --id {sid} --device my_rig "
            f"--kind note --format markdown --title \"{Path(name).stem} (generated)\" && napier ingest --source {sid}")


@rack.command("sync")
@click.option("--set", "sets", multiple=True, metavar="KEY=VALUE",
              help="Extra setting for the rack source this run "
                   "(e.g. html_file=page.html for a plug-in that can read a saved page)")
@click.option("--dry-run", is_flag=True, help="Report differences without writing files")
@click.option("--json", "as_json", is_flag=True)
def rack_sync(sets, dry_run, as_json):
    """Read the rack from its rack source (racks/devices.yaml `rack_source`, default: the hand-written
    racks/layout.yaml), write racks/<rack>.yaml and notes/rack.md, and report what changed."""
    from napier import rack as rackmod
    from napier.rack_sources import RackSourceError
    extra = {}
    for s in sets:
        if "=" not in s:
            raise click.UsageError(f"--set {s!r}: use KEY=VALUE")
        k, v = s.split("=", 1)
        extra[k.strip()] = v.strip()
    try:
        res = rackmod.sync(write=not dry_run, log=None if as_json else say, settings=extra)
    except (RackSourceError, PermissionError, ValueError) as e:
        raise click.ClickException(str(e)) from e
    if as_json:
        return emit(res)
    say(f"{'changed' if res['changed'] else 'unchanged'} ({res['source']}): {res['snapshot_file']}, {res['notes_file']}")
    if res["changed"] and not dry_run:
        say(_note_hint("rack.md"))


@rack.command("sources")
def rack_sources_cmd():
    """Rack sources napier can read your rack from: the built-in `file` and installed plug-ins."""
    from napier import rack as rackmod
    from napier import rack_sources
    name, rset, pset = rackmod.rack_settings(rackmod.load_config())
    for n in rack_sources.installed():
        mark = "  (enabled in racks/devices.yaml)" if n == name else ""
        say(f"{n}{mark}")
    say(f"racks folder: {rackmod.racks_dir()}" + ("  (the shipped example; set up local/racks for your own)"
                                                  if paths.using_examples() else ""))


@rack.command("export")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None, help="Write JSON here instead of stdout")
@click.option("--wishlist", is_flag=True, help="Also include wishlist modules (owned: false)")
def rack_export(out_file, wishlist):
    """Owned modules with specs, manual power, jacks, docs, role and tags, scenarios and their checks, as JSON."""
    data = json.dumps(_rack_export(include_wishlist=wishlist), indent=1, ensure_ascii=False, default=str)
    if out_file:
        Path(out_file).write_text(data)
        say(f"wrote {out_file}")
    else:
        click.echo(data)


@rack.command("scenarios")
@click.argument("scenario_id", required=False)
@click.option("--far-cm", default=20.0, show_default=True, help="List pairs farther apart than this (cm)")
@click.option("--brief", is_flag=True, help="Only the summary line and problems")
@click.option("--json", "as_json", is_flag=True)
def rack_scenarios(scenario_id, far_cm, brief, as_json):
    """Check what-if layouts in racks/scenarios/*.yaml: overlaps, seams and 1U/3U rows, then power per case
    against the supplies, pairs (pairs_with/keep_near) far apart or across cases, and case rows whose free
    space is split. `napier rack view` draws them."""
    from napier import rack as rackmod
    exp = _rack_export(include_wishlist=True)
    scns = exp["scenarios"]
    if scenario_id:
        if scenario_id not in scns:
            raise click.ClickException(f"no scenario {scenario_id!r}; have: {', '.join(scns) or 'none'}")
        scns = {scenario_id: scns[scenario_id]}
    actual = exp.get("problems") or []
    failing = bool(actual) or any(s["problems"] for s in scns.values())
    if as_json:
        click.echo(json.dumps(scns, indent=1, ensure_ascii=False, default=str))
        sys.exit(1 if failing else 0)
    if actual:
        say(f"actual rack: {len(actual)} problem{'' if len(actual) == 1 else 's'}")
        for p in actual:
            console.print(f"  [yellow]{p}[/yellow]")
    if not scns:
        say("no scenarios yet: add racks/scenarios/<name>.yaml")
    for sid, s in scns.items():
        ch = collections.Counter(m["change"] for m in s["modules"])
        say(f"{sid}: {s['name']} ({len(s['modules'])} modules: {ch['moved']} moved, {ch['new']} new; "
            f"{len(s['removed'])} removed; {len(s['problems'])} problems)")
        for p in s["problems"]:
            console.print(f"  [yellow]{p}[/yellow]")
        ck = s.get("checks") or {}
        if brief or not ck:
            continue
        parts = []
        for c in (ck.get("power") or {}):
            pct = (ck["power"].get(c) or {}).get("pct") or {}
            if pct:
                parts.append(f"{c} " + " ".join(f"{rackmod.RAIL_LABELS[k]} {v}%" for k, v in pct.items()))
        if parts:
            say("  power: " + "; ".join(parts))
        for w in ck.get("warnings") or []:
            console.print(f"  [red]{w}[/red]" if "over the" in w else f"  [yellow]{w}[/yellow]")
        far_all = [p for p in ck.get("pairs") or [] if p["cm"] > far_cm or p["cross_case"]]
        far = [p for p in far_all if not p.get("accepted")]
        accepted = [p for p in far_all if p.get("accepted")]
        if far:
            say(f"  pairs farther than {far_cm:g} cm or across cases:")
            for p in far:
                tags = [t for t, on in (("across cases", p["cross_case"]), ("keep_near", p["keep_near"])) if on]
                say(f"    {p['cm']:5.1f} cm  {p['a_name']} ({p['a_at']}) to {p['b_name']} ({p['b_at']})"
                    + (f"  [{', '.join(tags)}]" if tags else ""))
        else:
            say(f"  pairs: none farther than {far_cm:g} cm or across cases, beyond the accepted ones")
        if accepted:
            say("  accepted distances: " + "; ".join(f"{p['a_name']} to {p['b_name']} {p['cm']:.0f} cm"
                                                    for p in accepted))
        if ck.get("fragmented"):
            say("  free space split within a case row:")
            for f in ck["fragmented"]:
                say(f"    {f}")
        else:
            say("  free space: at most one block per case row")
    if failing:
        sys.exit(1)


@rack.command("view")
@click.option("--out", "out_file", type=click.Path(dir_okay=False), default=None,
              help="Where to write the page (default: ~/.napier/rack-view.html)")
@click.option("--file", "export_file", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Draw from a saved `napier rack export --wishlist` JSON instead of the current files")
@click.option("--fragment", is_flag=True, help="Leave out the <html>/<head>/<body> skeleton (for hosts that add their own)")
@click.option("--open", "open_page", is_flag=True, help="Open the page in your browser")
@click.option("--web-fonts", is_flag=True,
              help="Load the display fonts from Google Fonts (otherwise the page uses system fonts and loads nothing)")
def rack_view(out_file, export_file, fragment, open_page, web_fonts):
    """Draw the actual rack and every scenario as one interactive page: real HP widths, power per case,
    what changed, and each module's job, notes and challenge history on click."""
    from napier.viewer import render
    if export_file:
        exp = json.loads(Path(export_file).read_text(encoding="utf-8"))
    else:
        exp = json.loads(json.dumps(_rack_export(include_wishlist=True), ensure_ascii=False, default=str))
    dest = Path(out_file).expanduser() if out_file else paths.home() / "rack-view.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(exp, standalone=not fragment, web_fonts=web_fonts), encoding="utf-8")
    scns = exp.get("scenarios") or {}
    say(f"wrote {dest} (actual rack + {len(scns)} scenario{'' if len(scns) == 1 else 's'})")
    for sid, sc in scns.items():
        if sc.get("problems"):
            console.print(f"[yellow]{sid}: {len(sc['problems'])} problems (napier rack scenarios {sid})[/yellow]")
    if open_page:
        import webbrowser
        webbrowser.open(dest.as_uri())


@rack.command("usage")
def rack_usage():
    """Check racks/usage.yaml against the rack and write notes/rack-usage.md."""
    from napier import rack as rackmod
    usage = rackmod.load_usage()
    probs = rackmod.check_usage(usage) + rackmod.check_challenges()
    for p in probs:
        console.print(f"[yellow]usage[/yellow] {p}")
    slugs = rackmod.known_slugs()
    snap = rackmod.load_snapshot() or {"modules": []}
    racked = {m["slug"] for m in snap["modules"]}
    missing = sorted(racked - set(usage["modules"]))
    for s in missing:
        console.print(f"[dim]no usage yet[/dim] {slugs.get(s, s)}")
    n_open = sum(len(u["open"]) for u in usage["modules"].values())
    summary = (f"{len(usage['modules'])} modules described, {len(missing)} racked without usage, "
               f"{n_open} open questions, {len(rackmod.load_challenges())} logged challenges, {len(probs)} problems")
    if paths.using_examples():                     # the example rack is read only
        say(f"{summary} (the example rack; notes are written for a rack of your own)")
        return
    out, changed = rackmod.write_usage_md()
    say(f"{summary}; {'wrote' if changed else 'unchanged'} {out}")
    if changed:
        say(_note_hint("rack-usage.md"))


@rack.command("power")
@click.option("--json", "as_json", is_flag=True)
def rack_power(as_json):
    """Each case's current load vs. its supply limits (from racks/usage.yaml)."""
    from napier import rack as rackmod
    cp = _rack_export()["case_power"]
    if as_json:
        return emit(cp)
    for c, e in cp.items():
        lim = e["limits"] if isinstance(e["limits"], dict) else {}
        parts = []
        for k in rackmod.RAILS:
            used = e["load"][k]
            if lim.get(k):
                pct = e["pct"][k]
                flag = " [red]over[/red]" if pct > 100 else " [yellow]low headroom[/yellow]" if pct >= 90 else ""
                parts.append(f"{rackmod.RAIL_LABELS[k]} {used}/{lim[k]}mA ({pct}%){flag}")
            else:
                parts.append(f"{rackmod.RAIL_LABELS[k]} {used}mA (no limit recorded)")
        console.print(f"{c} ({e['modules']} modules): " + ", ".join(parts))


@rack.command("check")
@click.option("--tolerance", default=5, show_default=True, help="mA difference allowed per rail")
def rack_check(tolerance):
    """Manual power vs the rack source's power for every racked module that has a spec."""
    from napier import rack as rackmod
    from napier import specs as specmod
    snap = rackmod.load_snapshot() or {"modules": []}
    have = specmod.by_slug()
    mism = specmod.compare(snap["modules"], tolerance)
    for m in mism:
        d = ", ".join(f"{r} rack source {v['rack_source']} vs manual {v['manual']}" for r, v in m["diffs"].items())
        console.print(f"[yellow]power[/yellow] {m['name']}: {d} ({m['source']} p. {m['page']})")
    with_spec = sum(1 for m in snap["modules"] if m["slug"] in have)
    say(f"{len(mism)} power mismatches; {with_spec} of {len(snap['modules'])} racked modules have specs")


@main.group()
def specs():
    """Manual-cited module specs (power, jacks) in specs/."""


@specs.command("check")
@click.argument("names", nargs=-1)
def specs_check(names):
    """Verify every power anchor and jack name against the cited page of its source."""
    from napier import specs as specmod
    res = specmod.check(list(names) or None)
    for p in res.problems:
        console.print(f"[red]{p.what:6s}[/red] {p.spec}: {p.detail}")
    say(f"{res.specs} specs, {res.powered} with power, {res.jacks} jacks; {len(res.problems)} problems")
    if res.problems:
        sys.exit(1)



@main.command()
def mcp():
    """Serve search, grep, read, facts and status over MCP (stdio), for Claude and other agents."""
    try:
        from napier.mcp_server import serve
    except ImportError as e:
        raise click.ClickException(f"{e}. The MCP server needs the mcp extra: {paths.install_hint('mcp')} "
                                   "(or 'index,mcp' for search too)") from e
    serve()


# One-line summaries for the command lists in --help (the docstrings say more).
for _cmd, _short in {
    (main, "eval"): "Test search against the facts ledger (needs the index).",
    (main, "facts"): "The facts ledger: checked claims and where they came from.",
    (main, "mcp"): "Serve the lookups to assistants over MCP (stdio).",
    (main, "rack"): "Your rack: sync, power, what-if layouts, a drawing.",
    (main, "refresh"): "Maintainers: check sources and facts, open a PR.",
    (main, "search"): "Meaning-based search, with cited pages (needs the index).",
    (main, "status"): "What's downloaded, extracted and indexed, per device.",
    (main, "fetch"): "Download sources (--device ID, --source ID or --all).",
    (rack, "check"): "Where the rack source's power figures disagree with the manuals.",
    (rack, "export"): "Everything about the rack as JSON, for scripts and agents.",
    (rack, "power"): "Each case's load against its supply limits.",
    (rack, "scenarios"): "Check the rack and every what-if layout.",
    (rack, "sources"): "Rack sources installed, and which one devices.yaml enables.",
    (rack, "sync"): "Read the rack from its rack source and write the snapshot.",
    (rack, "usage"): "Check usage.yaml and challenges.yaml against the rack.",
    (rack, "view"): "Draw the rack and every scenario as one HTML page.",
    (source, "add"): "Add a URL or local file as a source (and fetch it).",
    (source, "apply"): "Switch a source to its new version: file, pin and date.",
    (source, "offset"): "Work out printed page = PDF page - offset from the page headers.",
    (source, "check"): "Download sources again and compare with their pins.",
    (facts, "recheck"): "Find every fact's anchors in its source's current text.",
    (facts, "verify"): "Record a check: on the hardware, in the manual, or refuted.",
    (specs, "check"): "Check each spec's power figures and jack names against its page.",
}.items():
    _cmd[0].commands[_cmd[1]].short_help = _short


if __name__ == "__main__":
    sys.exit(main())
