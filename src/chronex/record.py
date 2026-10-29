"""A step: one execution of some code, with what it read, wrote, ran and where.

Each finished step is written as one JSON file to ``.chronex/`` in the directory the step ran
in, so records travel with the outputs (rsync, ``hex remote pull``) and a tree of results can
be indexed later without any server.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from chronex import _guard, audit
from chronex.capture import code_identity, environment
from chronex.hashing import identify

SCHEMA = "chronex/0"
RECORD_DIR = ".chronex"

_stack: list[Step] = []


def current() -> Step | None:
    """The innermost active step, if any."""
    return _stack[-1] if _stack else None


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):  # numpy scalars and small arrays
        try:
            return _jsonable(value.tolist())
        except Exception:  # pragma: no cover
            pass
    return repr(value)


class Step:
    """Collects one step's provenance; use through ``chronex.step`` or ``chronex.track``.

    Parameters
    ----------
    name
        What the step is, e.g. ``fit``. Runs of the same step share the name.
    params
        Parameters that are not files.
    kind
        ``function``, ``block``, ``script`` or ``command``: which API produced the record.
    auto
        Treat every observed read as an input and every observed write as an output
        (zero-touch mode) instead of reporting them as undeclared.
    """

    def __init__(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        kind: str = "block",
        auto: bool = False,
        function_file: str | None = None,
        function: str | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.auto = auto
        self.id = f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}-{name}-{uuid.uuid4().hex[:8]}"
        self.params = _jsonable(params or {})
        self.function_file = function_file
        self.function = function
        self.inputs: list[dict[str, Any]] = []
        self.outputs: list[dict[str, Any]] = []
        self._declared_outputs: list[tuple[str, str | None]] = []
        self.reads: dict[str, None] = {}
        self.writes: dict[str, None] = {}
        self.subprocesses: list[str] = []
        self.status = "running"
        self.error: str | None = None
        self.cwd = os.getcwd()
        enclosing = current()
        self.parent = enclosing.id if enclosing else os.environ.get("CHRONEX_PARENT")
        self.started = _now()
        self.path: Path | None = None
        self._open = False

    # -- declaring files -------------------------------------------------------------------

    def input(self, path: str | os.PathLike[str], param: str | None = None) -> Any:
        """Declare ``path`` as an input; it is hashed now. Returns ``path`` unchanged."""
        absolute = os.path.abspath(os.fspath(path))
        entry: dict[str, Any] = {
            "path": absolute,
            "rel": os.path.relpath(absolute, self.cwd),
            "param": param,
        }
        entry.update(identify(absolute))
        entry["how"] = "declared"
        self.inputs.append(entry)
        return path

    def output(self, path: str | os.PathLike[str], param: str | None = None) -> Any:
        """Declare ``path`` as an output; it is hashed when the step ends. Returns ``path``."""
        absolute = os.path.abspath(os.fspath(path))
        if all(absolute != p for p, _ in self._declared_outputs):
            self._declared_outputs.append((absolute, param))
        return path

    # -- lifecycle -------------------------------------------------------------------------

    def _listen(self, kind: str, value: str) -> None:
        if current() is not self:
            return
        if kind == "read":
            self.reads.setdefault(value)
        elif kind == "write":
            self.writes.setdefault(value)
        else:
            self.subprocesses.append(value)

    def start(self) -> Step:
        _stack.append(self)
        audit.listen(self._listen)
        self._open = True
        return self

    def finish(self, error: BaseException | None = None) -> Path:
        if not self._open:
            raise RuntimeError(f"step {self.name} is not running")
        self._open = False
        audit.unlisten(self._listen)
        if _stack and _stack[-1] is self:
            _stack.pop()
        if error is not None:
            self.status = "failed"
            self.error = "".join(traceback.format_exception_only(type(error), error)).strip()
        elif self.status == "running":
            self.status = "completed"
        return self._write()

    def __enter__(self) -> Step:
        return self.start()

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.finish(exc)

    # -- writing ---------------------------------------------------------------------------

    def _settle(self) -> dict[str, Any]:
        declared_in = {i["path"] for i in self.inputs}
        written = set(self.writes)
        # Outputs: declared ones, plus (auto mode) everything written.
        outputs = list(self._declared_outputs)
        if self.auto:
            outputs += [(p, None) for p in self.writes if p not in {o for o, _ in outputs}]
        for path, param in outputs:
            entry: dict[str, Any] = {
                "path": path,
                "rel": os.path.relpath(path, self.cwd),
                "param": param,
            }
            entry.update(identify(path))
            entry["how"] = "declared" if (path, param) in self._declared_outputs else "observed"
            self.outputs.append(entry)
        declared_out = {o["path"] for o in self.outputs}

        def covered(path: str, roots: set[str]) -> bool:
            return any(path == r or path.startswith(os.path.join(r, "")) for r in roots)

        # Reads of files the step wrote itself are not inputs.
        reads = [p for p in self.reads if p not in written and os.path.isfile(p)]
        undeclared_reads = [p for p in reads if not covered(p, declared_in)]
        if self.auto:
            for path in undeclared_reads:
                observed: dict[str, Any] = {
                    "path": path,
                    "rel": os.path.relpath(path, self.cwd),
                    "param": None,
                }
                observed.update(identify(path))
                observed["how"] = "observed"
                self.inputs.append(observed)
            undeclared_reads = []
        undeclared_writes = [p for p in written if not covered(p, declared_out)]
        return {
            "undeclared_reads": undeclared_reads,
            "undeclared_writes": undeclared_writes,
            "missing_outputs": [o["path"] for o in self.outputs if o["kind"] == "missing"],
        }

    def _write(self) -> Path:
        with _guard.quiet():
            checks = self._settle()
            record = {
                "schema": SCHEMA,
                "id": self.id,
                "name": self.name,
                "kind": self.kind,
                "function": self.function,
                "auto": self.auto,
                "parent": self.parent,
                "status": self.status,
                "error": self.error,
                "started": self.started,
                "ended": _now(),
                "cwd": self.cwd,
                "argv": list(sys.argv),
                "params": self.params,
                "inputs": self.inputs,
                "outputs": self.outputs,
                "observed": {
                    "reads": list(self.reads),
                    "writes": list(self.writes),
                    "subprocesses": self.subprocesses,
                },
                **checks,
                "code": code_identity(self.function_file),
                "env": environment(),
                "shephex": _shephex_identity(self.cwd),
            }
            directory = Path(self.cwd) / RECORD_DIR
            directory.mkdir(exist_ok=True)
            self.path = directory / f"{self.id}.json"
            self.path.write_text(json.dumps(record, indent=1))
            sink = os.environ.get("CHRONEX_RECORD_LIST")
            if sink:
                with open(sink, "a") as stream:
                    stream.write(f"{self.path}\n")
        return self.path


def _shephex_identity(cwd: str) -> dict[str, Any] | None:
    meta = Path(cwd) / "shephex" / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):  # pragma: no cover
        return None
    return {"identifier": data.get("identifier"), "directory": cwd}
