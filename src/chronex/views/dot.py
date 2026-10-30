"""A file's lineage as a Graphviz graph: one node per step, its runs folded together.

Details (parameters across runs, code version, flags) go in each node's tooltip, so the graph
stays small enough to read at a glance.
"""

from __future__ import annotations

import os

from chronex.views.lineage import Lineage
from chronex.views.tooltip import listed, tooltip

# Fill and border per worst flag level; steps without flags are grey.
COLORS = {
    "error": ("#f8d7da", "#b02a37"),
    "warn": ("#fff3cd", "#a1660a"),
    None: ("#eef1f4", "#5a6270"),
}
FONT = "Helvetica,Arial,sans-serif"


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
            "tooltip": tooltip(name, runs, flags),
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
                    *listed(f"{p}  {sha[:10]}" for p, sha in sorted(paths.items())),
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
                    *listed(f"{p}: {why}" for p, why in sorted(paths.items())),
                ]
            ),
        }
        lines.append(f"  {_id('unlinked', name)} [{_attrs(attrs)}];")
        lines.append(f"  {_id('unlinked', name)} -> {_id('step', name)} [style=dashed];")
    for (producer, consumer), files in sorted(found.edges.items()):
        attrs = {
            "label": _edge_label(sorted(files)),
            "tooltip": "\n".join(listed(sorted(files), indent="")),
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
