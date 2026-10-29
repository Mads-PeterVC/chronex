"""The known-answer test: every variant of the toy workflow, with and without planted faults."""

import inspect
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from chronex import graph as graphs

# The toy workflow needs the examples group: uv sync --group examples
pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

TOY = Path(__file__).parents[1] / "examples" / "toy-workflow"
ANNOTATED = ["decorator", "block", "script", "mixed"]
FAULTS = Counter(
    {
        "modified-after-write": 2,  # both fits read the hand-edited label file
        "failed": 1,  # labelling chunk 3
        "failed-producer": 1,  # collect copies chunk 3 anyway
        "undeclared-read": 2,  # both fits read configs/prior.json inside toymodel
        "superseded-input": 3,  # the first stage, and the two scans that used it
        "mixed-lineage": 1,  # export combines curves from both models
    }
)


def shephex_unwraps() -> bool:
    try:
        from shephex.experiment.procedure import script
    except ImportError:
        return False
    return "unwrap" in inspect.getsource(script)


def run_toy(variant: str, workspace: Path, faults: bool) -> graphs.Graph:
    if variant == "mixed" and not shephex_unwraps():
        pytest.skip("shephex's ScriptProcedure does not unwrap decorated functions yet")
    command = [sys.executable, str(TOY / "drive.py"), variant, str(workspace)]
    subprocess.run([*command, *(["--faults"] if faults else [])], check=True, capture_output=True)
    return graphs.build(graphs.load(workspace))


def flag_counts(graph: graphs.Graph) -> Counter[str]:
    return Counter(f.code for _, f in graph.all_flags() if f.level != "info")


def lineage_names(graph: graphs.Graph, figure: Path) -> set[str]:
    (plot,) = graph.producers_of(figure)
    return {graph.records[s]["name"] for s in graph.ancestry(plot)}


@pytest.mark.toy
@pytest.mark.parametrize("variant", ANNOTATED)
def test_clean_run_links_every_step(variant: str, tmp_path: Path) -> None:
    graph = run_toy(variant, tmp_path / variant, faults=False)
    assert flag_counts(graph) == Counter()
    assert lineage_names(graph, tmp_path / variant / "results/cv.png") == {
        "generate",
        "label",
        "collect",
        "fit",
        "stage",
        "scan",
        "export",
    }


@pytest.mark.toy
@pytest.mark.parametrize("variant", ANNOTATED)
def test_planted_faults_are_all_found(variant: str, tmp_path: Path) -> None:
    graph = run_toy(variant, tmp_path / variant, faults=True)
    assert flag_counts(graph) == FAULTS


@pytest.mark.toy
def test_zero_touch_misses_what_it_cannot_see(tmp_path: Path) -> None:
    """``chronex run`` finds the faults inside Python, but not what awk read in export."""
    graph = run_toy("wrapper", tmp_path / "wrapper", faults=True)
    expected = FAULTS - Counter({"undeclared-read": 2, "mixed-lineage": 1})
    assert flag_counts(graph) == expected
    assert lineage_names(graph, tmp_path / "wrapper/results/cv.png") == {"export"}
