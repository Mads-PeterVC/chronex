"""The HTML report of one result."""

from pathlib import Path

from tests.helpers import make


def test_report_creates_its_directory(workdir: Path) -> None:
    from chronex.cli import main

    make(Path("a"), "v1")
    assert main(["report", "a", ".", "-o", "deep/er/report.html"]) == 0
    html = Path("deep/er/report.html").read_text()
    assert html.startswith("<!doctype html>")
    assert "fonts.googleapis" not in html
