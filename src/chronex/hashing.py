"""Content identity of files and directories.

A file is identified by its SHA-256. A directory is identified by the SHA-256 of the sorted
list of its files' relative paths and hashes, so two copies of a directory tree share an
identity no matter where they live.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from chronex import _guard

_CHUNK = 1 << 20
# (path, size, mtime_ns) -> sha256, for this process. Records hash the same input many times
# within one process (fan-out loops), so even a process-local cache pays off.
_cache: dict[tuple[str, int, int], str] = {}


def file_sha256(path: str | os.PathLike[str]) -> str:
    """SHA-256 of a file, cached on (path, size, mtime) for the lifetime of the process."""
    path = os.fspath(path)
    stat = os.stat(path)
    key = (path, stat.st_size, stat.st_mtime_ns)
    if key in _cache:
        return _cache[key]
    digest = hashlib.sha256()
    with _guard.quiet(), open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    _cache[key] = digest.hexdigest()
    return _cache[key]


MAX_LISTED_FILES = 2000


def tree_sha256(path: str | os.PathLike[str]) -> tuple[str, int, dict[str, str]]:
    """Identity, total size and per-file hashes of a directory tree (``.chronex`` excluded)."""
    root = Path(path)
    files = {}
    size = 0
    for file in sorted(p for p in root.rglob("*") if p.is_file() and ".chronex" not in p.parts):
        files[file.relative_to(root).as_posix()] = file_sha256(file)
        size += file.stat().st_size
    lines = "\n".join(f"{rel}\0{sha}" for rel, sha in files.items())
    return hashlib.sha256(lines.encode()).hexdigest(), size, files


def identify(path: str | os.PathLike[str]) -> dict[str, object]:
    """Kind, hash and size of a file or directory, or ``kind: missing``.

    Directories also list their files' hashes (up to ``MAX_LISTED_FILES``), so a later step
    reading one file of an output directory still links to the step that wrote the directory.
    """
    p = Path(path)
    if p.is_file():
        stat = p.stat()
        return {
            "kind": "file",
            "sha": file_sha256(p),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    if p.is_dir():
        sha, size, files = tree_sha256(p)
        entry: dict[str, object] = {"kind": "dir", "sha": sha, "size": size}
        if len(files) <= MAX_LISTED_FILES:
            entry["files"] = files
        return entry
    return {"kind": "missing", "sha": None, "size": None}
