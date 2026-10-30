"""How one input of a step is linked to the step that produced it.

No step knows about any other. Steps are linked afterwards: an input is produced by the step
that wrote a file with the same hash. Copies (collecting, staging, rsync) are therefore
transparent.

A producer must have finished before its consumer started (or be nested inside it), and one
that wrote the very path read wins. Content found only at other paths links when it has a
single original source; otherwise, or when it is too small to identify anything, the input is
ambiguous: reported, but not part of the lineage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from chronex.graph.flags import Flag
from chronex.graph.records import Record, host_of

# Content smaller than this (empty files, "{}", "ok") is too common to link across paths.
TRIVIAL_BYTES = 64


@dataclass
class Link:
    """How one input of a step was resolved."""

    producer: str | None  # id of the step that wrote this content, if any
    path: str | None  # where the producer wrote it
    origin: bool  # no step wrote this content or this path: it enters the graph here
    ambiguous: list[str] = field(default_factory=list)  # steps that wrote this content elsewhere


def enclosing(record: Record, by_id: dict[str, Record]) -> list[str]:
    """Ids of the steps a step ran inside, innermost first."""
    found: list[str] = []
    parent = record.get("parent")
    while parent in by_id and parent not in found:
        found.append(parent)
        parent = by_id[parent].get("parent")
    return found


def expand(inputs: list[dict[str, Any]], produced: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a directory input into its files, if steps wrote them one by one.

    A directory written as a whole by one step links as it is. One whose files were written
    by separate steps (`fits/` filled by one fit per dataset) links through its files. A
    directory of files no step wrote stays one origin input.
    """
    expanded = []
    for inp in inputs:
        files = inp.get("files") or {}
        if (
            inp["kind"] != "dir"
            or inp["sha"] in produced
            or not any(sha in produced for sha in files.values())
        ):
            expanded.append(inp)
            continue
        sizes = inp.get("sizes") or {}
        for rel, sha in files.items():
            expanded.append(
                {
                    "path": os.path.join(inp["path"], rel),
                    "rel": os.path.join(inp["rel"], rel),
                    "param": inp["param"],
                    "kind": "file",
                    "sha": sha,
                    "size": sizes.get(rel),
                    "how": inp["how"],
                    "directory": inp["path"],
                }
            )
    return expanded


def input_shas(record: Record) -> set[str]:
    """Hashes a step read, including the files inside input directories."""
    found = set()
    for inp in record["inputs"]:
        if inp["sha"]:
            found.add(inp["sha"])
        found.update((inp.get("files") or {}).values())
    return found


def before(producer: Record, consumer: Record) -> bool:
    """Whether a step could have written something another step read: it ended before the
    reader started, or ran inside it (a nested step ends after its enclosing step starts)."""
    if producer["id"] == consumer["id"]:
        return False
    return bool(producer["ended"] <= consumer["started"]) or consumer["id"] in producer.get(
        "_enclosing", ()
    )


def resolve(
    record: Record,
    inp: dict[str, Any],
    produced: dict[str, list[tuple[Record, str]]],
    writers: dict[tuple[str, str], list[tuple[Record, str]]],
    flags: dict[str, list[Flag]],
) -> Link:
    sid, host, sha = record["id"], host_of(record), inp["sha"]
    candidates = [(r, p) for r, p in produced.get(sha or "", []) if before(r, record)]
    same_path = [(r, p) for r, p in candidates if host_of(r) == host and p == inp["path"]]
    if same_path:
        producer, path = max(same_path, key=lambda item: item[0]["ended"])
        return Link(producer=producer["id"], path=path, origin=False)
    if candidates:
        # A step that read this content and wrote it again is a copy; copies of one original
        # are one source, and the latest copy is the producer.
        originals = {r["id"] for r, _ in candidates if sha not in input_shas(r)}
        trivial = inp["size"] is not None and inp["size"] < TRIVIAL_BYTES
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
                inp["path"],
            )
        else:
            flag = Flag(
                "warn",
                "ambiguous-input",
                f"{inp['rel']} has the same content as outputs of unrelated steps ({names}), "
                "so it is not linked",
                ambiguous,
                inp["path"],
            )
        flags[sid].append(flag)
        return Link(producer=None, path=None, origin=False, ambiguous=ambiguous)
    earlier = [
        (r, written) for r, written in writers.get((host, inp["path"]), []) if before(r, record)
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
                inp["path"],
            )
        )
        return Link(producer=None, path=None, origin=False)
    return Link(producer=None, path=None, origin=True)
