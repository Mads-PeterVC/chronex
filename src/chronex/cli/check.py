"""`chronex check`: link the records and report problems, as text or JSON."""

from __future__ import annotations

import json
import os
import sys

import rich_click as click

from chronex import graph as graphs
from chronex.cli._common import load, plural, roots_argument

COLORS = {"error": "\033[31m", "warn": "\033[33m", "info": "\033[2m"}


@click.command(
    short_help="Link the records and report problems.",
    epilog="Exit code: 1 if an error is found (or a warning, with --strict), 2 if a --target "
    "has no recorded lineage, else 0.",
)
@roots_argument
@click.option(
    "--target", multiple=True, metavar="FILE", help="Only the lineage of this file (repeatable)."
)
@click.option("--history", is_flag=True, help="Include steps redone by later runs.")
@click.option("--strict", is_flag=True, help="Fail on warnings too.")
@click.option("--all", "show_all", is_flag=True, help="Include info-level notes.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help='Print {"summary": {...}, "flags": [...]}: counts, and each flag with its step.',
)
def check(
    roots: tuple[str, ...],
    target: tuple[str, ...],
    history: bool,
    strict: bool,
    show_all: bool,
    as_json: bool,
) -> int:
    """Link the records below ROOTS (default: .) and report problems."""
    roots = roots or (".",)
    graph = load(roots)
    if target:
        scope: set[str] = set()
        for path in target:
            lineage = graph.lineage(path)
            if not lineage:
                print(f"chronex check: {graph.why_unknown(path)}", file=sys.stderr)
                return 2
            scope |= lineage
    elif history:
        scope = set(graph.records)
    else:
        scope = graph.current()
    found = [
        (sid, f) for sid, f in graph.all_flags() if sid in scope and (f.level != "info" or show_all)
    ]
    kept = {sid: graph.kept_by(sid) for sid in {sid for sid, _ in found}}
    links = sum(1 for sid in scope for link in graph.links[sid] if link.producer)
    origins = {
        inp["path"]
        for sid in scope
        for inp, link in zip(graph.records[sid]["inputs"], graph.links[sid], strict=True)
        if link.origin
    }
    hidden = 0 if history or target else len(graph.records) - len(scope)
    outside = _outside(graph, scope, roots)
    failing = ("error", "warn") if strict else ("error",)
    failed = any(f.level in failing for _, f in found)
    if as_json:
        summary = {
            "steps": len(scope),
            "hidden": hidden,
            "linked_inputs": links,
            "origin_files": len(origins),
            "origins_outside_roots": outside,
            "flags": {level: sum(f.level == level for _, f in found) for level in graphs.LEVELS},
            "passed": not failed,
        }
        entries = [
            {
                "step": sid,
                "name": graph.records[sid]["name"],
                "status": graph.records[sid]["status"],
                "cwd": graph.records[sid]["cwd"],
                "record": graph.records[sid].get("_file"),
                "kept_by": kept[sid],
                **f.to_dict(),
            }
            for sid, f in found
        ]
        print(json.dumps({"summary": summary, "flags": entries}, indent=1))
    else:
        color = sys.stdout.isatty()
        for sid, flag in found:
            record = graph.records[sid]
            label = f"{flag.level:5} {flag.code:22} {record['name']:10} {sid[-8:]}"
            prefix, reset = (COLORS[flag.level], "\033[0m") if color else ("", "")
            print(f"{prefix}{label}{reset}  {flag.text}{_kept(graph, kept[sid])}")
        current = "" if history or target else "current "
        steps = f"{len(scope)} {current}steps"
        if hidden:
            steps += f" ({hidden} older {plural(hidden, 'run')} hidden, --history to show)"
        print(
            f"{steps}; {links} linked {plural(links, 'input')}, {len(origins)} origin "
            f"{plural(len(origins), 'file')}, {len(found)} {plural(len(found), 'flag')}"
        )
        if outside:
            print(
                f"{outside} origin {plural(outside, 'input')} outside the searched directories: "
                "their producers' records may be elsewhere"
            )
    return 1 if failed else 0


def _outside(graph: graphs.Graph, steps: set[str], roots: tuple[str, ...]) -> int:
    """Origin inputs of these steps that lie outside the searched directories."""
    bases = tuple(os.path.join(os.path.realpath(r), "") for r in roots)
    return sum(
        1
        for sid in steps
        for inp, link in zip(graph.records[sid]["inputs"], graph.links[sid], strict=True)
        if link.origin and not os.path.realpath(inp["path"]).startswith(bases)
    )


def _kept(graph: graphs.Graph, users: list[str]) -> str:
    """Why a redone step's flag is still shown: the current steps that used its output."""
    if not users:
        return ""
    names = ", ".join(sorted({graph.records[u]["name"] for u in users}))
    return (
        f" [an older run, still current because {names} used its output: re-run or forget {names}]"
    )
