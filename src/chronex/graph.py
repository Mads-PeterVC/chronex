"""Link records into a lineage graph and check it.

No step knows about any other. Steps are linked afterwards: an input is produced by the step
that wrote a file with the same hash. Copies (collecting, staging, rsync) are therefore
transparent, and the checks below look for the ways a chain of steps goes wrong.

A producer must have finished before its consumer started, and one that wrote the very path
read wins. Content found only at other paths links when it has a single original source;
otherwise, or when it is too small to identify anything, the input is ambiguous: reported, but
not part of the lineage.
"""

from __future__ import annotations

import json
import os
import socket
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chronex.hashing import identify
from chronex.record import RECORD_DIR

Record = dict[str, Any]

LEVELS = ("error", "warn", "info")
# Content smaller than this (empty files, "{}", "ok") is too common to link across paths.
TRIVIAL_BYTES = 64


@dataclass
class Flag:
    level: str  # error, warn or info
    code: str
    text: str
    refs: list[str] = field(default_factory=list)  # ids of related steps

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "code": self.code, "text": self.text, "refs": self.refs}


@dataclass
class Link:
    """How one input of a step was resolved."""

    producer: str | None  # id of the step that wrote this content, if any
    path: str | None  # where the producer wrote it
    origin: bool  # no step wrote this content or this path: it enters the graph here
    ambiguous: list[str] = field(default_factory=list)  # steps that wrote this content elsewhere


@dataclass
class Graph:
    records: dict[str, Record]
    links: dict[str, list[Link]]
    flags: dict[str, list[Flag]]
    artifacts: dict[str, dict[str, Any]]

    def ancestry(self, step_id: str) -> set[str]:
        seen: set[str] = set()
        todo = [step_id]
        while todo:
            current = todo.pop()
            for link in self.links.get(current, []):
                if link.producer and link.producer not in seen:
                    seen.add(link.producer)
                    todo.append(link.producer)
        return seen

    def current(self) -> set[str]:
        """Steps that still matter: those not redone by a later run, and their ancestry.

        A step is redone when every path it wrote (or declared and did not write) was written
        again later on the same host. A step that wrote nothing is redone by a later run with
        the same name, parameters and directory.
        """
        writes: dict[tuple[str, str], list[str]] = defaultdict(list)
        runs: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for r in self.records.values():
            for out in r["outputs"]:
                if out["sha"]:
                    writes[_host(r), out["path"]].append(_end(r))
            key = (r["name"], r["cwd"], _host(r), json.dumps(r["params"], sort_keys=True))
            runs[key].append(_end(r))

        def redone(r: Record) -> bool:
            if r["outputs"]:
                return all(
                    any(t > _end(r) for t in writes[_host(r), out["path"]]) for out in r["outputs"]
                )
            key = (r["name"], r["cwd"], _host(r), json.dumps(r["params"], sort_keys=True))
            return any(t > _end(r) for t in runs[key])

        keep = {sid for sid, r in self.records.items() if not redone(r)}
        for sid in list(keep):
            keep |= self.ancestry(sid)
        return keep

    def lineage(self, path: str | os.PathLike[str]) -> set[str]:
        """The steps that wrote the current content of a file, and their ancestry."""
        found = set(self.producers_of(path))
        for sid in list(found):
            found |= self.ancestry(sid)
        return found

    def why_unknown(self, path: str | os.PathLike[str]) -> str:
        """Why no recorded step wrote the current content of a file."""
        absolute = os.path.abspath(path)
        if not os.path.exists(absolute):
            return f"{path} does not exist"
        host = socket.gethostname()
        wrote = [
            r
            for r in self.records.values()
            if _host(r) == host and any(o["path"] == absolute for o in r["outputs"])
        ]
        if wrote:
            last = max(wrote, key=_end)
            when = _end(last)[:19].replace("T", " ")
            return f"{path} was written by {last['name']} at {when} UTC, but has changed since"
        readers = sorted(
            {
                r["name"]
                for r in self.records.values()
                if _host(r) == host and any(i["path"] == absolute for i in r["inputs"])
            }
        )
        if readers:
            return f"no recorded step wrote {path}; it is an origin input of {', '.join(readers)}"
        return f"no recorded step wrote or read {path}"

    def producers_of(self, path: str | os.PathLike[str]) -> list[str]:
        """Steps that wrote the current content of a local file."""
        info = identify(path)
        entry = self.artifacts.get(str(info["sha"]))
        return (
            sorted({loc["step"] for loc in entry["locations"] if loc["role"] == "output"})
            if entry
            else []
        )

    def all_flags(self) -> list[tuple[str, Flag]]:
        order = {level: i for i, level in enumerate(LEVELS)}
        found = [(sid, f) for sid, flags in self.flags.items() for f in flags]
        return sorted(found, key=lambda x: (order[x[1].level], self.records[x[0]]["started"]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "links": {
                k: [
                    {
                        "producer": lk.producer,
                        "path": lk.path,
                        "origin": lk.origin,
                        "ambiguous": lk.ambiguous,
                    }
                    for lk in v
                ]
                for k, v in self.links.items()
            },
            "flags": {k: [f.to_dict() for f in v] for k, v in self.flags.items()},
            "artifacts": self.artifacts,
        }


# Directories that never hold a step's records, and can be large.
_SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".tox"}


