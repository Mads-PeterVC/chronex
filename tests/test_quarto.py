"""Figures in a Quarto document: a tabset of the figure and its provenance."""

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
    text = cq.figure("figure.png", caption="A figure", label="data")
    assert capsys.readouterr().out == text + "\n"  # printed, outside a notebook
    assert text.startswith("::: {.panel-tabset}\n\n## Figure\n\n![A figure](figure.png){#fig-data}")
    assert "\n## Provenance\n" in text
    assert "```{dot}\ndigraph lineage {" in text
    assert "no flags · 1 step · 1 origin file" in text
    assert text.count("<script>") == 1
    assert "<script>" not in cq.markdown("figure.png")  # once per document


def test_flags_are_counted_in_the_tab(workdir: Path) -> None:
    plot()
    Path("hidden").write_text("x")
    with chronex.step("plot") as s:
        Path("hidden").read_text()
        Path(s.output("figure.png")).write_bytes(Path(s.input("data.csv")).read_bytes())
    text = cq.markdown("figure.png")
    assert "\n## Provenance ⚠ 1\n" in text
    assert "**1 warning** · 1 step" in text


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
