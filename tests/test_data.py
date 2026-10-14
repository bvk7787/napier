"""The shipped data stays consistent: sources, facts, specs and the module catalog, as a contributor
would change them. Offline: these read the YAML only, never the manuals."""
import collections

import pytest
import yaml

from napier import facts, paths, specs
from napier.sources import FORMATS, KINDS, load_sources

ROLES = {"voice", "filter", "effect", "rhythm", "sequencer", "modulation", "utility", "mixer", "midi", "expander"}


@pytest.fixture
def srcs():
    return load_sources()                      # the public list only (conftest turns the overlay off)


def test_sources_are_well_formed(srcs):
    ids = [s.id for s in srcs]
    assert len(ids) == len(set(ids))
    for s in srcs:
        assert s.kind in KINDS and s.format in FORMATS, s.id
        assert s.url or s.path, f"{s.id}: needs a url or a path"
        if s.kind == "manual" and s.format == "pdf" and s.url:
            assert s.sha256, f"{s.id}: pin manuals (sha256)"


def test_public_sources_point_at_no_local_files(srcs):
    """Local files are the owner's own notes and belong in the overlay."""
    assert not [s.id for s in srcs if s.path], "note sources go in local/sources.yaml"


def test_facts_are_well_formed(srcs):
    known = {s.id for s in srcs}
    fmt = {s.id: s.format for s in srcs}
    devices = {s.device for s in srcs}
    seen = collections.Counter()
    for f in facts.load():
        seen[f["id"]] += 1
        assert f.get("claim"), f["id"]
        assert f.get("status") in facts.STATUSES, f["id"]
        if f.get("source"):
            assert f["source"] in known, f"{f['id']}: unknown source {f['source']}"
        if f["status"] == "manual" and fmt.get(f.get("source")) == "pdf":
            assert f.get("pages"), f"{f['id']}: a fact from a PDF manual cites its printed pages"
        if f.get("q"):
            assert f.get("anchors"), f"{f['id']}: an eval question needs anchors"
        if f.get("anchors"):
            assert f.get("q") and f.get("source"), f"{f['id']}: anchors need a question and a source"
    assert not [k for k, n in seen.items() if n > 1], "fact ids must be unique"
    fact_devices = {f["device"] for f in facts.load()}
    assert fact_devices <= devices | {"metropolix_solo"}, fact_devices - devices


def test_specs_name_known_sources(srcs):
    known = {s.id for s in srcs}
    for name, s in specs.load_all().items():
        assert s.get("slugs"), name
        if s.get("source"):
            assert s["source"] in known, f"{name}: unknown source {s['source']}"


def test_catalog_maps_to_known_devices(srcs):
    devices = {s.device for s in srcs}
    cat = yaml.safe_load((paths.REPO_ROOT / "catalog" / "modules.yaml").read_text())["modules"]
    for slug, v in cat.items():
        v = v or {}
        assert v.get("role") in ROLES, f"{slug}: role {v.get('role')!r}"
        if v.get("device"):
            assert v["device"] in devices, f"{slug}: device {v['device']} has no source"
        else:
            assert v.get("note"), f"{slug}: say why there's nothing to index"
        if v.get("parent"):
            assert v["parent"] in cat, f"{slug}: parent {v['parent']} isn't in the catalog"


ANCHOR_MAX_WORDS = 25    # docs/data-policy.md: anchors are short quotations, enough to find the passage


def _anchors():
    for f in facts.load():
        alts = [a for alt in f.get("alt") or [] for a in (alt if isinstance(alt, list) else [alt])]
        for a in [*(f.get("anchors") or []), *alts]:
            yield f["id"], str(a)
    for name, s in specs.load_all().items():
        a = (s.get("power") or {}).get("anchor")
        if a:
            yield name, str(a)


def test_forum_facts_quote_no_one(srcs):
    """Forum facts paraphrase and link the thread; they never quote an individual poster."""
    forums = {s.id for s in srcs if s.format == "discourse"}
    quoted = [f["id"] for f in facts.load() if f.get("source") in forums and (f.get("anchors") or f.get("alt"))]
    assert not quoted, f"forum facts with quoted anchors: {quoted}"


def test_anchors_are_short_quotations():
    long = [(where, len(a.split())) for where, a in _anchors() if len(a.split()) > ANCHOR_MAX_WORDS]
    assert not long, f"anchors over {ANCHOR_MAX_WORDS} words: {long}"
