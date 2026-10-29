import os
from pathlib import Path

import pytest


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test in its own directory, as a step's cwd decides where records go."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CHRONEX_PARENT", raising=False)
    monkeypatch.delenv("CHRONEX_AUTO", raising=False)
    return tmp_path


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "toy: runs the full toy workflow (slow)")
    os.environ.setdefault("MPLBACKEND", "Agg")
