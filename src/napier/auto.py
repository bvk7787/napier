"""`napier refresh`: the unattended update pass, with a local model for the two checked steps.

1. Check every source upstream. Nothing changed: write a one-line report and stop.
2. Apply changed sources (new file, pin, offset; the local model reads the new version label off
   the first page), re-ingest them, recheck their facts and fix moved pages.
3. Eval the affected devices. A fact that now misses AND whose source changed gets its question
   reworded by the local model, judged by search (top 3), up to 3 tries.
4. Anything it can't settle goes on the "needs review" list: sources gone or erroring, anchors
   that vanished (the claim may have changed), misses it couldn't fix.
5. Full eval and tests, then a branch, commit and PR. With --merge it merges when the eval gate and
   tests pass; the review list rides along in the PR and the report.

Keeps the Mac awake (not the display) while it runs. Reports land in ~/.napier/reports/.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from napier import facts as factsmod
from napier import paths, refresh
from napier.parse import norm
from napier.sources import load_sources
from napier.text import load_units

OLLAMA = os.environ.get("NAPIER_OLLAMA", "http://localhost:11434")
MODEL = os.environ.get("NAPIER_LOCAL_MODEL", "qwen3.5:9b")
TRIES = 3
RACK_NOTE = "notes/rack.md"        # the generated rack note source (see napier.rack)

REWORD_SYSTEM = (
    "You write the question a musician would type into a search box over hardware manuals. "
    "You get a fact, the manual passage that states it, and passages a previous question wrongly "
    "retrieved. Write ONE natural question (max 20 words) whose answer is the target passage. Name the "
    "device by its real name, and use the passage's own terms for the control, jack, mode or setting. "
    "Don't copy the passage's sentences. Reply with JSON only: {\"q\": \"...\"}"
)
VERSION_SYSTEM = (
    "You read the first pages of a hardware manual or release notes and return its version label: "
    "firmware or OS version and/or revision and date as printed, short, like 'firmware 1.5 (2026.11.02)' "
    "or 'Rev C (2027-01-10)'. If none is printed, return null. Reply with JSON only: {\"version\": ...}"
)


# ---------------------------------------------------------------- small helpers

def keep_awake() -> subprocess.Popen | None:
    """Stop idle and system sleep for as long as this process lives; the display may still sleep."""
    if platform.system() != "Darwin":
        return None
    return subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())])


def notify(title: str, msg: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["osascript", "-e", f"display notification {json.dumps(msg)} with title {json.dumps(title)}"],
                       check=False)


def git(*args, check=True, cwd=None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd or paths.REPO_ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def local_repo():
    """The private overlay folder when it is its own git repo (rack and note changes are committed there)."""
    lr = paths.local_root()
    return lr if lr and (lr / ".git").exists() else None


def ollama_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            return any(m.get("name") == MODEL for m in json.loads(r.read()).get("models", []))
    except Exception:  # noqa: BLE001
        return False


def chat_json(system: str, messages: list[dict]) -> dict:
    body = json.dumps({"model": MODEL, "stream": False, "format": "json", "think": False,
                       "options": {"temperature": 0.3},
                       "messages": [{"role": "system", "content": system}, *messages]}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.loads(r.read())["message"]["content"])


def device_name(device: str) -> str:
    """A readable device name for prompts: its manual's title without 'manual', 'user guide' etc."""
    import re
    titles = [s.title for s in load_sources() if s.device == device and s.kind == "manual"]
    t = titles[0] if titles else device.replace("_", " ")
    t = re.sub(r"\s*\(.*?\)", "", t)
    t = re.sub(r"\b(official\s+)?(user\s+|operation\s+)?(manual|guide|product page|cheat sheet)\b.*$", "", t,
               flags=re.I)
    return t.strip() or device.replace("_", " ")


def set_fact_fields(fid: str, **fields) -> None:
    """Rewrite one fact's block with new field values; the rest of the file is untouched."""
    device = factsmod.find(fid)["device"]
    file = factsmod.facts_file(device)
    text = file.read_text()
    a, b = refresh._block_span(text, "id", fid)
    fact = yaml.safe_load(text[a:b])[0]
    fact.update(fields)
    order = factsmod.ORDER
    fact = {k: fact[k] for k in order if k in fact} | {k: v for k, v in fact.items() if k not in order}
    file.write_text(refresh._replace_block(text, a, b, yaml.safe_dump([fact], sort_keys=False,
                                                                       allow_unicode=True, width=110)))
    yaml.safe_load(file.read_text())


