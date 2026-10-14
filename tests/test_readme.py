"""Every `napier ...` command the docs show is one the CLI accepts, and the offline ones run."""
import re
import shlex
import warnings
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from napier import cli

ROOT = Path(__file__).parents[1]
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]


def doc_commands():
    """(file, argv) for each napier command in a fenced code block, comments and placeholders aside."""
    for doc in DOCS:
        in_code = False
        text = re.sub(r"\\\n\s*", " ", doc.read_text())          # join continued lines
        for line in text.splitlines():
            if line.startswith("```"):
                in_code = not in_code
                continue
            if not in_code:
                continue
            line = re.sub(r"\s+#.*$", "", line).strip()
            for part in re.split(r"\s+(?:&&|\|)\s+", line):
                if part.startswith("napier ") and "<" not in part and "..." not in part:
                    yield doc.name, tuple(shlex.split(part)[1:])


COMMANDS = sorted(set(doc_commands()))


def parse(argv: list[str]) -> None:
    """Parse argv the way napier would, down to the last subcommand, without running anything."""
    cmd: click.Command = cli.main
    name = "napier"
    while True:
        ctx = cmd.make_context(name, list(argv), resilient_parsing=False)
        if not isinstance(cmd, click.Group):
            return
        with warnings.catch_warnings():               # protected_args: deprecated in click 8.2, still needed
            warnings.simplefilter("ignore", DeprecationWarning)
            rest = [*ctx.protected_args, *ctx.args]
        if not rest:
            return
        name, cmd, argv = cmd.resolve_command(ctx, rest)


def test_the_docs_show_commands():
    assert len(COMMANDS) > 10


@pytest.mark.parametrize("doc, argv", COMMANDS, ids=[f"{d}: {' '.join(a)}" for d, a in COMMANDS])
def test_documented_command_parses(doc, argv):
    try:
        parse(argv)
    except click.BadParameter as e:          # an example file that isn't on this machine is fine
        if "does not exist" not in str(e):
            raise


@pytest.mark.parametrize("argv", [
    ["status"], ["status", "--wide"], ["status", "--device", "m8_tracker"], ["source", "list", "--device", "m8_tracker"],
    ["facts", "list", "--device", "m8_tracker"], ["rack", "sources"], ["rack", "power"], ["rack", "usage"],
    ["rack", "export"], ["rack", "check"], ["--version"],
])
def test_offline_commands_run_on_the_shipped_data(argv, monkeypatch, tmp_path):
    monkeypatch.delenv("NAPIER_CATALOG")                 # the shipped catalog and example rack
    monkeypatch.setenv("NAPIER_NOTES", str(tmp_path / "notes"))
    r = CliRunner().invoke(cli.main, argv)
    assert r.exit_code == 0, r.output
    assert "Traceback" not in r.output