def load(*roots: str | os.PathLike[str]) -> list[Record]:
    """Every record below the given directories."""
    records = []
    for root in roots:
        for directory, subdirs, _ in os.walk(root):
            subdirs[:] = sorted(d for d in subdirs if d not in _SKIPPED_DIRS)
            if RECORD_DIR not in subdirs:
                continue
            subdirs.remove(RECORD_DIR)
            for path in sorted(Path(directory, RECORD_DIR).glob("*.json")):
                record = json.loads(path.read_text())
                if record.get("schema", "").startswith("chronex/"):
                    record["_file"] = str(path)
                    records.append(record)
    return records


def _host(record: Record) -> str:
    return str(record.get("env", {}).get("host", ""))


def _end(record: Record) -> str:
    """When a step ended, or started if it never recorded an end."""
    return str(record["ended"] or record["started"])


def _outputs(record: Record) -> list[tuple[str, str, str]]:
    """(path, sha, kind) of every output, including the files inside output directories."""
    found = []
    for out in record["outputs"]:
        if out["sha"] is None:
            continue
        found.append((out["path"], out["sha"], out["kind"]))
        for rel, sha in (out.get("files") or {}).items():
            found.append((os.path.join(out["path"], rel), sha, "file"))
    return found


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
        for path, sha, kind in _outputs(record):
            produced[sha].append((record, path))
            writers[_host(record), path].append((record, sha))
            locate(sha, None, kind, path, "output", record["id"])
        for out in record["outputs"]:
            if out["sha"]:
                artifacts[out["sha"]]["size"] = out["size"]
        for inp in record["inputs"]:
            if inp["sha"]:
                locate(inp["sha"], inp["size"], inp["kind"], inp["path"], "input", record["id"])

    links: dict[str, list[Link]] = {}
    flags: dict[str, list[Flag]] = defaultdict(list)
    for record in records:
        links[record["id"]] = [
            _resolve(record, inp, produced, writers, flags) for inp in record["inputs"]
        ]

    graph = Graph(records=by_id, links=links, flags=flags, artifacts=artifacts)
    failed_parents = {r["parent"] for r in records if r["status"] == "failed" and r["parent"]}
    for record in records:
        _check_record(record, graph, writers, failed_parents)
    _check_mixed(graph, writers)
    return graph


def _input_shas(record: Record) -> set[str]:
    """Hashes a step read, including the files inside input directories."""
    found = set()
    for inp in record["inputs"]:
        if inp["sha"]:
            found.add(inp["sha"])
        found.update((inp.get("files") or {}).values())
    return found