# ---------------------------------------------------------------- local-model steps

VERSION_RE = re.compile(r"^[\w .,:()/+-]{1,60}$")


def new_version_label(sid: str, old: str) -> str | None:
    units = load_units(sid)[:2]
    head = "\n".join((u.get("md") or u.get("raw") or "") for u in units)[:3000]
    if not head.strip():
        return None
    try:
        v = chat_json(VERSION_SYSTEM, [{"role": "user", "content": f"Previous label: {old}\n\n{head}"}]).get("version")
    except Exception:  # noqa: BLE001
        return None
    if not v or not isinstance(v, str) or v.strip() == old or not VERSION_RE.match(v.strip()):
        return None              # anything that isn't a plain version label (URLs, sentences, markup) is dropped
    return v.strip()


def passage_for(fact: dict) -> str:
    want = [norm(a) for a in fact["anchors"]]
    for u in load_units(fact["source"]):
        t = (u.get("md") or "") + " " + (u.get("raw") or "")
        if all(w in norm(t) for w in want):
            return (u.get("md") or u.get("raw") or "")[:2500]
    return ""


def reword(fact: dict, searcher, kind: str | None, hits) -> tuple[str | None, int | None, list]:
    """Up to TRIES questions from the local model; returns (q, rank, attempts) for the first that
    puts the anchored passage in the top 3, else (None, best_rank, attempts)."""
    from napier import evaluate as ev
    name = device_name(fact["device"])
    wrong = "\n".join(f"- {h.text[:200]}" for h in hits[:3])
    msgs = [{"role": "user", "content": f"Device: {name}\nFact: {fact['claim']}\nOld question (failed): {fact['q']}\n\n"
                                        f"Target passage:\n{passage_for(fact)}\n\nReturned instead:\n{wrong}"}]
    attempts, best = [], None
    for _ in range(TRIES):
        try:
            q = (chat_json(REWORD_SYSTEM, msgs).get("q") or "").strip()
        except Exception as e:  # noqa: BLE001
            attempts.append(dict(error=str(e)))
            continue
        if not q or any(norm(a) in norm(q) for a in fact["anchors"]):
            attempts.append(dict(q=q, rejected="empty or copied the anchor"))
            msgs += [{"role": "assistant", "content": json.dumps({"q": q})},
                     {"role": "user", "content": "Rejected: write a different natural question."}]
            continue
        res = searcher.search(q, device=fact["device"], kind=kind, top=10)
        rank = next((i + 1 for i, h in enumerate(res) if ev.holds(h.text, fact, primary_only=True)), None)
        attempts.append(dict(q=q, rank=rank))  # type: ignore[dict-item]
        if rank and rank <= 3:
            return q, rank, attempts
        if rank and (best is None or rank < best):
            best = rank
        got = "\n".join(f"- {h.text[:200]}" for h in res[:3])
        msgs += [{"role": "assistant", "content": json.dumps({"q": q})},
                 {"role": "user", "content": f"The target ranked {rank or 'below 10'}. It returned:\n{got}\nTry again."}]
    return None, best, attempts


# ---------------------------------------------------------------- the pass

def overlay_tests(lrepo) -> str:
    """Run the overlay's own tests (local/tests) before public changes are committed and pushed, so a
    private guard there (say, a check that nothing private reaches the public tree) can stop the push.
    Returns "" when they pass or there are none, else the tail of pytest's output."""
    if not lrepo or not (Path(lrepo) / "tests").is_dir():
        return ""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=lrepo, capture_output=True, text=True)
    return "" if r.returncode == 0 else "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])


