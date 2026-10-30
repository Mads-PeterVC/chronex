"""Finding records on disk."""

from pathlib import Path

from chronex import graph as graphs
from tests.helpers import make


def test_records_are_found_without_walking_virtualenvs(workdir: Path) -> None:
    (workdir / ".venv" / "lib" / ".chronex").mkdir(parents=True)
    (workdir / ".venv" / "lib" / ".chronex" / "x.json").write_text("not json")
    make(Path("a"), "v1")
    assert len(graphs.load(workdir)) == 1
