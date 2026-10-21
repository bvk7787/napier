# Instructions for coding agents

If you're helping someone use napier, run the CLI or the MCP tools and cite what they print: title,
version and printed page. If you're changing its code or data:

- Read [CLAUDE.md](CLAUDE.md) first. It covers the ground rules (polite fetching, printed pages,
  wrong facts get refuted and kept, nothing personal in the public tree), the layout and the checks
  to run.
- [CONTRIBUTING.md](CONTRIBUTING.md) says what a pull request needs, and [REVIEW.md](REVIEW.md) how
  it's reviewed: what failure looks like in each area, risk tiers, and how findings are written.
- [docs/rack.md](docs/rack.md) covers the rack planner and rack-source plug-ins.
- Never copy anything from a user's overlay (`local/`) into the public tree, and leave names, rack
  URLs and rig notes out of public files and commit messages.