def run(merge: bool = False, push: bool = True, log=print) -> dict:
    from napier import evaluate as ev
    from napier import search as sm
    from napier.store import EMBED_MODEL, Store

    awake = keep_awake()
    today = dt.date.today().isoformat()
    rep: dict[str, Any] = dict(date=today, model=MODEL, updated=[], review=[], reworded=[], pages_fixed=[], eval=None,
               outcome="")
    reports = paths.home() / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    def finish(outcome: str) -> dict:
        rep["outcome"] = outcome
        (reports / f"refresh-{today}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
        (reports / f"refresh-{today}.md").write_text(render(rep))
        (reports / "latest.md").write_text(render(rep))
        n = len(rep["review"])
        notify("napier refresh", outcome + (f" · {n} for review" if n else ""))
        log(outcome)
        if awake:
            awake.terminate()
        return rep

    try:
        # 0. Don't touch work in progress.
        if git("status", "--porcelain"):
            return finish("skipped: napier has uncommitted changes")
        if git("branch", "--show-current") != "main":
            return finish("skipped: napier is not on main")
        if push:                                   # --no-push touches no remote: no pull either
            git("pull", "--ff-only", "-q", check=False)
        lrepo = local_repo()
        if lrepo:
            if git("status", "--porcelain", cwd=lrepo):
                return finish("skipped: the local overlay has uncommitted changes")
            if push:
                git("pull", "--ff-only", "-q", check=False, cwd=lrepo)

        # 1. What changed upstream?
        srcs = load_sources()
        checks = refresh.check(srcs, log=lambda c: log(f"{c.status:8s} {c.id} {c.detail}"))
        changed = [c for c in checks if c.status == "changed"]
        for c in checks:
            if c.status in ("gone", "error"):
                rep["review"].append(dict(kind=f"source-{c.status}", id=c.id, detail=c.detail))

        # 1b. The rack from its rack source (a plug-in may fetch once): a change re-ingests notes/rack.md and gets committed.
        rack_changed = False
        try:
            from napier import rack as rackmod
            rr = rackmod.sync(log=lambda m: log(f"rack     {m}"))
            rack_changed = rr["changed"]
            rep["rack"] = {k: [f"{m['vendor']} {m['name']}" for m in rr[k]]
                           for k in ("added", "removed", "recount", "unmapped",
                                     "wishlist_added", "wishlist_removed", "wishlist_unmapped")}
            rep["rack"]["changed"] = rack_changed
            from napier import specs as specmod
            snap = rackmod.load_snapshot() or {"modules": []}
            rep["rack"]["power_mismatches"] = [f"{m['name']} ({', '.join(m['diffs'])})"
                                               for m in specmod.compare(snap["modules"])]
            for m in rr["unmapped"]:
                rep["review"].append(dict(kind="rack-unmapped", id=m["slug"],
                                          detail=f"{m['vendor']} {m['name']}: add its manual, then map it in racks/devices.yaml"))
            for m in rr.get("wishlist_unmapped", []):
                rep["review"].append(dict(kind="wishlist-unmapped", id=m["slug"],
                                          detail=f"{m['vendor']} {m['name']} (planning rack, not owned): add its manual, "
                                                 "then map it in racks/devices.yaml"))
            if rr.get("wishlist_error"):
                rep["review"].append(dict(kind="wishlist-rack-error", id="wishlist", detail=rr["wishlist_error"]))
        except Exception as e:  # noqa: BLE001
            rep["review"].append(dict(kind="rack-error", id="rack", detail=f"{type(e).__name__}: {e}"))
        if not changed and not rack_changed:
            return finish(f"no changes upstream ({len(checks)} sources checked, rack unchanged)")
        llm = ollama_ok()
        if not llm:
            rep["review"].append(dict(kind="local-model", id=MODEL, detail=f"{MODEL} not reachable at {OLLAMA}"))

        # 2. Apply, ingest, recheck.
        byid = {s.id: s for s in srcs}
        for c in changed:
            a = refresh.apply(c.id)
            entry = dict(id=c.id, device=c.device, old_version=c.version, new_version=None,
                         offset=a.get("offset"), offset_note=a.get("offset_note"))
            rep["updated"].append(entry)
        fresh = load_sources()
        rack_ids = {s.id for s in fresh if rack_changed and s.path and s.path.replace("\\", "/") == RACK_NOTE}
        Store().ingest([s for s in fresh if s.id in {c.id for c in changed} | rack_ids], embed_model=EMBED_MODEL,
                       all_sources=fresh, log=lambda m: None)
        for e in rep["updated"]:  # type: ignore[misc]
            v = new_version_label(e["id"], e["old_version"]) if llm else None
            base = re.sub(r"\s*\(changed upstream [\d-]+\)$", "", e["old_version"])
            e["new_version"] = v or f"{base} (changed upstream {today})"
            refresh.update_source_entry(e["id"], {"version": e["new_version"]})
            if e.get("offset_note"):
                rep["review"].append(dict(kind="page-offset", id=e["id"], detail=e["offset_note"]))
        changed_ids = {c.id for c in changed} | rack_ids
        for r in refresh.recheck():
            if r.source not in changed_ids:
                continue
            if r.problem == "page-moved" and r.found_pages:
                refresh.set_fact_pages(r.id, r.found_pages)
                rep["pages_fixed"].append(dict(id=r.id, detail=r.detail))
            elif r.problem in ("anchor-missing", "alt-only"):
                rep["review"].append(dict(kind=r.problem, id=r.id, detail=r.detail))

        # 3. Eval affected devices; reword misses on changed sources with the local model.
        searcher = sm.Searcher(rerank_model=sm.RERANK_MODEL)
        devices = sorted({e["device"] for e in rep["updated"]} | {s.device for s in fresh if s.id in rack_ids})
        missing = {x["id"] for x in rep["review"] if x["kind"] == "anchor-missing"}
        for d in devices:
            cases = factsmod.eval_cases(d)
            res = ev.evaluate(searcher, cases, k=10, rerank=True)
            for f in cases:
                r = res.ranks[f["id"]]  # type: ignore[assignment]
                if (r and r <= 3) or f["id"] in missing:  # type: ignore[operator]
                    continue
                kind = byid[f["source"]].kind if f.get("source") in byid else None
                if f.get("source") in changed_ids and llm:
                    hits = searcher.search(f["q"], device=d, kind=kind, top=10)
                    q, rank, attempts = reword(f, searcher, kind, hits)
                    if q:
                        set_fact_fields(f["id"], q=q)
                        rep["reworded"].append(dict(id=f["id"], old=f["q"], new=q, rank=rank))
                        continue
                    rep["review"].append(dict(kind="eval-miss", id=f["id"], detail=f"local model couldn't fix (best rank {rank})",
                                              attempts=attempts))
                else:
                    rep["review"].append(dict(kind="eval-miss", id=f["id"],
                                              detail=f"rank {r or '>10'}; source unchanged, so not reworded"))

        # 3b. Specs: power anchors and jack names must still be on their cited pages.
        from napier import specs as specmod
        sc = specmod.check()
        for pr in sc.problems:
            rep["review"].append(dict(kind="spec", id=pr.spec, detail=f"{pr.what}: {pr.detail}"))

        # 4. Gate: full eval + tests.
        allres = ev.evaluate(searcher, factsmod.eval_cases(), k=10, rerank=True)
        rep["eval"] = dict(hit1=round(allres.hit(1), 3), hit3=round(allres.hit(3), 3), facts=len(allres.ranks))
        tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=paths.REPO_ROOT, capture_output=True, text=True)
        rep["tests"] = tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "no output"
        passing = allres.hit(3) >= ev.MIN_HIT3 and tests.returncode == 0

        # 5. Branch, commit, PR, maybe merge.
        if not push:
            return finish(f"applied {len(rep['updated'])} updates locally (no push)")
        names = ", ".join([e["id"] for e in rep["updated"]] + (["rack"] if rack_changed else []))   # local commit only
        if lrepo and git("status", "--porcelain", cwd=lrepo):
            # private: rack snapshot, generated notes, overlay sources and facts. Straight to its main.
            git("add", "-A", cwd=lrepo)
            git("commit", "-q", "-m", f"Auto refresh {today}: {names}", cwd=lrepo)
            git("push", "-q", cwd=lrepo, check=False)
            rep["local_commit"] = git("rev-parse", "--short", "HEAD", cwd=lrepo)
        if not git("status", "--porcelain"):
            return finish(f"updated the private overlay only ({names})")
        failed = overlay_tests(lrepo)
        if failed:
            rep["review"].append(dict(kind="push-blocked", id="local/tests", detail=failed))
            return finish("public changes left uncommitted: the overlay's tests failed (see review)")
        pub = public_report(rep)
        pub_names = ", ".join(e["id"] for e in pub["updated"]) or "facts"
        branch = f"auto-refresh-{today}"
        git("checkout", "-q", "-B", branch)        # -B: a second run the same day reuses the name
        git("add", *[d for d in ("sources.yaml", "facts", "specs") if (paths.REPO_ROOT / d).exists()])
        git("commit", "-q", "-m", f"Auto refresh {today}: {pub_names}\n\n{render(pub, short=True)}")
        git("push", "-q", "-u", "origin", branch)
        body = render(pub)
        pr = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch,  # type: ignore[assignment]
                             "--title", f"Auto refresh {today}", "--body", body],
                            cwd=paths.REPO_ROOT, capture_output=True, text=True)
        rep["pr"] = pr.stdout.strip() or pr.stderr.strip()  # type: ignore[attr-defined]
        if pr.returncode:  # type: ignore[attr-defined]
            git("checkout", "-q", "main")
            return finish(f"updated {len(rep['updated'])} sources, branch {branch} pushed but no PR ({rep['pr'][:200]})")
        model_text = bool(rep["reworded"])          # questions the local model wrote: a person reviews them
        if merge and passing and not model_text:
            # squash, queued until the required CI checks pass (the repository allows only squash merges)
            m = subprocess.run(["gh", "pr", "merge", branch, "--squash", "--auto", "--delete-branch"],
                               cwd=paths.REPO_ROOT, capture_output=True, text=True)
            git("checkout", "-q", "main")
            git("pull", "-q", "--ff-only", check=False)
            if m.returncode:
                return finish(f"updated {len(rep['updated'])} sources, PR open (merge failed: "
                              f"{(m.stderr or m.stdout).strip()[:200]})")
            return finish(f"updated {len(rep['updated'])} sources, merge queued for when CI passes "
                          f"(hit@3 {rep['eval']['hit3']:.0%})")
        git("checkout", "-q", "main")
        why = ("eval or tests below the gate" if not passing else
               "questions reworded by the local model need review" if model_text else "left for review")
        return finish(f"updated {len(rep['updated'])} sources, PR open ({why})")
    except Exception as e:  # noqa: BLE001  always leave a report, and leave the checkout on main
        if git("branch", "--show-current", check=False) not in ("main", ""):
            git("checkout", "-q", "main", check=False)
        rep["review"].append(dict(kind="refresh-failed", id="napier refresh", detail=f"{type(e).__name__}: {e}"))
        return finish(f"failed: {type(e).__name__}: {e}")

