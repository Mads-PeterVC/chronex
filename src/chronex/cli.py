"""Command line: `chronex run`, `check`, `show`, `report` and `forget`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from chronex import graph as graphs
from chronex.runner import run

COLORS = {"error": "\033[31m", "warn": "\033[33m", "info": "\033[2m"}


def _outside(graph: graphs.Graph, steps: set[str], roots: list[str]) -> int:
    """Origin inputs of these steps that lie outside the searched directories."""
    bases = [os.path.join(os.path.realpath(r), "") for r in roots]
    return sum(
        1
        for sid in steps
        for inp, link in zip(graph.records[sid]["inputs"], graph.links[sid], strict=True)
        if link.origin and not os.path.realpath(inp["path"]).startswith(tuple(bases))
    )


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _check(args: argparse.Namespace) -> int:
    graph = graphs.build(graphs.load(*args.roots))
    if args.target:
        scope: set[str] = set()
        for target in args.target:
            lineage = graph.lineage(target)
            if not lineage:
                print(f"chronex check: {graph.why_unknown(target)}", file=sys.stderr)
                return 2
            scope |= lineage
    elif args.history:
        scope = set(graph.records)
    else:
        scope = graph.current()
    found = [
        (sid, f) for sid, f in graph.all_flags() if sid in scope and (f.level != "info" or args.all)
    ]
    kept = {sid: graph.kept_by(sid) for sid in {sid for sid, _ in found}}
    links = sum(1 for sid in scope for link in graph.links[sid] if link.producer)
    origins = {
        inp["path"]
        for sid in scope
        for inp, link in zip(graph.records[sid]["inputs"], graph.links[sid], strict=True)
        if link.origin
    }
    hidden = 0 if args.history or args.target else len(graph.records) - len(scope)
    outside = _outside(graph, scope, args.roots)
    failing = ("error", "warn") if args.strict else ("error",)
    failed = any(f.level in failing for _, f in found)
    if args.json:
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
        current = "" if args.history or args.target else "current "
        steps = f"{len(scope)} {current}steps"
        if hidden:
            steps += f" ({hidden} older {_plural(hidden, 'run')} hidden, --history to show)"
        print(
            f"{steps}; {links} linked {_plural(links, 'input')}, {len(origins)} origin "
            f"{_plural(len(origins), 'file')}, {len(found)} {_plural(len(found), 'flag')}"
        )
        if outside:
            inputs = "input" if outside == 1 else "inputs"
            print(
                f"{outside} origin {inputs} outside the searched directories: "
                "their producers' records may be elsewhere"
            )
    return 1 if failed else 0


def _kept(graph: graphs.Graph, users: list[str]) -> str:
    """Why a redone step's flag is still shown: the current steps that used its output."""
    if not users:
        return ""
    names = ", ".join(sorted({graph.records[u]["name"] for u in users}))
    return (
        f" [an older run, still current because {names} used its output: re-run or forget {names}]"
    )


def _files(paths: list[str], limit: int = 2) -> str:
    shown = [os.path.relpath(p) for p in paths[:limit]]
    more = f" and {len(paths) - limit} more" if len(paths) > limit else ""
    return ", ".join(shown) + more


def _show(args: argparse.Namespace) -> int:
    """Upstream lineage of a file, as an indented tree."""
    graph = graphs.build(graphs.load(*args.roots))
    producers = graph.producers_of(args.path)
    if not producers:
        print(graph.why_unknown(args.path))
        return 2
    seen: set[str] = set()
    origins: set[str] = set()  # each named once, not under every step that read it

    def show(sid: str, depth: int) -> None:
        record = graph.records[sid]
        flags = ", ".join(f.code for f in graph.flags.get(sid, []) if f.level != "info")
        params = " ".join(f"{k}={v}" for k, v in record["params"].items() if k != "argv")
        files = (
            f"{_files([i['path'] for i in record['inputs']])} → "
            f"{_files([o['path'] for o in record['outputs']])}"
        ).strip()
        mark = " (see above)" if sid in seen else ""
        head = " ".join(part for part in (record["name"], f"[{record['status']}]", params) if part)
        print(f"{'  ' * depth}{head}  {files}{mark}" + (f"  ⚑ {flags}" if flags else ""))
        if sid in seen:
            return
        seen.add(sid)
        shown: set[str] = set()
        indent = "  " * (depth + 1)
        for inp, link in zip(record["inputs"], graph.links[sid], strict=True):
            path = os.path.relpath(inp["path"])
            if link.producer:
                if link.producer not in shown:
                    shown.add(link.producer)
                    show(link.producer, depth + 1)
            elif link.ambiguous:
                names = ", ".join(sorted({graph.records[a]["name"] for a in link.ambiguous}))
                print(f"{indent}same content as an output of {names}: {path}")
            elif link.origin and inp["path"] in origins:
                print(f"{indent}origin: {path} (see above)")
            elif link.origin:
                origins.add(inp["path"])
                print(f"{indent}origin: {path} ({(inp['sha'] or 'missing')[:10]})")
            else:
                print(f"{indent}changed without a record: {path} ({(inp['sha'] or '')[:10]})")

    for sid in producers:
        show(sid, 0)
    return 0


