"""Build the graph: link every input of every record, then run the checks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from chronex.graph.checks import check_mixed, check_record
from chronex.graph.flags import Flag
from chronex.graph.model import Graph
from chronex.graph.records import Record, host_of, outputs_of
from chronex.graph.resolve import Link, enclosing, expand, resolve


def build(records: list[Record]) -> Graph:
    by_id = {r["id"]: r for r in records}
    artifacts: dict[str, dict[str, Any]] = {}
    produced: dict[str, list[tuple[Record, str]]] = defaultdict(list)
    writers: dict[tuple[str, str], list[tuple[Record, str]]] = defaultdict(list)

    def locate(sha: str, size: Any, kind: str, path: str, role: str, step: str) -> None:
        entry = artifacts.setdefault(sha, {"sha": sha, "size": size, "kind": kind, "locations": []})
        location = {"path": path, "role": role, "step": step}
        if location not in entry["locations"]:
            entry["locations"].append(location)

    for record in records:
        record["_enclosing"] = enclosing(record, by_id)
        for path, sha, kind in outputs_of(record):
            produced[sha].append((record, path))
            writers[host_of(record), path].append((record, sha))
            locate(sha, None, kind, path, "output", record["id"])
        for out in record["outputs"]:
            if out["sha"]:
                artifacts[out["sha"]]["size"] = out["size"]
    for record in records:
        record["inputs"] = expand(record["inputs"], produced)
        for inp in record["inputs"]:
            if inp["sha"]:
                locate(inp["sha"], inp["size"], inp["kind"], inp["path"], "input", record["id"])

    links: dict[str, list[Link]] = {}
    flags: dict[str, list[Flag]] = defaultdict(list)
    for record in records:
        links[record["id"]] = [
            resolve(record, inp, produced, writers, flags) for inp in record["inputs"]
        ]

    graph = Graph(
        records=by_id,
        links=links,
        flags=flags,
        artifacts=artifacts,
        produced=produced,
        writers=writers,
    )
    failed_parents = {r["parent"] for r in records if r["status"] == "failed" and r["parent"]}
    redone = graph.redone()
    for record in records:
        check_record(record, graph, writers, failed_parents, record["id"] in redone)
    check_mixed(graph, writers)
    return graph
