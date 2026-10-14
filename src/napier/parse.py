"""Docling parsing and chunking (adapted from the device knowledge store in
Fourier, a sibling project for sample libraries).

- Parsed PDFs are cached as Docling JSON keyed by file sha256 (parsing is the slow step), in the
  same scheme Fourier uses, so a Fourier cache file can be copied into ~/.napier/parsed as-is.
- PDF chunks come from HybridChunker with tables serialized as markdown, so a spec row keeps its
  key and value together.
- Docling drops text drawn inside figures. For each picture we read the PDF text layer inside its
  bounding box and keep the lines Docling didn't already emit for that page, as one extra
  "figure text" chunk per page.
- Text sources (changelogs, community docs) are chunked by section, then by paragraph.
"""
from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

from napier import paths
from napier.sources import Source

PIPELINE_VERSION = "2"  # bump when parsing/chunking output changes, to force re-ingest (2: unescape &amp;)
MAX_TOKENS = 384
TEXT_CHUNK_CHARS = 1400
MIN_FIGURE_CHARS = 12
_norm_re = re.compile(r"[^0-9a-z]")


def norm(text: str) -> str:
    """Lowercase alphanumerics only, after NFKC (so ligatures like U+FB01 compare as 'fi')."""
    return _norm_re.sub("", unicodedata.normalize("NFKC", html.unescape(text)).lower())


def clean(text: str) -> str:
    """NFKC, and undo the HTML escaping Docling's markdown applies (&amp; and friends)."""
    return unicodedata.normalize("NFKC", html.unescape(text)).strip()


def novel_lines(lines: list[str], known_norm: str, min_len: int = 3) -> list[str]:
    out, seen = [], set()
    for line in lines:
        line = clean(line)
        n = norm(line)
        if len(n) < min_len or n in seen or n in known_norm:
            continue
        seen.add(n)
        out.append(line)
    return out


def convert(src: Source, sha: str, cache_dir: Path | None = None):
    """Docling-parse a PDF, reusing the cached JSON when the file hasn't changed."""
    from docling_core.types.doc import DoclingDocument
    cache_dir = cache_dir or paths.home() / "parsed"
    cache = cache_dir / f"{sha[:16]}.json"
    if cache.exists():
        return DoclingDocument.load_from_json(cache)
    from docling.document_converter import DocumentConverter
    doc = DocumentConverter().convert(str(src.file)).document
    cache_dir.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(cache)
    return doc


def _chunker(tokenizer_model: str, max_tokens: int):
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
    from transformers import AutoTokenizer

    from napier.store import REVISIONS

    class _MarkdownTables(ChunkingSerializerProvider):
        def get_serializer(self, doc):
            return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())

    hf = AutoTokenizer.from_pretrained(tokenizer_model, revision=REVISIONS.get(tokenizer_model))
    tok = HuggingFaceTokenizer(tokenizer=hf, max_tokens=max_tokens)
    return HybridChunker(tokenizer=tok, merge_peers=True, serializer_provider=_MarkdownTables())


def figure_text(doc, pdf_path: Path) -> dict[int, list[str]]:
    """PDF text-layer lines inside each picture's bounding box, by page."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    out: dict[int, list[str]] = {}
    try:
        for pic in doc.pictures:
            for prov in pic.prov:
                page = doc.pages.get(prov.page_no)
                if page is None:
                    continue
                bb = prov.bbox.to_bottom_left_origin(page_height=page.size.height)
                tp = pdf[prov.page_no - 1].get_textpage()
                text = tp.get_text_bounded(left=bb.l, bottom=bb.b, right=bb.r, top=bb.t)
                lines = [ln for ln in re.split(r"[\r\n]+", text) if ln.strip()]
                if lines:
                    out.setdefault(prov.page_no, []).extend(lines)
    finally:
        pdf.close()
    return out


def chunk_pdf(doc, src: Source, tokenizer_model: str, max_tokens: int = MAX_TOKENS) -> list[dict]:
    """Chunks as dicts: text, embed_text, pages (PDF page indexes), headings, figure."""
    chunker = _chunker(tokenizer_model, max_tokens)
    chunks = []
    for ch in chunker.chunk(doc):
        pages = sorted({p.page_no for it in ch.meta.doc_items for p in it.prov})
        headings = [clean(h) for h in (ch.meta.headings or [])]
        chunks.append(dict(text=clean(ch.text), embed_text=f"{src.title}\n{clean(chunker.contextualize(ch))}",
                           pages=pages, headings=headings, figure=False))
    known: dict[int, str] = {}
    for c in chunks:
        for p in c["pages"]:  # type: ignore[attr-defined]
            known[p] = known.get(p, "") + norm(c["text"])  # type: ignore[arg-type]
    for page, lines in sorted(figure_text(doc, src.file).items()):
        body = " / ".join(novel_lines(lines, known.get(page, "")))
        if len(norm(body)) < MIN_FIGURE_CHARS:
            continue
        headings = next((c["headings"] for c in chunks if page in c["pages"] and c["headings"]), [])  # type: ignore[misc, operator]
        label = " > ".join(headings + [f"figure text, page {page}"])
        chunks.append(dict(text=body, embed_text=f"{src.title}\n{label}\n{body}", pages=[page],
                           headings=headings, figure=True))
    return chunks


def chunk_text_units(units: list[dict], src: Source, max_chars: int = TEXT_CHUNK_CHARS) -> list[dict]:
    """Section-aware chunks for text sources: each section split on blank lines into pieces of
    at most max_chars (a single long paragraph is split hard)."""
    chunks = []
    for u in units:
        head = u.get("heading", "")
        paras = [p.strip() for p in re.split(r"\n\s*\n", u["md"]) if p.strip()]
        buf = ""
        pieces = []
        for p in paras:
            while len(p) > max_chars:
                pieces.append(p[:max_chars])
                p = p[max_chars:]
            if buf and len(buf) + len(p) + 2 > max_chars:
                pieces.append(buf)
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf:
            pieces.append(buf)
        for piece in pieces:
            text = clean(piece)
            if len(norm(text)) < MIN_FIGURE_CHARS:
                continue
            chunks.append(dict(text=text, embed_text=f"{src.title}\n{head}\n{text}", pages=[],
                               headings=[head] if head else [], figure=False))
    return chunks
