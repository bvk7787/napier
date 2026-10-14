# Instructions for coding agents

Helping someone *use* napier (look something up, add a source, check a fact, plan a rack)? Use the
CLI or the MCP tools and cite what they print: title, version, printed page. Changing its code or
data? Read on.

- Read [CLAUDE.md](CLAUDE.md) first: the ground rules (polite fetching, printed pages, facts are
  refuted rather than deleted, nothing personal in the public tree), the layout, and the checks to
  run.
- Contributing (tests, what a pull request needs): [CONTRIBUTING.md](CONTRIBUTING.md).
- The rack planner and rack-source plug-ins: [docs/rack.md](docs/rack.md).
- Never move data from a user's overlay (`local/`) into the public tree, and never write names,
  rack URLs or rig notes into public files or commit messages.
