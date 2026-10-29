"""Observe what a step actually touches through Python's audit hooks (PEP 578).

Every ``open()`` in the process raises an ``open`` audit event, including those inside numpy,
pandas or ASE. While a step is active, the hook files each event as a read or a write of an
absolute path. Subprocesses are noted too: what they read and write is invisible here.

Audit hooks cannot be removed, so one hook is installed per process and forwards events to
whichever observers are currently listening.
"""

from __future__ import annotations

import contextlib
import os
import sys
import sysconfig
from collections.abc import Callable
from typing import Any

from chronex import _guard

Listener = Callable[[str, str], None]  # (kind, value): kind is read, write or subprocess

_listeners: list[Listener] = []
_installed = False
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_IGNORED_SUFFIXES = (".py", ".pyc", ".pyi", ".so", ".pyd", ".pth", ".dylib")
# Files shephex keeps in <experiment>/shephex/ about the run itself.
_SHEPHEX_BOOKKEEPING = {"meta.json", "context.json", "result.pkl", "procedure.pkl", "procedure.py"}


def _ignored_roots() -> tuple[str, ...]:
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        with contextlib.suppress(KeyError):
            roots.add(sysconfig.get_path(key))
    roots.update(("/dev", "/proc", "/sys", "/etc", "/usr", "/System", "/Library"))
    return tuple(os.path.join(os.path.realpath(r), "") for r in roots if r)


_IGNORED_ROOTS = _ignored_roots()


def interesting(path: str) -> bool:
    """Whether a path is data rather than interpreter, library or system files."""
    if path.endswith(_IGNORED_SUFFIXES) or "__pycache__" in path:
        return False
    for part in (".chronex", ".cache", ".matplotlib", "site-packages", "mpl-data"):
        if f"{os.sep}{part}{os.sep}" in path:
            return False
    head, name = os.path.split(path)
    if os.path.basename(head) == "shephex" and name in _SHEPHEX_BOOKKEEPING:
        return False
    return not path.startswith(_IGNORED_ROOTS)


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not _listeners or _guard.active():
        return
    if event == "open":
        path, mode, flags = args
        if isinstance(path, int) or path is None:
            return
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = os.path.abspath(os.fspath(path))
        if not interesting(path):
            return
        if isinstance(mode, str):
            write = any(c in mode for c in "wax+")
        else:
            write = bool((flags or 0) & _WRITE_FLAGS)
        if not write and os.path.isdir(path):
            return
        kind = "write" if write else "read"
    elif event == "subprocess.Popen":
        kind, path = "subprocess", " ".join(map(str, args[1] if args[1] else [args[0]]))
    else:
        return
    with _guard.quiet():
        for listener in list(_listeners):
            listener(kind, path)


def listen(listener: Listener) -> None:
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
    _listeners.append(listener)


def unlisten(listener: Listener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)
