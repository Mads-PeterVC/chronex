"""A file's lineage grouped by step name: the runs of each step, folded together."""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from chronex.graph import Graph, Record


@dataclass
class Lineage:
    """A file's lineage, grouped by step name."""

    target: str
    base: str  # paths are shown relative to this
    steps: dict[str, list[Record]]  # name -> runs, oldest first
    producers: list[str]  # names of the steps that wrote the target
    edges: dict[tuple[str, str], set[str]]  # (producer, consumer) -> paths
    origins: dict[str, dict[str, str]]  # consumer -> {path: sha}
    unlinked: dict[str, dict[str, str]]  # consumer -> {path: why}: undeclared, changed, ambiguous
    flags: dict[str, list[tuple[str, str, str]]]  # name -> [(level, code, text)]
    commits: set[str] = field(default_factory=set)

    @property
    def runs(self) -> int:
        return sum(len(runs) for runs in self.steps.values())

    def count(self, level: str) -> int:
        return sum(1 for flags in self.flags.values() for f in flags if f[0] == level)


def lineage(graph: Graph, target: str | os.PathLike[str]) -> Lineage:
    """Group the lineage of a file by step name. Raises LookupError if no step wrote it."""
    ids = graph.lineage(target)
    if not ids:
        raise LookupError(graph.why_unknown(target))
    records = [graph.records[sid] for sid in ids]
    base = os.path.commonpath([os.path.abspath(target), *(r["cwd"] for r in records)])
    if os.path.isfile(base):
        base = os.path.dirname(base)

    def rel(path: str) -> str:
        return os.path.relpath(path, base)

    steps: dict[str, list[Record]] = defaultdict(list)
    for r in sorted(records, key=lambda r: r["started"]):
        steps[r["name"]].append(r)
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    origins: dict[str, dict[str, str]] = defaultdict(dict)
    unlinked: dict[str, dict[str, str]] = defaultdict(dict)
    flags: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    commits = set()
    for r in records:
        name = r["name"]
        for inp, link in zip(r["inputs"], graph.links[r["id"]], strict=True):
            if link.producer in ids:
                edges[graph.records[link.producer]["name"], name].add(rel(link.path or ""))
            elif link.origin:
                origins[name][rel(inp["path"])] = inp["sha"] or "missing"
            elif link.ambiguous:
                unlinked[name][rel(inp["path"])] = "same content as unrelated outputs"
            else:
                unlinked[name][rel(inp["path"])] = "changed without a record"
        for path in r.get("undeclared_reads", []):
            unlinked[name][rel(path)] = "read without being declared"
        for flag in graph.flags.get(r["id"], []):
            entry = (flag.level, flag.code, flag.text)
            if flag.level != "info" and entry not in flags[name]:
                flags[name].append(entry)
        commits |= {commit(g) for g in r["code"]["git"]}
    return Lineage(
        target=rel(os.path.abspath(target)),
        base=base,
        steps=dict(steps),
        producers=sorted({graph.records[sid]["name"] for sid in graph.producers_of(target)}),
        edges=dict(edges),
        origins=dict(origins),
        unlinked=dict(unlinked),
        flags=dict(flags),
        commits=commits,
    )


def commit(state: dict[str, Any]) -> str:
    commit = (state.get("commit") or "no commit")[:7]
    return commit + ("*" if state.get("dirty") else "")