def public_report(rep: dict) -> dict:
    """The parts of a refresh report that may go into the public repository's commit and PR: public
    sources and facts only. Overlay sources, private facts and the rack stay in the local report."""
    from napier.sources import load_sources as _load
    pub_ids = {s.id for s in _load(paths.sources_file())}
    pub_facts = {f["id"] for f in factsmod.load(root=paths.facts_dir())}
    from napier import specs as specmod
    pub_specs = set(specmod.load_all())
    keep = pub_ids | pub_facts | pub_specs | {MODEL, "napier refresh", "local/tests"}
    out = dict(rep)
    out["updated"] = [e for e in rep["updated"] if e["id"] in pub_ids]
    out["reworded"] = [r for r in rep["reworded"] if r["id"] in pub_facts]
    out["pages_fixed"] = [r for r in rep["pages_fixed"] if r["id"] in pub_facts]
    out["review"] = [x for x in rep["review"] if x.get("id") in keep and not x["kind"].startswith(("rack", "wishlist"))
                     and x["kind"] != "push-blocked"]
    out.pop("rack", None)
    out.pop("local_commit", None)
    return out


def render(rep: dict, short: bool = False) -> str:
    L = [f"# napier refresh {rep['date']}", "", f"**{rep.get('outcome', '')}**", ""]
    if rep["updated"]:
        L += ["## Updated sources", "", "| source | was | now |", "|---|---|---|"]
        L += [f"| {e['id']} | {e['old_version']} | {e['new_version']} |" for e in rep["updated"]]
        L.append("")
    if rep["pages_fixed"]:
        L += [f"Pages fixed automatically: {len(rep['pages_fixed'])}", ""]
    if rep["reworded"]:
        L += ["## Questions reworded by the local model", ""]
        L += [f"- `{r['id']}`: {r['old']} -> {r['new']} (rank {r['rank']})" for r in rep["reworded"]]
        L.append("")
    rk = rep.get("rack") or {}
    if any(rk.get(k) for k in ("added", "removed", "recount")):
        L += ["## Rack changes", ""]
        L += [f"- {k}: {', '.join(rk[k])}" for k in ("added", "removed", "recount") if rk.get(k)]
        L.append("")
    if rk.get("power_mismatches"):
        L += [f"Manual vs rack-source power differs for {len(rk['power_mismatches'])} modules "
              f"(`napier rack check`): {', '.join(rk['power_mismatches'])}", ""]
    if rep["review"]:
        L += ["## Needs review", ""]
        L += [f"- {x['kind']}: `{x['id']}` {x.get('detail', '')}" for x in rep["review"]]
        L.append("")
    if rep.get("eval"):
        L += [f"Eval: hit@1 {rep['eval']['hit1']:.0%}, hit@3 {rep['eval']['hit3']:.0%} over {rep['eval']['facts']} facts. "
              f"Tests: {rep.get('tests', '')}", ""]
    if not short:
        L += [f"Local model: {rep['model']}"]
    return "\n".join(L)
