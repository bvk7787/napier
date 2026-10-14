"""Keep tests hermetic: every NAPIER_* override cleared, NAPIER_HOME in a temp folder, and no private overlay,
napier.toml or shipped catalog unless a test sets one. No test reads a developer's setup or writes to ~/.napier."""
import os

import pytest


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    for k in [k for k in os.environ if k.startswith("NAPIER_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("NAPIER_LOCAL", "none")
    monkeypatch.setenv("NAPIER_CONFIG", "none")
    monkeypatch.setenv("NAPIER_CATALOG", "none")
    monkeypatch.setenv("NAPIER_HOME", str(tmp_path / "napier-home"))
