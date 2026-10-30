"""The checks run on a linked graph: the ways a chain of steps goes wrong."""

from __future__ import annotations

import os
import socket
from collections import defaultdict
from typing import Any

from chronex.graph.flags import Flag
from chronex.graph.model import Graph
from chronex.graph.records import Record, host_of, outputs_of
from chronex.hashing import identify


def check_record(
    record: Record,
    graph: Graph,
    writers: dict[tuple[str, str], list[tuple[Record, str]]],
    failed_parents: set[str],
    redone: bool,
) -> None:
    sid = record["id"]
    flags = graph.flags[sid]
    # A failure is reported where it happened, not again by every step enclosing it.
    if record["status"] == "failed" and sid not in failed_parents:
        flags.append(Flag("warn", "failed", f"step failed: {record.get('error')}"))
    elif record["status"] == "running":
        flags.append(
            Flag(
                "warn",
                "incomplete",
                "no end recorded: still running, or killed (SIGKILL, out of memory, node failure)",
            )
        )
    for inp, link in zip(record["inputs"], graph.links[sid], strict=True):
        if not link.producer:
            continue
        producer = graph.records[link.producer]
        if producer["status"] != "completed":
            flags.append(
                Flag(
                    "warn",
                    "failed-producer",
                    f"{inp['rel']} comes from a {producer['status']} run of {producer['name']}",
                    [producer["id"]],
                    inp["path"],
                )
            )
        later = [
            r
            for r, sha in writers.get((host_of(producer), link.path or ""), [])
            if sha != inp["sha"] and r["ended"] > producer["ended"]
        ]
        if later:
            newest = max(later, key=lambda r: r["ended"])
            advice = (
                f"{record['name']} has been re-run since"
                if redone
                else f"re-run {record['name']} to use the new version"
            )
            flags.append(
                Flag(
                    "warn",
                    "superseded-input",
                    f"{inp['rel']} is the version {producer['name']} wrote at "
                    f"{producer['ended'][11:19]} UTC; {newest['name']} rewrote "
                    f"{os.path.relpath(link.path or '', record['cwd'])} at "
                    f"{newest['ended'][11:19]} UTC: {advice}",
                    [producer["id"], newest["id"]],
                    inp["path"],
                )
            )
    for path in record.get("undeclared_reads", []):
        flags.append(
            Flag(
                "warn",
                "undeclared-read",
                f"read {os.path.relpath(path, record['cwd'])} without declaring it",
                path=path,
            )
        )
    for path in record.get("undeclared_writes", []):
        flags.append(
            Flag(
                "info",
                "undeclared-write",
                f"wrote {os.path.relpath(path, record['cwd'])} without declaring it",
                path=path,
            )
        )
    for path in record.get("missing_inputs", []):
        flags.append(
            Flag(
                "warn",
                "missing-input",
                f"declared input {os.path.relpath(path, record['cwd'])} did not exist",
                path=path,
            )
        )
    if record["status"] != "failed":  # a failed step's missing outputs are not news
        for path in record.get("missing_outputs", []):
            rel = os.path.relpath(path, record["cwd"])
            text = f"declared output {rel} was not written"
            flags.append(Flag("error", "missing-output", text, path=path))
    if record.get("code", {}).get("unrecorded"):
        flags.append(
            Flag(
                "warn",
                "unrecorded-code",
                f"the code was {record['code']['unrecorded']}, so it is not in the record; "
                "save it as a script, or use python -c",
            )
        )
    if record["observed"].get("workers"):
        # Declared files say what the workers used; with none, nothing does.
        if any(inp["how"] == "declared" for inp in record["inputs"]):
            level, known = "info", "is taken from the step's declarations"
        else:
            level, known = "warn", "is unknown: declare it in the step that starts them"
        flags.append(
            Flag(
                level,
                "untracked-workers",
                "started worker processes (multiprocessing, concurrent.futures, os.fork); what "
                f"they read and wrote {known}",
            )
        )
    if record["observed"]["subprocesses"]:
        commands = "; ".join(record["observed"]["subprocesses"])[:120]
        flags.append(
            Flag(
                "info",
                "subprocess",
                f"ran `{commands}`: what it read and wrote is only known from declarations",
            )
        )
    if host_of(record) == socket.gethostname():
        for out in record["outputs"]:
            if out["sha"] and os.path.exists(out["path"]):
                if _unchanged(out):
                    continue
                now = identify(out["path"])["sha"]
                if now != out["sha"]:
                    flags.append(
                        Flag(
                            "info",
                            "changed-on-disk",
                            f"{out['rel']} has changed since this step wrote it",
                            path=out["path"],
                        )
                    )


def _unchanged(out: dict[str, Any]) -> bool:
    """Whether a file output still has the size and mtime it had when hashed (no re-hash)."""
    if out["kind"] != "file" or "mtime_ns" not in out:
        return False
    stat = os.stat(out["path"])
    return bool(stat.st_size == out["size"] and stat.st_mtime_ns == out["mtime_ns"])


def check_mixed(graph: Graph, writers: dict[tuple[str, str], list[tuple[Record, str]]]) -> None:
    """Flag the step where two versions of the same file, written by re-runs, first meet."""
    memo: dict[str, dict[tuple[str, str], set[str]]] = {}

    def versions(start: str) -> dict[tuple[str, str], set[str]]:
        """Versions of each path written by this step and everything upstream of it.

        An iterative depth-first walk: chains can be long, and links that close a cycle
        (possible with equal timestamps) are skipped.
        """
        visiting: set[str] = set()
        todo = [(start, False)]
        while todo:
            sid, ready = todo.pop()
            if sid in memo or (not ready and sid in visiting):
                continue
            producers = [lk.producer for lk in graph.links[sid] if lk.producer]
            if not ready:
                visiting.add(sid)
                todo.append((sid, True))
                todo.extend((p, False) for p in producers if p not in memo and p not in visiting)
                continue
            found: dict[tuple[str, str], set[str]] = defaultdict(set)
            record = graph.records[sid]
            for path, sha, _ in outputs_of(record):
                found[host_of(record), path].add(sha)
            for p in producers:
                for key, shas in memo.get(p, {}).items():
                    found[key] |= shas
            memo[sid] = found
            visiting.discard(sid)
        return memo[start]

    for sid, record in graph.records.items():
        producers = {lk.producer for lk in graph.links[sid] if lk.producer}
        upstream: dict[tuple[str, str], set[str]] = defaultdict(set)
        for p in producers:
            for key, shas in versions(p).items():
                upstream[key] |= shas
        mixed = []
        for key, shas in upstream.items():
            if len(shas) > 1 and not any(versions(p).get(key, set()) >= shas for p in producers):
                mixed.append(key[1])
        if mixed:
            names = ", ".join(sorted(os.path.relpath(p, record["cwd"]) for p in mixed))
            flags = graph.flags[sid]
            flags.append(
                Flag(
                    "warn",
                    "mixed-lineage",
                    f"inputs descend from different versions of {names}",
                    sorted({r["id"] for m in mixed for r, _ in writers[(host_of(record), m)]}),
                )
            )
