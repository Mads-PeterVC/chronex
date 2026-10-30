"""The HTML report of one result."""

import json
from pathlib import Path

import pytest

import chronex
from chronex.cli import main
from tests.helpers import check, make


def test_report_creates_its_directory(workdir: Path) -> None:
    make(Path("a"), "v1")
    assert main(["report", "a", ".", "-o", "deep/er/report.html"]) == 0
    html = Path("deep/er/report.html").read_text()
    assert html.startswith("<!doctype html>")
    assert "fonts.googleapis" not in html


def test_report_embeds_the_figure_and_lists_hidden_reads(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("config.json").write_text("{}")
    with chronex.step("plot") as s:
        Path("config.json").read_text()
        Path(s.output("figure.png")).write_bytes(b"\x89PNG not really")
    assert main(["report", "figure.png"]) == 0
    html = Path("lineage.html").read_text()
    data = json.loads(html.split("const D = ", 1)[1].split(";\n", 1)[0])
    assert data["image"].startswith("data:image/png;base64,")
    (act,) = data["acts"].values()
    assert act["undeclared_reads"] == ["config.json"]
    assert main(["report", "config.json"]) == 2
    assert check("--target", "config.json", capsys=capsys)[0] == 2
