"""A file's lineage as a Graphviz graph: one node per step, its runs folded together.

Details (parameters across runs, code version, flags) go in each node's tooltip, so the graph
stays small enough to read at a glance.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from chronex.graph import Graph, Record

# Fill and border per worst flag level; steps without flags are grey.
COLORS = {
    "error": ("#f8d7da", "#b02a37"),
    "warn": ("#fff3cd", "#a1660a"),
    None: ("#eef1f4", "#5a6270"),
}
FONT = "Helvetica,Arial,sans-serif"
MAX_LISTED = 8  # tooltip lines of one kind before "and N more"


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
        commits |= {_commit(g) for g in r["code"]["git"]}
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


def to_dot(found: Lineage) -> str:
    """Graphviz source for a lineage: origins at the top, the target at the bottom."""
    lines = [
        "digraph lineage {",
        "  rankdir=TB;",
        f'  graph [fontname="{FONT}", nodesep=0.35, ranksep=0.45];',
        f'  node [fontname="{FONT}", fontsize=11, shape=box, style="rounded,filled", '
        'penwidth=1.2, href="#"];',
        f'  edge [fontname="{FONT}", fontsize=9, color="#7a828c", fontcolor="#5a6270"];',
    ]
    for name in sorted(found.steps):
        runs = found.steps[name]
        flags = found.flags.get(name, [])
        worst = next((lvl for lvl in ("error", "warn") if any(f[0] == lvl for f in flags)), None)
        fill, border = COLORS[worst]
        style = "rounded,filled" + (
            ",dashed" if any(r["status"] != "completed" for r in runs) else ""
        )
        label = name + (f" ×{len(runs)}" if len(runs) > 1 else "")
        attrs = {
            "label": label,
            "fillcolor": fill,
            "color": border,
            "style": style,
            "tooltip": _tooltip(name, runs, flags),
        }
        lines.append(f"  {_id('step', name)} [{_attrs(attrs)}];")
    for name in sorted(found.origins):
        paths = found.origins[name]
        attrs = {
            "label": _one_or_count(paths, "origin file"),
            "shape": "note",
            "style": "filled",
            "fillcolor": "#ffffff",
            "color": "#9aa1a9",
            "fontsize": "9",
            "tooltip": "\n".join(
                [
                    "Origin inputs (no recorded step wrote them):",
                    *_listed(f"{p}  {sha[:10]}" for p, sha in sorted(paths.items())),
                ]
            ),
        }
        lines.append(f"  {_id('origin', name)} [{_attrs(attrs)}];")
        lines.append(f"  {_id('origin', name)} -> {_id('step', name)} [style=dashed];")
    for name in sorted(found.unlinked):
        paths = found.unlinked[name]
        fill, border = COLORS["warn"]
        attrs = {
            "label": _one_or_count(paths, "unrecorded input"),
            "shape": "note",
            "style": "filled",
            "fillcolor": fill,
            "color": border,
            "fontsize": "9",
            "tooltip": "\n".join(
                [
                    "Inputs whose source is not recorded:",
                    *_listed(f"{p}: {why}" for p, why in sorted(paths.items())),
                ]
            ),
        }
        lines.append(f"  {_id('unlinked', name)} [{_attrs(attrs)}];")
        lines.append(f"  {_id('unlinked', name)} -> {_id('step', name)} [style=dashed];")
    for (producer, consumer), files in sorted(found.edges.items()):
        attrs = {
            "label": _edge_label(sorted(files)),
            "tooltip": "\n".join(_listed(sorted(files))),
        }
        lines.append(f"  {_id('step', producer)} -> {_id('step', consumer)} [{_attrs(attrs)}];")
    target = _id("file", found.target)
    attrs = {
        "label": found.target,
        "style": "filled",
        "fillcolor": "#ffffff",
        "color": "#2f343a",
        "penwidth": "1.6",
        "tooltip": found.target,
    }
    lines.append(f"  {target} [{_attrs(attrs)}];")
    for name in found.producers:
        lines.append(f"  {_id('step', name)} -> {target};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _tooltip(name: str, runs: list[Record], flags: list[tuple[str, str, str]]) -> str:
    statuses: dict[str, int] = defaultdict(int)
    for r in runs:
        statuses[r["status"]] += 1
    counts = ", ".join(f"{n} {status}" for status, n in sorted(statuses.items()))
    runs_text = "1 run" if len(runs) == 1 else f"{len(runs)} runs"
    lines = [f"{name}: {runs_text} ({counts})"]
    for key, value in _params(runs).items():
        lines.append(f"{key} = {value}")
    commits = sorted({_commit(g) for r in runs for g in r["code"]["git"]})
    if commits:
        lines.append("code: " + ", ".join(commits))
    elif any(r["code"]["files"] for r in runs):
        lines.append("code: not in git (only file hashes recorded)")
    hosts = sorted({str(r["env"]["host"]) for r in runs})
    lines.append(
        "host: " + ", ".join(hosts[:3]) + (f" and {len(hosts) - 3} more" if len(hosts) > 3 else "")
    )
    lines.append("ran: " + _span(runs))
    for r in runs:
        if r.get("error"):
            lines.append(f"error: {r['error']}")
            break
    if flags:
        lines.append("flags:")
        lines += _listed(f"{level} {code}: {text}" for level, code, text in flags)
    return "\n".join(lines)


def _params(runs: list[Record]) -> dict[str, str]:
    """Each parameter's value, or its range or set of values across runs."""
    found: dict[str, list[Any]] = defaultdict(list)
    for r in runs:
        for key, value in r["params"].items():
            found[key].append(value)
    shown = {}
    for key, values in found.items():
        if key == "argv":
            key, values = "command", [" ".join(map(str, v)) for v in values]
        distinct = sorted({json.dumps(v, sort_keys=True) for v in values})
        if len(distinct) == 1:
            shown[key] = _short(values[0])
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            shown[key] = f"{min(values):g}–{max(values):g} ({len(distinct)} values)"
        else:
            listed = [_short(json.loads(v)) for v in distinct[:4]]
            more = f" and {len(distinct) - 4} more" if len(distinct) > 4 else ""
            shown[key] = ", ".join(listed) + more
    return shown


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _commit(state: dict[str, Any]) -> str:
    commit = (state.get("commit") or "no commit")[:7]
    return commit + ("*" if state.get("dirty") else "")


