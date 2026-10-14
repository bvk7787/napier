"""The text layer: one unit per PDF page (or per section of a text source), saved as JSONL.

`grep` and `read` work on this layer only, so they need no index, no models and no network.
For PDFs each unit keeps two texts: `raw` from the PDF text layer (exact, includes text drawn
inside figures) and `md` from Docling (tables and headings kept, better for reading).
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from napier import paths
from napier.sources import Source

MD_HEADING = r"^#{1,6}\s"


def nfkc(s: str) -> str:
    """NFKC, with soft hyphens (which PDF text layers leave at line breaks) removed."""
    s = re.sub("[\ufffe\u00ad]\r?\n", "", s)
    return unicodedata.normalize("NFKC", s.replace("\ufffe", "").replace("\u00ad", ""))


def text_dir() -> Path:
    return paths.home() / "text"


def units_file(source_id: str) -> Path:
    paths.check_name("source id", source_id)
    return paths.inside(text_dir(), text_dir() / f"{source_id}.jsonl")


# ---------------------------------------------------------------- building units

def pdf_raw_pages(pdf_path: Path) -> list[str]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return [nfkc(pdf[i].get_textpage().get_text_range()).replace("\r\n", "\n").replace("\r", "\n")
                for i in range(len(pdf))]
    finally:
        pdf.close()


def _page_md(doc, page_no: int) -> str:
    try:
        return doc.export_to_markdown(page_no=page_no, escape_underscores=False)
    except TypeError:
        return doc.export_to_markdown(page_no=page_no)


def clean_heading(line: str) -> str:
    h = re.sub(r"^#{1,6}\s*", "", line.strip())
    h = re.sub(r"\s*\{#[^}]*\}\s*$", "", h.replace("**", "").replace("\\.", ".")).strip()
    return h


def pdf_units(src: Source, doc=None) -> list[dict]:
    raws = pdf_raw_pages(src.file)
    units = []
    for i, raw in enumerate(raws, 1):
        md = nfkc(html.unescape(_page_md(doc, i))) if doc is not None else raw
        heads = [clean_heading(ln) for ln in md.splitlines() if re.match(MD_HEADING, ln)]
        units.append(dict(n=i, page=i, printed=src.printed(i), heading=heads[0] if heads else "",
                          md=md, raw=raw))
    return units


def text_units(src: Source) -> list[dict]:
    text = nfkc(src.file.read_text(encoding="utf-8", errors="replace")).replace("\r\n", "\n")
    rx = re.compile(src.heading or MD_HEADING)
    units, cur, head = [], [], ""

    def flush():
        body = "\n".join(cur).strip()
        if body:
            units.append(dict(n=len(units) + 1, page=None, printed=None, heading=head, md=body, raw=body))

    for ln in text.split("\n"):
        if rx.search(ln):
            flush()
            cur, head = [ln], clean_heading(ln)
        else:
            cur.append(ln)
    flush()
    return units


def build_units(src: Source, doc=None) -> list[dict]:
    return pdf_units(src, doc) if src.is_pdf else text_units(src)


def save_units(source_id: str, units: list[dict]) -> Path:
    f = units_file(source_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units))
    return f


def load_units(source_id: str) -> list[dict]:
    f = units_file(source_id)
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]


def has_text(source_id: str) -> bool:
    return units_file(source_id).exists()


# ---------------------------------------------------------------- grep

@dataclass
class GrepHit:
    source_id: str
    title: str
    version: str
    device: str
    kind: str
    cite: str
    heading: str
    line: str
    before: list[str]
    after: list[str]

    def as_dict(self):
        return self.__dict__.copy()


MAX_REGEX = 200
# a quantified group that itself ends in a quantifier, e.g. (a+)+ or (\w*)*: the classic shape of
# catastrophic backtracking, which would freeze grep (and the MCP server serving it) on one manual
_NESTED = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]")


def check_regex(query: str) -> str:
    """A --regex query, if it's short and has no nested quantifiers; else ValueError."""
    if len(query) > MAX_REGEX:
        raise ValueError(f"regex longer than {MAX_REGEX} characters")
    if _NESTED.search(query):
        raise ValueError("regex has a repeated group inside a repeat (like (a+)+), which can take forever; "
                         "simplify it")
    try:
        re.compile(query)
    except re.error as e:
        raise ValueError(f"not a valid regex: {e}") from e
    return query


def pattern(query: str, regex: bool = False, ignore_case: bool = True) -> re.Pattern:
    """Literal queries match text exactly, with two allowances:
    - a space matches any run of whitespace, so 'Live mode' also finds 'Live' at the end of one
      line and 'mode' at the start of the next
    - a '+' matches with or without spaces around it, so '[FUNC]+[PLAY]' and '[FUNC] + [PLAY]'
      find the same combos (Elektron manuals space them, Dirtywave's don't)"""
    if regex:
        rx = check_regex(query)
    else:
        query = re.sub(r"\s*\+\s*", "+", query)
        rx = r"\s+".join(re.escape(p).replace(r"\+", r"\s*\+\s*") for p in query.split())
    return re.compile(rx, re.I if ignore_case else 0)


