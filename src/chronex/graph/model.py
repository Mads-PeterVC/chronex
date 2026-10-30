"""The linked graph of records, and the questions asked of it: lineage, what is current."""

from __future__ import annotations

import json
import os
import socket
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from chronex.graph.flags import LEVELS, Flag
from chronex.graph.records import Record, end_of, host_of
from chronex.graph.resolve import TRIVIAL_BYTES, Link, resolve
from chronex.hashing import identify


@dataclass
class Graph:
    records: dict[str, Record]
    links: dict[str, list[Link]]
    flags: dict[str, list[Flag]]
    artifacts: dict[str, dict[str, Any]]
    # Who wrote each content (sha) and each (host, path): how inputs and files are resolved.
    produced: dict[str, list[tuple[Record, str]]] = field(default_factory=dict)
    writers: dict[tuple[str, str], list[tuple[Record, str]]] = field(default_factory=dict)
    _redone: set[str] | None = field(default=None, repr=False)

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

    def redone(self) -> set[str]:
        """Steps redone by a later run.

        A step is redone when every path it wrote (or declared and did not write) was written
        again later on the same host. A step that wrote nothing is redone by a later run with
        the same name, parameters and directory.
        """
        if self._redone is not None:
            return self._redone
        writes: dict[tuple[str, str], list[str]] = defaultdict(list)
        runs: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for r in self.records.values():
            for out in r["outputs"]:
                if out["sha"]:
                    writes[host_of(r), out["path"]].append(end_of(r))
            key = (r["name"], r["cwd"], host_of(r), json.dumps(r["params"], sort_keys=True))
            runs[key].append(end_of(r))

        def redone(r: Record) -> bool:
            if r["outputs"]:
                return all(
                    any(t > end_of(r) for t in writes[host_of(r), out["path"]])
                    for out in r["outputs"]
                )
            key = (r["name"], r["cwd"], host_of(r), json.dumps(r["params"], sort_keys=True))
            return any(t > end_of(r) for t in runs[key])

        self._redone = {sid for sid, r in self.records.items() if redone(r)}
        return self._redone

    def current(self) -> set[str]:
        """Steps that still matter: those not redone by a later run, and their ancestry."""
        keep = set(self.records) - self.redone()
        for sid in list(keep):
            keep |= self.ancestry(sid)
        return keep

    def kept_by(self, step_id: str) -> list[str]:
        """The steps not redone that a redone step is still upstream of: why it is current."""
        redone = self.redone()
        if step_id not in redone:
            return []
        return sorted(
            sid for sid in self.records if sid not in redone and step_id in self.ancestry(sid)
        )

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
        link = self.locate(absolute)
        if link and link.ambiguous:
            names = ", ".join(sorted({self.records[a]["name"] for a in link.ambiguous}))
            if os.path.getsize(absolute) < TRIVIAL_BYTES:
                return f"{path} has the same content as an output of {names}, too little to link"
            return f"{path} has the same content as outputs of unrelated steps ({names})"
        host = socket.gethostname()
        wrote = [
            r
            for r in self.records.values()
            if host_of(r) == host and any(o["path"] == absolute for o in r["outputs"])
        ]
        if wrote:
            last = max(wrote, key=end_of)
            when = end_of(last)[:19].replace("T", " ")
            return f"{path} was written by {last['name']} at {when} UTC, but has changed since"
        readers = sorted(
            {
                r["name"]
                for r in self.records.values()
                if host_of(r) == host and any(i["path"] == absolute for i in r["inputs"])
            }
        )
        if readers:
            return f"no recorded step wrote {path}; it is an origin input of {', '.join(readers)}"
        return f"no recorded step wrote or read {path}"

    def locate(self, path: str | os.PathLike[str]) -> Link | None:
        """Resolve a local file as if a step read it now: by the rules inputs are linked by."""
        absolute = os.path.abspath(path)
        info = identify(absolute)
        if info["sha"] is None:
            return None
        reader: Record = {"id": "", "started": "9999", "env": {"host": socket.gethostname()}}
        read = {"path": absolute, "rel": os.fspath(path), "sha": info["sha"], "size": info["size"]}
        return resolve(reader, read, self.produced, self.writers, defaultdict(list))

    def producers_of(self, path: str | os.PathLike[str]) -> list[str]:
        """The step that wrote the current content of a local file: its latest writer, or the
        single source of a copy. Empty if none did, or if that is ambiguous."""
        link = self.locate(path)
        return [link.producer] if link and link.producer else []

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
