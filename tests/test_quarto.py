"""Figures in a Quarto document: a tabset of the figure and its provenance."""

import os
from pathlib import Path

import pytest

import chronex
import chronex.quarto as cq
from chronex import graph as graphs


@pytest.fixture(autouse=True)
def fresh_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cq, "_script_shown", False)


def plot() -> None:
    Path("data.csv").write_text("x,y\n1,2\n")
    with chronex.step("plot") as s:
        Path(s.output("figure.png")).write_bytes(Path(s.input("data.csv")).read_bytes())


def test_a_figure_comes_with_its_lineage(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plot()
    cq.figure("figure.png", caption="A figure", label="data")
    text = capsys.readouterr().out  # printed, outside a notebook
    assert text.startswith("::: {.panel-tabset}\n\n## Figure\n\n![A figure](figure.png){#fig-data}")
    assert "\n## Provenance\n" in text
    assert "```{dot}\ndigraph lineage {" in text
    assert "no flags · 1 step · 1 origin file" in text
    assert text.count("<script>") == 1
    assert "<script>" not in cq.markdown("figure.png")  # once per document


def test_flags_are_counted_in_the_tab_and_listed(workdir: Path) -> None:
    plot()
    Path("my_hidden*").write_text("x")
    with chronex.step("plot") as s:
        Path("my_hidden*").read_text()
        Path(s.output("figure.png")).write_bytes(Path(s.input("data.csv")).read_bytes())
    text = cq.markdown("figure.png")
    assert "\n## Provenance ⚠ 1\n" in text
    assert "**1 warning** · 1 step" in text
    assert "\n\n- **warning** `undeclared-read` in plot: " in text
    assert "my\\_hidden\\*" in text  # shown as is, not as emphasis


def test_a_figure_without_lineage_says_why(workdir: Path) -> None:
    Path("drawn.png").write_bytes(b"by hand")
    text = cq.markdown("drawn.png")
    assert "No recorded lineage: no recorded step wrote or read drawn.png." in text


def test_a_figure_made_in_a_cell_is_recorded(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("data.csv").write_text("x,y\n1,2\n")
    with cq.make_figure("figures/scatter.png", caption="Scatter", dpi=100) as s:
        Path("figures").mkdir()
        Path("figures/scatter.png").write_bytes(Path(s.input("data.csv")).read_bytes())
    (record,) = graphs.load(workdir)
    assert record["name"] == "scatter"
    assert record["params"] == {"dpi": 100}
    assert [o["rel"] for o in record["outputs"]] == ["figures/scatter.png"]
    out = capsys.readouterr().out
    assert "![Scatter](figures/scatter.png)" in out
    assert '"step:scatter"' in out


def test_the_figure_path_is_relative_to_the_document(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Path("work").mkdir()
    monkeypatch.setenv("QUARTO_DOCUMENT_PATH", str(workdir))
    monkeypatch.chdir("work")
    plot()
    assert "![](work/figure.png)" in cq.markdown("figure.png")


@pytest.mark.toy
def test_the_example_site_renders(tmp_path: Path) -> None:
    """examples/quarto over the toy workflow: three figures, each with its lineage drawn."""
    import shutil
    import subprocess
    import sys

    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")
    pytest.importorskip("ipykernel")
    if not shutil.which("quarto"):
        pytest.skip("needs quarto")
    examples = Path(__file__).parents[1] / "examples"
    site = tmp_path / "examples" / "quarto"
    shutil.copytree(
        examples / "quarto", site, ignore=shutil.ignore_patterns("work", "_site", ".quarto")
    )
    shutil.copytree(examples / "toy-workflow", tmp_path / "examples" / "toy-workflow")
    result = subprocess.run(
        ["quarto", "render"],
        cwd=site,
        env={**os.environ, "QUARTO_PYTHON": sys.executable},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    html = (site / "_site" / "index.html").read_text()
    assert html.count('<div class="chronex-lineage">') == 3
    assert html.count("<svg") == 3
    assert html.count("Provenance ⚠ 7") == 2  # the run with mistakes; the clean run has none
    assert "no flags · 8 steps (14 runs)" in html
    assert '"step:energy"' not in html  # the graph is drawn, not shown as source
    assert (site / "_site" / "work" / "faulty" / "figures" / "energy.png").exists()
