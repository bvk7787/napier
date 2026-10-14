## What this changes

<!-- What and why. Link the issue if there is one (sources and facts for gear you own don't need one). -->

## Checks

- [ ] `pytest -q` and `ruff check src tests` pass, and a behavior change comes with a test
- [ ] For a new source: `source add` passed robots.txt (no `--ignore-robots` unless the publisher said yes, explained above), the manual is pinned, and the page offset was checked
- [ ] For new facts: status and printed pages are right; facts with `q` and `anchors` pass `napier eval --device <id>` (score above)
- [ ] For `hardware` facts: what I checked on the device, and on which firmware, is described above
- [ ] For specs: `napier specs check <name>` passes with the manual fetched
- [ ] No personal data: no real person, private rig or rack; fixtures use invented names and `example.test` URLs
- [ ] `rack export` and MCP JSON only gained fields; nothing renamed or removed
- [ ] Docs and CHANGELOG.md updated where behavior changed
