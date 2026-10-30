"""`chronex report`: a self-contained HTML page explaining one result."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from chronex.cli._common import load, roots_argument


@click.command(
    short_help="Write a self-contained HTML lineage page for a file.",
    epilog="Exit code: 2 if no recorded step wrote the file, else 0.",
)
@click.argument("target")
@roots_argument
@click.option(
    "-o", "--output", default="lineage.html", show_default=True, help="Where to write the page."
)
@click.option("--title", help="The page's title (default: the target's name).")
def report(target: str, roots: tuple[str, ...], output: str, title: str | None) -> int:
    """Write a self-contained HTML lineage page for TARGET, e.g. a figure, from records below
    ROOTS (default: .)."""
    from chronex.report import write_report

    graph = load(roots)
    if not graph.producers_of(target):
        print(f"chronex report: {graph.why_unknown(target)}", file=sys.stderr)
        return 2
    out = write_report(graph, Path(target), Path(output), title=title)
    print(f"wrote {out}")
    return 0
