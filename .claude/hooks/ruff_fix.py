"""Claude Code hook: lint a Python file in this repository right after Claude edits it.

Runs `ruff check --fix` on that one file. Whatever ruff can't fix goes back to Claude (exit code 2,
message on stderr), so it gets fixed before review. Without ruff installed it does nothing.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    name = (event.get("tool_input") or {}).get("file_path") or ""
    if not name.endswith(".py"):
        return 0
    path = Path(name).resolve()
    if ROOT not in path.parents or not path.is_file():
        return 0
    venv = ROOT / ".venv" / "bin" / "ruff"      # the locked version CI uses, ahead of any global ruff
    ruff = str(venv) if venv.exists() else shutil.which("ruff")
    if not ruff:
        return 0
    result = subprocess.run([ruff, "check", "--fix", "--quiet", str(path)], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        sys.stderr.write(result.stdout + result.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
