"""Records as read from disk, and what every part of the graph asks of one."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from chronex.recording.step import RECORD_DIR

Record = dict[str, Any]

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


def host_of(record: Record) -> str:
    return str(record.get("env", {}).get("host", ""))


def end_of(record: Record) -> str:
    """When a step ended, or started if it never recorded an end."""
    return str(record["ended"] or record["started"])


def outputs_of(record: Record) -> list[tuple[str, str, str]]:
    """(path, sha, kind) of every output, including the files inside output directories."""
    found = []
    for out in record["outputs"]:
        if out["sha"] is None:
            continue
        found.append((out["path"], out["sha"], out["kind"]))
        for rel, sha in (out.get("files") or {}).items():
            found.append((os.path.join(out["path"], rel), sha, "file"))
    return found
