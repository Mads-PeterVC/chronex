"""Steps and helpers shared by the tests."""

import shutil
from pathlib import Path

import chronex
from chronex import In, Out
from chronex import graph as graphs


@chronex.step
def make(target: Out[Path], value: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)


@chronex.step
def copy(source: In[Path], target: Out[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


@chronex.step
def use(source: In[Path], target: Out[Path]) -> None:
    target.write_text(source.read_text() + "!")


def codes(graph: graphs.Graph) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for sid, flag in graph.all_flags():
        if flag.level != "info":
            found.setdefault(flag.code, []).append(graph.records[sid]["name"])
    return found
