"""Where napier keeps things.

Public data ships in the repo: sources.yaml, facts/, specs/, catalog/ and examples/. A private
overlay adds to it: `local/` beside the checkout (gitignored, usually its own private git repo), or
the folder $NAPIER_LOCAL names ($NAPIER_LOCAL=none turns the overlay off). The overlay can hold:

  local/sources.yaml   more sources (rig notes, private documents), listed before the public ones
  local/facts/         more fact files (one per device), merged with facts/
  local/racks/         your rack: devices.yaml (rack source, owned modules), usage, challenges, scenarios
  local/notes/         notes about your setup, and the notes `rack sync` and `rack usage` generate
  local/napier.toml    owner = "Your name", rack_title = "My Rack" (used in generated prose and the viewer)

Without an overlay, the rack commands read examples/racks (a small example rack) and refuse to write.
Narrower overrides still win: NAPIER_HOME, NAPIER_SOURCES (the public list), NAPIER_FACTS,
NAPIER_SPECS, NAPIER_RACKS, NAPIER_NOTES, NAPIER_CONFIG, NAPIER_CATALOG (the module catalog, or "none").
`napier refresh` also reads NAPIER_OLLAMA (the Ollama server, default http://localhost:11434) and
NAPIER_LOCAL_MODEL (the model it uses to reword eval questions)."""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Source ids and device ids name files (~/.napier/files/<id>.pdf, facts/<device>.yaml), so they are
# plain names: lowercase letters, digits and underscores. Nothing else gets near a path.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,99}$")


def check_name(what: str, value: str) -> str:
    """value if it's a plain name (see NAME_RE), else ValueError."""
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise ValueError(f"{what} {value!r} must be lowercase letters, digits and underscores")
    return value


def inside(base: Path, p: Path) -> Path:
    """p, after checking it resolves inside base (no ../, no absolute paths, no symlink escapes)."""
    if not p.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"{p} is outside {base}")
    return p


def home() -> Path:
    """Data folder: downloaded files, parsed cache, text layer, index. Default ~/.napier."""
    return Path(os.environ.get("NAPIER_HOME") or "~/.napier").expanduser()


def local_root() -> Path | None:
    """The private overlay folder, or None. Read on every call, so a changed env var applies."""
    env = os.environ.get("NAPIER_LOCAL")
    if env:
        return None if env.lower() == "none" else Path(env).expanduser()
    p = REPO_ROOT / "local"
    return p if p.is_dir() else None


def sources_file() -> Path:
    """The public source list (where `source add` writes unless --local)."""
    return Path(os.environ.get("NAPIER_SOURCES") or REPO_ROOT / "sources.yaml").expanduser()


def local_sources_file() -> Path | None:
    lr = local_root()
    return lr / "sources.yaml" if lr else None


def sources_files() -> list[Path]:
    """Every source list to read: the overlay's first (the owner's own notes are the most specific answer
    about their setup, so grep and status list them before the manuals), then the public list."""
    pub = sources_file()
    lf = local_sources_file()
    if lf and lf.exists() and lf.resolve() != pub.resolve():
        return [lf, pub]
    return [pub]


def facts_dir() -> Path:
    """The public facts folder."""
    return Path(os.environ.get("NAPIER_FACTS") or REPO_ROOT / "facts").expanduser()


def facts_dirs() -> list[Path]:
    """Public facts, then the overlay's local/facts (if it exists)."""
    out = [facts_dir()]
    lr = local_root()
    if lr and (lr / "facts").is_dir() and (lr / "facts").resolve() != out[0].resolve():
        out.append(lr / "facts")
    return out


def examples_dir() -> Path:
    return REPO_ROOT / "examples"


def racks_dir() -> Path:
    """$NAPIER_RACKS, else local/racks, else the example rack (read only)."""
    env = os.environ.get("NAPIER_RACKS")
    if env:
        return Path(env).expanduser()
    lr = local_root()
    if lr and (lr / "racks").is_dir():
        return lr / "racks"
    return examples_dir() / "racks"


def notes_dir() -> Path:
    """$NAPIER_NOTES, else local/notes, else the example notes (read only)."""
    env = os.environ.get("NAPIER_NOTES")
    if env:
        return Path(env).expanduser()
    lr = local_root()
    if lr:
        return lr / "notes"
    return examples_dir() / "notes"


def using_examples() -> bool:
    """True when the rack commands are reading the shipped example rack (nothing of yours is set up)."""
    try:
        return racks_dir().resolve() == (examples_dir() / "racks").resolve()
    except OSError:
        return False


def config_file() -> Path | None:
    env = os.environ.get("NAPIER_CONFIG")
    if env:
        return None if env.lower() == "none" else Path(env).expanduser()
    lr = local_root()
    return lr / "napier.toml" if lr else None


def config() -> dict:
    """napier.toml from the overlay (or $NAPIER_CONFIG): owner, rack_title. Empty when there is none."""
    f = config_file()
    if not f or not f.exists():
        return {}
    with open(f, "rb") as fh:
        return tomllib.load(fh)


def owner() -> str:
    """Whose rig this is, for generated prose ("How <owner> uses ..."). Default: "the owner"."""
    return str(config().get("owner") or "the owner")


def rack_title() -> str:
    """napier.toml `rack_title`, or "" (the viewer then uses the rack's own name)."""
    return str(config().get("rack_title") or "")


def install_hint(extras: str = "index,mcp") -> str:
    """How to add optional extras to this clone's install."""
    return (f"cd {REPO_ROOT} && uv tool install -e '.[{extras}]' "
            f"(or pip install -e '.[{extras}]' in the virtual environment napier runs from)")