def unit_cite(src: Source, u: dict) -> str:
    if u.get("page"):
        return src.cite_pages([u["page"]])
    return f"§ {u['heading']}" if u.get("heading") else ""


def grep(query: str, sources: list[Source], regex: bool = False, ignore_case: bool = True,
         context: int = 1, max_hits: int = 50) -> list[GrepHit]:
    rx = pattern(query, regex, ignore_case)
    hits: list[GrepHit] = []
    for src in sources:
        for u in load_units(src.id):
            text = u["raw"] if src.is_pdf else u["md"]
            lines = text.split("\n")
            # match line by line, then across line breaks for multi-word queries
            joined = "\n".join(lines)
            spans = [m.start() for m in rx.finditer(joined)]
            if not spans:
                continue
            starts, pos = [], 0
            for ln in lines:
                starts.append(pos)
                pos += len(ln) + 1
            done = set()
            for sp in spans:
                i = max(k for k, s in enumerate(starts) if s <= sp)
                if i in done:
                    continue
                done.add(i)
                hits.append(GrepHit(src.id, src.title, src.version, src.device, src.kind, unit_cite(src, u),
                                    u.get("heading", ""), lines[i].strip(),
                                    [x.strip() for x in lines[max(0, i - context):i]],
                                    [x.strip() for x in lines[i + 1:i + 1 + context]]))
                if len(hits) >= max_hits:
                    return hits
    return hits


# ---------------------------------------------------------------- read

def read_page(src: Source, page: int | None = None, pdf_page: int | None = None,
              raw: bool = False) -> dict:
    if not src.is_pdf:
        raise ValueError(f"{src.id} has no pages; read it by --section")
    n = pdf_page if pdf_page else src.pdf_page(page)  # type: ignore[arg-type]
    units = {u["page"]: u for u in load_units(src.id)}
    if n not in units:
        raise ValueError(f"{src.id}: no page {page if page else n} (PDF page {n}); "
                         f"{len(units)} pages indexed")
    u = units[n]
    return dict(source_id=src.id, title=src.label(), cite=src.cite_pages([n]), heading=u["heading"],
                text=u["raw"] if raw else u["md"])


def _norm_title(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", nfkc(s).lower()).strip()


def heading_rx(src: Source) -> re.Pattern:
    return re.compile(MD_HEADING if src.is_pdf or not src.heading else src.heading)


def level(line: str) -> int:
    return (len(line) - len(line.lstrip("#"))) or 1


def sections(src: Source) -> list[dict]:
    """Every heading in the source: title, level, and the page (or section number) it starts on."""
    out = []
    for u in load_units(src.id):
        if src.is_pdf:
            for ln in u["md"].split("\n"):
                if re.match(MD_HEADING, ln):
                    out.append(dict(title=clean_heading(ln), level=len(ln) - len(ln.lstrip("#")),
                                    page=u["page"], cite=src.cite_pages([u["page"]])))
        elif u.get("heading"):
            out.append(dict(title=u["heading"], level=level(u["md"].split("\n", 1)[0]), page=None,
                            cite=f"§ {u['heading']}"))
    return out


def read_section(src: Source, title: str, max_chars: int = 8000, nth: int = 1) -> dict:
    """The section whose heading contains `title`, up to the next heading of the same or a
    higher level, across page breaks."""
    want, hrx = _norm_title(title), heading_rx(src)
    flat = []  # (page, line)
    for u in load_units(src.id):
        for ln in u["md"].split("\n"):
            flat.append((u.get("page"), ln))
    starts = [i for i, (_, ln) in enumerate(flat) if hrx.search(ln) and want in _norm_title(ln)]
    if not starts:
        raise ValueError(f"{src.id}: no heading contains {title!r} (try `napier read {src.id} --toc`)")
    i0 = starts[min(nth, len(starts)) - 1]
    lvl = level(flat[i0][1])
    body, pages = [flat[i0][1]], [flat[i0][0]]
    for pg, ln in flat[i0 + 1:]:
        if hrx.search(ln) and level(ln) <= lvl:
            break
        body.append(ln)
        pages.append(pg)
    text = "\n".join(body).strip()
    cut = len(text) > max_chars
    pgs = sorted({p for p in pages if p})
    cite = src.cite_pages(pgs) if pgs else f"§ {clean_heading(flat[i0][1])}"
    return dict(source_id=src.id, title=src.label(), cite=cite, heading=clean_heading(flat[i0][1]),
                text=text[:max_chars] + ("\n[... cut; raise --max-chars]" if cut else ""),
                matches=len(starts))
