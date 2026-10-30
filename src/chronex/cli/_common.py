"""What the commands share: where records are searched for, and wording."""

from __future__ import annotations

import os

import rich_click as click

from chronex import graph as graphs

roots_argument = click.argument("roots", nargs=-1, type=click.Path(file_okay=False))


def load(roots: tuple[str, ...]) -> graphs.Graph:
    """The linked records below these directories, or below `.` if none are given."""
    return graphs.build(graphs.load(*(roots or (".",))))


def plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def files(paths: list[str], limit: int = 2) -> str:
    """A few paths, relative to here, and how many more."""
    shown = [os.path.relpath(p) for p in paths[:limit]]
    more = f" and {len(paths) - limit} more" if len(paths) > limit else ""
    return ", ".join(shown) + more
