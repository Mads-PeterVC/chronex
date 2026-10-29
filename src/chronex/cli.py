"""Command line: ``chronex run``, ``chronex check``, ``chronex show`` and ``chronex report``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chronex import graph as graphs
from chronex.runner import run

COLORS = {"error": "\033[31m", "warn": "\033[33m", "info": "\033[2m"}


def _check(args: argparse.Namespace) -> int:
    graph = graphs.build(graphs.load(*args.roots))
    found = [(sid, f) for sid, f in graph.all_flags() if f.level != "info" or args.all]
    if args.json:
        print(json.dumps([{"step": sid, **f.to_dict()} for sid, f in found], indent=1))
    else:
        color = sys.stdout.isatty()
        for sid, flag in found:
            record = graph.records[sid]
            label = f"{flag.level:5} {flag.code:22} {record['name']:10} {sid[-8:]}"
            prefix, reset = (COLORS[flag.level], "\033[0m") if color else ("", "")
            print(f"{prefix}{label}{reset}  {flag.text}")
        steps = len(graph.records)
        links = sum(1 for v in graph.links.values() for link in v if link.producer)
        origins = sum(1 for v in graph.links.values() for link in v if link.origin)
        print(f"{steps} steps, {links} linked inputs, {origins} origin inputs, {len(found)} flags")
    return 1 if any(f.level == "error" for _, f in found) else 0


def _show(args: argparse.Namespace) -> int:
    """Upstream lineage of a file, as an indented tree."""
    graph = graphs.build(graphs.load(*args.roots))
    producers = graph.producers_of(args.path)
    if not producers:
        print(f"no recorded step wrote the current content of {args.path}")
        return 1
    seen: set[str] = set()

    def show(sid: str, depth: int) -> None:
        record = graph.records[sid]
        flags = ", ".join(f.code for f in graph.flags.get(sid, []) if f.level != "info")
        params = " ".join(f"{k}={v}" for k, v in record["params"].items() if k != "argv")
        mark = " (see above)" if sid in seen else ""
        print(
            f"{'  ' * depth}{record['name']} [{record['status']}] {params}{mark}"
            + (f"  ⚑ {flags}" if flags else "")
        )
        if sid in seen:
            return
        seen.add(sid)
        shown: set[str] = set()
        for inp, link in zip(record["inputs"], graph.links[sid], strict=True):
            if link.producer:
                if link.producer not in shown:
                    shown.add(link.producer)
                    show(link.producer, depth + 1)
            elif link.ambiguous:
                names = ", ".join(sorted({graph.records[a]["name"] for a in link.ambiguous}))
                print(f"{'  ' * (depth + 1)}same content as: {names}: {inp['rel']}")
            else:
                state = "origin" if link.origin else "UNMATCHED"
                print(f"{'  ' * (depth + 1)}{state}: {inp['rel']} ({(inp['sha'] or '')[:10]})")

    for sid in producers:
        show(sid, 0)
    return 0


def _report(args: argparse.Namespace) -> int:
    from chronex.report import write_report

    graph = graphs.build(graphs.load(*args.roots))
    out = write_report(graph, Path(args.target), Path(args.output), title=args.title)
    print(f"wrote {out}")
    return 0


def _run(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("chronex run: give a command after --", file=sys.stderr)
        return 2
    return run(
        command,
        inputs=args.inputs,
        outputs=args.outputs,
        watch=args.watch,
        name=args.name,
        quiet=args.quiet,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chronex", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a command and record it without changing its code")
    p.add_argument("--in", dest="inputs", action="append", default=[], help="input path or glob")
    p.add_argument("--out", dest="outputs", action="append", default=[], help="output path")
    p.add_argument(
        "--watch", action="append", default=[], help="directory whose changes are outputs"
    )
    p.add_argument("--name", help="step name (default: the command, or the Python script)")
    p.add_argument("-q", "--quiet", action="store_true", help="do not report what was recorded")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=_run)

    p = sub.add_parser("check", help="link the records below ROOTS and report problems")
    p.add_argument("roots", nargs="+")
    p.add_argument("--all", action="store_true", help="include info-level notes")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_check)

    p = sub.add_parser("show", help="print the upstream lineage of a file")
    p.add_argument("path")
    p.add_argument("roots", nargs="+")
    p.set_defaults(func=_show)

    p = sub.add_parser("report", help="write a self-contained HTML lineage page for a file")
    p.add_argument("target", help="the result to explain, e.g. a figure")
    p.add_argument("roots", nargs="+")
    p.add_argument("-o", "--output", default="lineage.html")
    p.add_argument("--title")
    p.set_defaults(func=_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
