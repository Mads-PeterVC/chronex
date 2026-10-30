"""The Graphviz view of a lineage: one node per step, details in tooltips."""

import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

import chronex
from chronex import Out
from chronex import graph as graphs
from chronex.cli import main
from chronex.views.dot import to_dot
from chronex.views.lineage import lineage


@chronex.step
def simulate(target: Out[Path], seed: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"simulated data for seed {seed}, long enough to link by content\n" * 2)


def sweep_and_plot() -> None:
    Path("config.json").write_text('{"bins": 10}')
    for seed in range(3):
        simulate(Path(f"data/run-{seed}.csv"), seed)
    with chronex.step("plot") as s:
        s.input("config.json")
        text = "".join(Path(s.input(f"data/run-{seed}.csv")).read_text() for seed in range(3))
        Path(s.output("figure.png")).write_text(text)


def test_runs_of_a_step_fold_into_one_node(workdir: Path) -> None:
    sweep_and_plot()
    found = lineage(graphs.build(graphs.load(workdir)), "figure.png")
    assert {name: len(runs) for name, runs in found.steps.items()} == {"simulate": 3, "plot": 1}
    assert found.edges == {("simulate", "plot"): {f"data/run-{i}.csv" for i in range(3)}}
    assert found.origins == {"plot": {"config.json": found.origins["plot"]["config.json"]}}
    dot = to_dot(found)
    assert '"step:simulate" [label="simulate ×3"' in dot
    assert "seed = 0–2 (3 values)" in dot
    assert (
        '"step:simulate" -> "step:plot" [label="3 files in data/", tooltip="data/run-0.csv&#10;'
        in dot
    )
    assert '"origin:plot" [label="config.json", shape="note"' in dot
    assert '"step:plot" -> "file:figure.png";' in dot
    assert "#f8d7da" not in dot and "#fff3cd" not in dot  # nothing flagged


def test_flags_colour_a_step_and_unrecorded_inputs_are_shown(workdir: Path) -> None:
    sweep_and_plot()
    Path("data/run-1.csv").write_text("edited by hand, long enough to be linked by content\n")
    Path("hidden.txt").write_text("x")
    with chronex.step("plot") as s:
        Path("hidden.txt").read_text()
        text = "".join(Path(s.input(f"data/run-{seed}.csv")).read_text() for seed in range(3))
        Path(s.output("figure.png")).write_text(text)
    found = lineage(graphs.build(graphs.load(workdir)), "figure.png")
    assert found.count("error") == 1  # modified-after-write
    assert found.unlinked == {
        "plot": {
            "data/run-1.csv": "changed without a record",
            "hidden.txt": "read without being declared",
        }
    }
    dot = to_dot(found)
    assert '"step:plot" [label="plot", fillcolor="#f8d7da"' in dot
    assert "error modified-after-write: data/run-1.csv differs" in dot
    assert '"unlinked:plot" [label="2 unrecorded inputs"' in dot


def test_a_file_without_lineage_raises(workdir: Path) -> None:
    Path("loose").write_text("x")
    with pytest.raises(LookupError, match="no recorded step wrote or read loose"):
        lineage(graphs.build(graphs.load(workdir)), "loose")


def test_show_prints_dot_that_graphviz_accepts(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep_and_plot()
    assert main(["show", "figure.png", "--dot"]) == 0
    dot = capsys.readouterr().out
    assert dot.startswith("digraph lineage {")
    if shutil.which("dot"):
        svg = subprocess.run(["dot", "-Tsvg"], input=dot, capture_output=True, text=True)
        assert svg.returncode == 0, svg.stderr
        assert 'xlink:title="simulate: 3 runs (3 completed)' in svg.stdout


def test_a_python_script_shows_its_command_and_file(workdir: Path) -> None:
    Path("plot.py").write_text("from pathlib import Path\nPath('figure.png').write_text('x')\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    command = [sys.executable, "-m", "chronex.cli", "run", "-q", "--", sys.executable, "plot.py"]
    assert subprocess.call([*command, "--dpi", "90"], env=env) == 0
    dot = to_dot(lineage(graphs.build(graphs.load(workdir)), "figure.png"))
    assert "command = python plot.py --dpi 90&#10;code: plot.py not in git&#10;" in dot
    assert "host:" not in dot


def test_a_cell_shows_its_document_and_source(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "with chronex.step('plot') as s:\n    Path(s.output('figure.png')).write_text('x')"
    shell = types.SimpleNamespace(user_ns={"In": ["", source]})
    ipython = types.ModuleType("IPython")
    ipython.get_ipython = lambda: shell  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setenv("QUARTO_DOCUMENT_PATH", str(workdir))
    monkeypatch.setenv("QUARTO_DOCUMENT_FILE", "index.qmd")
    Path("index.qmd").write_text("# a document")
    with chronex.step("plot") as s:
        Path(s.output("figure.png")).write_text("x")
    dot = to_dot(lineage(graphs.build(graphs.load(workdir)), "figure.png"))
    assert "code: index.qmd not in git&#10;cell:&#10;  with chronex.step('plot') as s:&#10;" in dot
