"""`chronex show`: the upstream lineage of a file, as an indented tree."""

from __future__ import annotations

import os

import rich_click as click

from chronex.cli._common import files, load, roots_argument
from chronex.views.dot import to_dot
from chronex.views.lineage import lineage


@click.command(
    short_help="Print the upstream lineage of a file.",
    epilog="Exit code: 2 if no recorded step wrote the file, else 0.",
)
@click.argument("path")
@roots_argument
@click.option(
    "--dot",
    "as_dot",
    is_flag=True,
    help="Print Graphviz source instead: one node per step, details in tooltips.",
)
def show(path: str, roots: tuple[str, ...], as_dot: bool) -> int:
    """Print the upstream lineage of a file, from records below ROOTS (default: .)."""
    graph = load(roots)
    producers = graph.producers_of(path)
    if not producers:
        print(graph.why_unknown(path))
        return 2
    if as_dot:
        print(to_dot(lineage(graph, path)), end="")
        return 0
    seen: set[str] = set()
    origins: set[str] = set()  # each named once, not under every step that read it

    def step(sid: str, depth: int) -> None:
        record = graph.records[sid]
        flags = ", ".join(f.code for f in graph.flags.get(sid, []) if f.level != "info")
        params = " ".join(f"{k}={v}" for k, v in record["params"].items() if k != "argv")
        edge = (
            f"{files([i['path'] for i in record['inputs']])} → "
            f"{files([o['path'] for o in record['outputs']])}"
        ).strip()
        mark = " (see above)" if sid in seen else ""
        head = " ".join(part for part in (record["name"], f"[{record['status']}]", params) if part)
        print(f"{'  ' * depth}{head}  {edge}{mark}" + (f"  ⚑ {flags}" if flags else ""))
        if sid in seen:
            return
        seen.add(sid)
        shown: set[str] = set()
        indent = "  " * (depth + 1)
        for inp, link in zip(record["inputs"], graph.links[sid], strict=True):
            rel = os.path.relpath(inp["path"])
            if link.producer:
                if link.producer not in shown:
                    shown.add(link.producer)
                    step(link.producer, depth + 1)
            elif link.ambiguous:
                names = ", ".join(sorted({graph.records[a]["name"] for a in link.ambiguous}))
                print(f"{indent}same content as an output of {names}: {rel}")
            elif link.origin and inp["path"] in origins:
                print(f"{indent}origin: {rel} (see above)")
            elif link.origin:
                origins.add(inp["path"])
                print(f"{indent}origin: {rel} ({(inp['sha'] or 'missing')[:10]})")
            else:
                print(f"{indent}changed without a record: {rel} ({(inp['sha'] or '')[:10]})")

    for sid in producers:
        step(sid, 0)
    return 0
