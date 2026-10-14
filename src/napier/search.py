"""Hybrid search: vector + BM25 candidates, reciprocal rank fusion, cross-encoder rerank.

Adapted from the device knowledge store in Fourier, a sibling project for sample libraries, whose
eval (46 facts, on a laptop) chose these defaults: arctic-embed-l-v2.0 + BM25 fused gets hit@3 93%
at ~60 ms/query; reranking with bge-reranker-v2-m3 gets hit@3 96% at ~1.7 s/query. `--no-rerank`
trades the last few points for speed. Results cite printed page numbers, using each source's
page_offset.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from napier.sources import Source, source_map
from napier.store import EMBED_MODEL, REVISIONS, Embedder, Store, pick_device

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
POOL = 30
RRF_K = 60


@dataclass
class Hit:
    id: str
    device: str
    kind: str
    source_id: str
    title: str
    version: str
    pages: list[int]            # PDF page indexes
    printed: list[int | None]   # printed page numbers (None = unnumbered front matter)
    headings: str
    text: str
    figure: bool
    score: float
    cite: str = ""
    ranks: dict[str, int] = field(default_factory=dict)

    def as_dict(self):
        return self.__dict__.copy()


def rrf(rankings: dict[str, list[str]], k: int = RRF_K) -> dict[str, float]:
    score: dict[str, float] = {}
    for ids in rankings.values():
        for r, i in enumerate(ids):
            score[i] = score.get(i, 0.0) + 1.0 / (k + r + 1)
    return score


def _quote(s: str) -> str:
    return s.replace("'", "''")


def cite_for(src: Source | None, title: str, version: str, pages: list[int], headings: str) -> str:
    label = src.label() if src else (f"{title}, {version}" if version else title)
    if pages:
        where = src.cite_pages(pages) if src else "PDF p. " + ", ".join(map(str, pages))
    else:
        where = f"§ {headings.split(' > ')[-1]}" if headings else ""
    return f"{label}, {where}" if where else label


class Searcher:
    def __init__(self, store: Store | None = None, rerank_model: str | None = RERANK_MODEL,
                 embed_model: str | None = None, sources: dict[str, Source] | None = None):
        self.store = store or Store()
        self.tbl = self.store.table()
        if self.tbl is None:
            raise RuntimeError("the index is empty; run `napier ingest` first")
        self.sources = sources if sources is not None else source_map()
        models = {v.get("embed_model") for v in self.store.state.values() if v.get("embed_model")}
        self.embedder = Embedder(embed_model or (next(iter(models)) if models else EMBED_MODEL))
        self.reranker = None
        if rerank_model:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(rerank_model, revision=REVISIONS.get(rerank_model), device=pick_device())

    def search(self, query: str, device: str | None = None, kind: str | None = None, top: int = 5,
               pool: int = POOL, rerank: bool = True) -> list[Hit]:
        conds = []
        if device:
            conds.append(f"device = '{_quote(device)}'")
        if kind:
            conds.append(f"kind = '{_quote(kind)}'")
        where = " AND ".join(conds) or None
        vq = self.tbl.search(self.embedder.query(query), vector_column_name="vector").limit(pool)
        fq = self.tbl.search(query, query_type="fts", fts_columns="embed_text").limit(pool)
        if where:
            vq, fq = vq.where(where, prefilter=True), fq.where(where, prefilter=True)
        vec_rows, fts_rows = vq.to_list(), fq.to_list()
        rows = {r["id"]: r for r in vec_rows + fts_rows}
        ranks = {"vector": [r["id"] for r in vec_rows], "bm25": [r["id"] for r in fts_rows]}
        fused = rrf(ranks)
        order = sorted(fused, key=lambda i: -fused[i])
        scores = fused
        if rerank and self.reranker is not None and order:
            # rerank on title + headings + text: on bare chunk text the cross-encoder buried
            # spec-table rows and figure text (Fourier eval: hit@3 73% vs 96%)
            ce = self.reranker.predict([(query, rows[i]["embed_text"]) for i in order], show_progress_bar=False)
            scores = {i: float(s) for i, s in zip(order, ce, strict=True)}
            order = sorted(order, key=lambda i: -scores[i])
        hits = []
        for i in order[:top]:
            r = rows[i]
            src = self.sources.get(r["source_id"])
            pages = [int(p) for p in r["pages"]]
            hits.append(Hit(id=i, device=r["device"], kind=r.get("kind", ""), source_id=r["source_id"],
                            title=r["title"], version=r["version"], pages=pages,
                            printed=[src.printed(p) if src else None for p in pages], headings=r["headings"],
                            text=r["text"], figure=bool(r["figure"]), score=scores[i],
                            cite=cite_for(src, r["title"], r["version"], pages, r["headings"]),
                            ranks={k: v.index(i) + 1 for k, v in ranks.items() if i in v}))
        return hits
