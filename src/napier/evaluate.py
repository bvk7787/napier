"""Search eval over the facts ledger (facts with `q` and `anchors`).

A result "holds" a fact when one chunk contains every anchor of the primary set or of any `alt`
set, compared as lowercase alphanumerics after NFKC. hit@k = a holding chunk is in the top k.
When a fact names its source and printed pages, we also check the holding chunk cites one of them.
"""
from __future__ import annotations

from dataclasses import dataclass

from napier.parse import norm

MIN_HIT3 = 0.90


def holds(text: str, fact: dict, primary_only: bool = False) -> bool:
    n = norm(text)
    sets = [fact["anchors"]] if primary_only else [fact["anchors"], *fact.get("alt", [])]
    return any(all(norm(a) in n for a in s) for s in sets)


@dataclass
class EvalResult:
    ranks: dict[str, int | None]
    page_ok: dict[str, bool | None]
    k: int

    def hit(self, k: int) -> float:
        return sum(1 for r in self.ranks.values() if r and r <= k) / max(1, len(self.ranks))

    def summary(self) -> str:
        checkable = [v for v in self.page_ok.values() if v is not None]
        return (f"hit@1 {self.hit(1):.0%}  hit@3 {self.hit(3):.0%}  hit@{self.k} {self.hit(self.k):.0%}"
                f"  ({len(self.ranks)} facts; cited page correct {sum(checkable)}/{len(checkable)})")

    def as_dict(self):
        return dict(hit1=self.hit(1), hit3=self.hit(3), hitk=self.hit(self.k), k=self.k,
                    ranks=self.ranks, page_ok=self.page_ok)


def evaluate(searcher, facts: list[dict], k: int = 10, sources: dict | None = None, **kw) -> EvalResult:
    """Each fact is searched within its device and, when its source is known, that source's kind,
    so a manual fact tests manual retrieval and isn't crowded out by the community doc."""
    sources = sources or getattr(searcher, "sources", {}) or {}
    ranks: dict[str, int | None] = {}
    page_ok: dict[str, bool | None] = {}
    for f in facts:
        src = sources.get(f.get("source", ""))
        hits = searcher.search(f["q"], device=f["device"], kind=src.kind if src else None, top=k, **kw)
        rank = next((i + 1 for i, h in enumerate(hits) if holds(h.text, f)), None)
        ranks[f["id"]] = rank
        if not f.get("pages"):
            page_ok[f["id"]] = None          # nothing to check against
            continue
        if not rank:
            page_ok[f["id"]] = False
            continue
        h = hits[rank - 1]
        if not holds(h.text, f, primary_only=True):
            page_ok[f["id"]] = None          # matched alt wording, which lives on other pages
            continue
        same_source = not f.get("source") or f["source"] == h.source_id
        page_ok[f["id"]] = same_source and bool(set(p for p in h.printed if p) & set(f["pages"]))
    return EvalResult(ranks, page_ok, k)