def _report(args: argparse.Namespace) -> int:
    from chronex.report import write_report

    graph = graphs.build(graphs.load(*args.roots))
    if not graph.producers_of(args.target):
        print(f"chronex report: {graph.why_unknown(args.target)}", file=sys.stderr)
        return 2
    out = write_report(graph, Path(args.target), Path(args.output), title=args.title)
    print(f"wrote {out}")
    return 0


def _forget(args: argparse.Namespace) -> int:
    """Move records out of the way, into `.chronex/forgotten/`, where nothing reads them."""
    graph = graphs.build(graphs.load(*(args.root or ["."])))

    def matches(wanted: str) -> set[str]:
        return {
            sid
            for sid, r in graph.records.items()
            if wanted in (sid, r["name"]) or (len(wanted) >= 8 and sid.endswith(wanted))
        }

    chosen = {sid for wanted in args.steps for sid in matches(wanted)}
    unknown = [wanted for wanted in args.steps if not matches(wanted)]
    if unknown:
        print(f"chronex forget: no record matches {', '.join(unknown)}", file=sys.stderr)
        return 2
    # Steps nested inside a forgotten step go with it.
    chosen |= {sid for sid, r in graph.records.items() if chosen & set(r["_enclosing"])}
    verb = "would forget" if args.dry_run else "forgot"
    for sid in sorted(chosen, key=lambda s: graph.records[s]["started"]):
        record = graph.records[sid]
        print(f"{verb} {record['name']} {sid[-8:]} [{record['status']}] {record['started'][:19]}")
        if not args.dry_run:
            source = Path(record["_file"])
            target = source.parent / "forgotten" / source.name
            target.parent.mkdir(exist_ok=True)
            source.rename(target)
    users = sorted(
        {
            graph.records[sid]["name"]
            for sid, links in graph.links.items()
            if sid not in chosen and any(lk.producer in chosen for lk in links)
        }
    )
    if users:
        print(f"note: {', '.join(users)} read files these steps wrote; re-run them, or forget them")
    return 0


def _run(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print(
            "chronex run: give the command after --, e.g. chronex run --in a.csv -- sort a.csv",
            file=sys.stderr,
        )
        return 2
    return run(
        command,
        inputs=args.inputs,
        outputs=args.outputs,
        watch=args.watch,
        name=args.name,
        quiet=args.quiet,
    )


def _roots(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "roots", nargs="*", default=["."], help="directories to search for records (default: .)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chronex", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a command and record it without changing its code")
    p.add_argument(
        "--in", dest="inputs", nargs="+", action="extend", default=[], help="input paths or globs"
    )
    p.add_argument(
        "--out", dest="outputs", nargs="+", action="extend", default=[], help="output paths"
    )
    p.add_argument(
        "--watch",
        nargs="+",
        action="extend",
        default=[],
        help="directories whose changes are outputs",
    )
    p.add_argument("--name", help="step name (default: the command, or the Python script)")
    p.add_argument("-q", "--quiet", action="store_true", help="do not report what was recorded")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=_run)

    p = sub.add_parser(
        "check",
        help="link the records below ROOTS and report problems",
        description="Exit code: 1 if an error is found (or a warning, with --strict), 2 if a "
        "--target has no recorded lineage, else 0.",
    )
    _roots(p)
    p.add_argument("--target", action="append", help="only the lineage of this file (repeatable)")
    p.add_argument("--history", action="store_true", help="include steps redone by later runs")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--all", action="store_true", help="include info-level notes")
    p.add_argument(
        "--json",
        action="store_true",
        help='print {"summary": {...}, "flags": [...]}: counts, and each flag with its step',
    )
    p.set_defaults(func=_check)

    p = sub.add_parser(
        "show",
        help="print the upstream lineage of a file",
        description="Exit code: 2 if no recorded step wrote the file, else 0.",
    )
    p.add_argument("path")
    _roots(p)
    p.set_defaults(func=_show)

    p = sub.add_parser(
        "report",
        help="write a self-contained HTML lineage page for a file",
        description="Exit code: 2 if no recorded step wrote the file, else 0.",
    )
    p.add_argument("target", help="the result to explain, e.g. a figure")
    _roots(p)
    p.add_argument("-o", "--output", default="lineage.html")
    p.add_argument("--title")
    p.set_defaults(func=_report)

    p = sub.add_parser(
        "forget",
        help="stop counting steps: a failed experiment, a mistaken command",
        description="Moves the records of the given steps, and of steps nested inside them, to "
        ".chronex/forgotten/. Move them back to undo.",
    )
    p.add_argument(
        "steps", nargs="+", help="a step's id (or its last 8 characters, as check shows) or name"
    )
    p.add_argument("--root", action="append", help="directory to search for records (default: .)")
    p.add_argument("-n", "--dry-run", action="store_true", help="only say what would be forgotten")
    p.set_defaults(func=_forget)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
