## What this changes

<!-- What and why. Link the issue if there is one (sources and facts for gear you own don't need one). -->

## Testing

<!-- The commands you ran and what they printed: pytest, ruff, mypy, and facts recheck and eval scores for data. -->

## Risk

<!-- Low, Medium or High (REVIEW.md), set by the paths this touches, and why. -->

## How to revert

<!-- Usually: revert the squash commit. Say what else needs undoing, if anything: a release, a changed pin, a moved source. -->

## Checks

- [ ] A fresh-context review ran on the diff (REVIEW.md), and every finding is fixed or answered
- [ ] `pytest -q` and `ruff check src tests` pass, and a behavior change comes with a test
- [ ] For a new source: `source add` passed robots.txt (no `--ignore-robots` unless the publisher said yes, explained above), the manual is pinned, and the page offset was checked
- [ ] For new facts: each has a source, a question and anchors (plus the printed page for a PDF), and `napier facts recheck --device <id>` and `napier eval --device <id>` pass (score above)
- [ ] No hardware checks, open questions or forum paraphrases in `facts/`; those stay in your overlay
- [ ] For specs: `napier specs check <name>` passes with the manual fetched
- [ ] No personal data: no real person, private rig or rack, in code, claims, notes or commit messages; fixtures use invented names and `example.test` URLs
- [ ] `rack export` and MCP JSON only gained fields; nothing renamed or removed
- [ ] Docs and CHANGELOG.md updated where behavior changed
