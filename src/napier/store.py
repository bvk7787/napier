"""Ingest: text layer for every source, plus a LanceDB chunk index (vectors + full text) for search.

Adapted from the device knowledge store in Fourier, a sibling project for sample libraries. Ingest
is incremental: a source is redone only when its file, the pipeline version or the embedding model changes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from napier import paths
from napier.sources import Source, check_source, file_sha256

EMBED_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
# Hugging Face models load at a pinned commit, so an upstream change can't silently alter results
# (or the code a model ships). A model not listed here (--embed-model) loads at its latest commit.
REVISIONS = {
    "Snowflake/snowflake-arctic-embed-l-v2.0": "ac6544c8a46e00af67e330e85a9028c66b8cfd9a",
    "BAAI/bge-reranker-v2-m3": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
}
TABLE = "chunks"


def _q(s: str) -> str:
    return s.replace("'", "''")


def pick_device() -> str:
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False


class Embedder:
    """sentence-transformers wrapper; uses the model's own query prompt when it defines one."""

    def __init__(self, model: str = EMBED_MODEL, device: str | None = None):
        from sentence_transformers import SentenceTransformer
        self.name = model
        self.model = SentenceTransformer(model, revision=REVISIONS.get(model), device=device or pick_device())
        dim = getattr(self.model, "get_embedding_dimension", None) or \
            self.model.get_sentence_embedding_dimension
        self.dim = dim()
        self._query_prompt = "query" if "query" in (self.model.prompts or {}) else None

    def docs(self, texts: list[str]):
        return self.model.encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)

    def query(self, text: str):
        return self.model.encode([text], prompt_name=self._query_prompt, normalize_embeddings=True,
                                 show_progress_bar=False)[0]


@dataclass
class IngestReport:
    text: dict[str, int] = field(default_factory=dict)      # source_id -> units written
    added: dict[str, int] = field(default_factory=dict)     # source_id -> chunks indexed
    skipped: list[str] = field(default_factory=list)        # unchanged
    removed: list[str] = field(default_factory=list)        # no longer in sources
    problems: dict[str, str] = field(default_factory=dict)  # source_id -> reason


def load_state(home: Path | None = None) -> dict:
    f = (home or paths.home()) / "state.json"
    return json.loads(f.read_text()) if f.exists() else {}


class Store:
    def __init__(self, home: Path | None = None):
        self.home = home or paths.home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.state_file = self.home / "state.json"
        self.state = load_state(self.home)
        self._db = None

    @property
    def db(self):
        if self._db is None:
            import lancedb
            self._db = lancedb.connect(str(self.home / "lancedb"))
        return self._db

    def table(self):
        try:
            return self.db.open_table(TABLE)
        except (ValueError, FileNotFoundError):
            return None

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def ingest(self, sources: list[Source], embed_model: str = EMBED_MODEL, force: bool = False,
               text_only: bool = False, all_sources: list[Source] | None = None, log=print) -> IngestReport:
        from napier.parse import PIPELINE_VERSION
        from napier.text import build_units, has_text, save_units
        rep = IngestReport()
        ok, shas = [], {}
        for s in sources:
            problem = check_source(s)
            if problem:
                rep.problems[s.id] = problem
            else:
                ok.append(s)
                shas[s.id] = file_sha256(s.file)

        # sources removed from sources.yaml: drop their rows and text
        live = {s.id for s in (all_sources if all_sources is not None else sources)}
        for sid in sorted(set(self.state) - live):
            if not text_only and self.table() is not None:
                self.table().delete(f"source_id = '{_q(sid)}'")
            self.state.pop(sid, None)
            rep.removed.append(sid)

        if not text_only:  # a model change alters the vector width: rebuild the index
            models = {v.get("embed_model") for v in self.state.values() if v.get("embed_model")}
            if self.table() is not None and models and models != {embed_model}:
                self.db.drop_table(TABLE)
                for v in self.state.values():
                    v.pop("embed_model", None)
                    v.pop("chunks", None)

        emb = None
        for i, s in enumerate(ok, 1):
            st = self.state.get(s.id, {})
            same_file = st.get("sha256") == shas[s.id] and st.get("pipeline") == PIPELINE_VERSION
            need_text = force or not same_file or not has_text(s.id) or \
                (s.is_pdf and not st.get("docling") and docling_available())
            need_index = not text_only and (force or not same_file or st.get("embed_model") != embed_model)
            if not need_text and not need_index:
                rep.skipped.append(s.id)
                continue
            t = time.time()
            doc = None
            log(f"[{i}/{len(ok)}] {s.id}")
            if s.is_pdf and docling_available():
                log("  parsing the PDF ...")
                from napier.parse import convert
                doc = convert(s, shas[s.id])
            elif s.is_pdf and need_index:
                raise RuntimeError(f"indexing a PDF needs the index extra: {paths.install_hint('index,mcp')}")
            if need_text:
                units = build_units(s, doc)
                save_units(s.id, units)
                rep.text[s.id] = len(units)
            st = dict(st, sha256=shas[s.id], pipeline=PIPELINE_VERSION, device=s.device, kind=s.kind,
                      docling=bool(doc is not None) if s.is_pdf else None,
                      text_units=rep.text.get(s.id, st.get("text_units")),
                      ingested=time.strftime("%Y-%m-%d %H:%M"))
            if need_index:
                from napier.parse import chunk_pdf, chunk_text_units
                from napier.text import load_units
                chunks = chunk_pdf(doc, s, tokenizer_model=embed_model) if s.is_pdf \
                    else chunk_text_units(load_units(s.id), s)
                log(f"  {len(chunks)} chunks; embedding ...")
                emb = emb or Embedder(embed_model)
                vecs = emb.docs([c["embed_text"] for c in chunks])
                rows = [dict(id=f"{s.id}:{i}", source_id=s.id, device=s.device, kind=s.kind, title=s.title,
                             version=s.version, pages=[int(p) for p in c["pages"]],
                             page=c["pages"][0] if c["pages"] else 0, headings=" > ".join(c["headings"]),
                             text=c["text"], embed_text=c["embed_text"], figure=c["figure"],
                             vector=[float(x) for x in v])
                        for i, (c, v) in enumerate(zip(chunks, vecs, strict=True))]
                tbl = self.table()
                if tbl is None:
                    self.db.create_table(TABLE, rows)
                else:
                    tbl.delete(f"source_id = '{_q(s.id)}'")
                    tbl.add(rows)
                st.update(embed_model=embed_model, chunks=len(rows))
                rep.added[s.id] = len(rows)
            elif not same_file:  # text redone but index not rebuilt: mark the index stale
                st.pop("embed_model", None)
                st.pop("chunks", None)
            self.state[s.id] = st
            self._save()
            log(f"  {s.id} done in {time.time() - t:.0f}s")
        if rep.added:
            self.reindex_fts()
        self._save()
        return rep

    def reindex_fts(self):
        from lancedb.index import FTS
        tbl = self.table()
        if tbl is not None:
            tbl.create_index("embed_text", config=FTS(), replace=True)