def _resolve(
    record: Record,
    inp: dict[str, Any],
    produced: dict[str, list[tuple[Record, str]]],
    writers: dict[tuple[str, str], list[tuple[Record, str]]],
    flags: dict[str, list[Flag]],
) -> Link:
    sid, started, host, sha = record["id"], record["started"], _host(record), inp["sha"]
    candidates = [
        (r, p) for r, p in produced.get(sha or "", []) if r["id"] != sid and r["ended"] <= started
    ]
    same_path = [(r, p) for r, p in candidates if _host(r) == host and p == inp["path"]]
    if same_path:
        producer, path = max(same_path, key=lambda item: item[0]["ended"])
        return Link(producer=producer["id"], path=path, origin=False)
    if candidates:
        # A step that read this content and wrote it again is a copy; copies of one original
        # are one source, and the latest copy is the producer.
        originals = {r["id"] for r, _ in candidates if sha not in _input_shas(r)}
        trivial = (inp["size"] or 0) < TRIVIAL_BYTES
        if len(originals) <= 1 and not trivial:
            producer, path = max(candidates, key=lambda item: item[0]["ended"])
            return Link(producer=producer["id"], path=path, origin=False)
        ambiguous = sorted({r["id"] for r, _ in candidates})
        names = ", ".join(sorted({r["name"] for r, _ in candidates}))
        if trivial:
            flag = Flag(
                "info",
                "ambiguous-input",
                f"{inp['rel']} ({inp['size']} bytes) has the same content as an output of "
                f"{names}, too little to link by content",
                ambiguous,
            )
        else:
            flag = Flag(
                "warn",
                "ambiguous-input",
                f"{inp['rel']} has the same content as outputs of unrelated steps ({names}); "
                "not linked to either",
                ambiguous,
            )
        flags[sid].append(flag)
        return Link(producer=None, path=None, origin=False, ambiguous=ambiguous)
    earlier = [
        (r, written)
        for r, written in writers.get((host, inp["path"]), [])
        if r["id"] != sid and r["ended"] <= started
    ]
    if earlier and sha:
        writer, written = max(earlier, key=lambda item: item[0]["ended"])
        flags[sid].append(
            Flag(
                "error",
                "modified-after-write",
                f"{inp['rel']} differs from what {writer['name']} wrote there "
                f"({written[:10]}… then, {sha[:10]}… when read): changed without a record",
                [writer["id"]],
            )
        )
        return Link(producer=None, path=None, origin=False)
    return Link(producer=None, path=None, origin=True)


def _check_record(
    record: Record,
    graph: Graph,
    writers: dict[tuple[str, str], list[tuple[Record, str]]],
    failed_parents: set[str],
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
                )
            )
        later = [
            r
            for r, sha in writers.get((_host(producer), link.path or ""), [])
            if sha != inp["sha"] and r["ended"] > producer["ended"]
        ]
        if later:
            newest = max(later, key=lambda r: r["ended"])
            flags.append(
                Flag(
                    "warn",
                    "superseded-input",
                    f"{inp['rel']} is the version {producer['name']} wrote at "
                    f"{producer['ended'][11:19]} UTC; {newest['name']} rewrote "
                    f"{os.path.basename(link.path or '')} at {newest['ended'][11:19]} UTC",
                    [producer["id"], newest["id"]],
                )
            )
    for path in record.get("undeclared_reads", []):
        flags.append(
            Flag(
                "warn",
                "undeclared-read",
                f"read {os.path.relpath(path, record['cwd'])} without declaring it",
            )
        )
    for path in record.get("undeclared_writes", []):
        flags.append(
            Flag(
                "info",
                "undeclared-write",
                f"wrote {os.path.relpath(path, record['cwd'])} without declaring it",
            )
        )
    for path in record.get("missing_inputs", []):
        flags.append(
            Flag(
                "warn",
                "missing-input",
                f"declared input {os.path.relpath(path, record['cwd'])} did not exist",
            )
        )
    if record["status"] != "failed":  # a failed step's missing outputs are not news
        for path in record.get("missing_outputs", []):
            rel = os.path.relpath(path, record["cwd"])
            flags.append(Flag("error", "missing-output", f"declared output {rel} was not written"))
    if record["observed"].get("workers"):
        flags.append(
            Flag(
                "warn",
                "untracked-workers",
                f"started {record['observed']['workers']} worker process(es); what they read "
                "and wrote is only known from declarations",
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
    if _host(record) == socket.gethostname():
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
                        )
                    )


def _unchanged(out: dict[str, Any]) -> bool:
    """Whether a file output still has the size and mtime it had when hashed (no re-hash)."""
    if out["kind"] != "file" or "mtime_ns" not in out:
        return False
    stat = os.stat(out["path"])
    return bool(stat.st_size == out["size"] and stat.st_mtime_ns == out["mtime_ns"])


def _check_mixed(graph: Graph, writers: dict[tuple[str, str], list[tuple[Record, str]]]) -> None:
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
            for path, sha, _ in _outputs(record):
                found[_host(record), path].add(sha)
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
                    sorted({r["id"] for m in mixed for r, _ in writers[(_host(record), m)]}),
                )
            )