def _span(runs: list[Record]) -> str:
    start = min(r["started"] for r in runs)
    end = max(r["ended"] or r["started"] for r in runs)
    first = dt.datetime.fromisoformat(start)
    last = dt.datetime.fromisoformat(end)
    if first.date() == last.date():
        return f"{first:%Y-%m-%d %H:%M}–{last:%H:%M} UTC"
    return f"{first:%Y-%m-%d %H:%M} – {last:%Y-%m-%d %H:%M} UTC"


def _listed(lines: Any) -> list[str]:
    lines = list(lines)
    shown = [f"  {line}" for line in lines[:MAX_LISTED]]
    if len(lines) > MAX_LISTED:
        shown.append(f"  and {len(lines) - MAX_LISTED} more")
    return shown


def _one_or_count(paths: dict[str, str], word: str) -> str:
    return next(iter(paths)) if len(paths) == 1 else f"{len(paths)} {word}s"


def _edge_label(paths: list[str]) -> str:
    if len(paths) <= 2:
        return "\n".join(paths)
    directory = os.path.commonpath(paths) if all(paths) else ""
    where = f" in {directory}/" if directory and directory not in paths else ""
    return f"{len(paths)} files{where}"


def _id(kind: str, name: str) -> str:
    return _quote(f"{kind}:{name}")


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _attrs(attrs: dict[str, str]) -> str:
    parts = []
    for key, value in attrs.items():
        if key == "tooltip":  # a newline in a tooltip is an XML character reference
            value = value.replace("&", "&amp;").replace("\n", "&#10;")
        quoted = _quote(value)
        if key == "label":  # and in a label, an escape
            quoted = quoted.replace("\n", "\\n")
        parts.append(f"{key}={quoted}")
    return ", ".join(parts)
