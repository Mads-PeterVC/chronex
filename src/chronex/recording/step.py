"""A step: one execution of some code, with what it read, wrote, ran and where.

Each step is written as one JSON file to `.chronex/` in the directory the step ran in, so
records travel with the outputs (rsync, `hex remote pull`) and a tree of results can be
indexed later without any server. The file is written when the step starts, with status
`running`, and rewritten when it ends; a record left `running` means the process died
without finishing it. SIGTERM (a Slurm time limit) finishes open steps as failed first.
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

from chronex import _guard
from chronex.hashing import identify
from chronex.recording import audit
from chronex.recording.code import code_identity, main_file
from chronex.recording.environment import environment
from chronex.recording.lifecycle import catch_sigterm, current, release_sigterm, stack
from chronex.recording.params import jsonable

SCHEMA = "chronex/0"
RECORD_DIR = ".chronex"
# Set while a step runs, so a process it starts knows it was started by one.
STEP_VARIABLE = "CHRONEX_STEP"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


class Step:
    """Collects one step's provenance; use through `chronex.step` or `chronex.track`.

    Parameters
    ----------
    name
        What the step is, e.g. `fit`. Runs of the same step share the name.
    params
        Parameters that are not files.
    kind
        `function`, `block`, `script` or `command`: which API produced the record.
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
        self.params = jsonable(params or {})
        self.function_file = function_file
        self.function = function
        self.entry = main_file()  # now: by the time the step ends, it may be gone
        self.inputs: list[dict[str, Any]] = []
        self.outputs: list[dict[str, Any]] = []
        self._declared_outputs: list[tuple[str, str | None]] = []
        self.reads: dict[str, None] = {}
        self.writes: dict[str, None] = {}
        self._first_read: set[str] = set()  # read before the step wrote them
        self._overwritten: dict[str, dict[str, Any]] = {}  # identity when first rewritten
        self._from_children: set[str] = set()  # files written by steps nested in this one
        self.subprocesses: list[str] = []
        self.workers = 0
        self.status = "running"
        self.error: str | None = None
        self.cwd = os.getcwd()
        enclosing = current()
        self.parent = enclosing.id if enclosing else os.environ.get("CHRONEX_PARENT")
        self.started = _now()
        self.path: Path | None = None
        self._open = False
        self._listed = False
        self._enclosing_env: str | None = None

    # -- declaring files -------------------------------------------------------------------

    def input(self, path: str | os.PathLike[str], param: str | None = None) -> Any:
        """Declare `path` as an input; it is hashed now. Returns `path` unchanged."""
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
        """Declare `path` as an output; it is hashed when the step ends. Returns `path`."""
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
            if value not in self.writes:
                self._first_read.add(value)
        elif kind == "write":
            # The audit event comes before open() truncates: keep what was read.
            first = value in self._first_read and value not in self._overwritten
            if first and os.path.isfile(value):
                self._overwritten[value] = identify(value)
            self.writes.setdefault(value)
        elif kind == "worker":
            self.workers += 1
        elif kind == "rename":
            source, target = value.split("\0")
            self.writes.pop(source, None)
            self.writes.setdefault(target)
        else:
            self.subprocesses.append(value)

    def start(self) -> Step:
        self._write_start()
        catch_sigterm()
        self._enclosing_env = os.environ.get(STEP_VARIABLE)
        os.environ[STEP_VARIABLE] = self.name  # inherited by workers and subprocesses
        stack.append(self)
        audit.listen(self._listen)
        self._open = True
        return self

    def finish(self, error: BaseException | str | None = None) -> Path:
        """End the step: completed, or failed with an exception or a message."""
        if not self._open:
            raise RuntimeError(f"step {self.name} is not running")
        self._open = False
        audit.unlisten(self._listen)
        if self in stack:
            stack.remove(self)
        if self._enclosing_env is None:
            os.environ.pop(STEP_VARIABLE, None)
        else:
            os.environ[STEP_VARIABLE] = self._enclosing_env
        release_sigterm()
        if isinstance(error, str):
            self.status, self.error = "failed", error
        elif error is not None:
            self.status = "failed"
            self.error = "".join(traceback.format_exception_only(type(error), error)).strip()
        elif self.status == "running":
            self.status = "completed"
        path = self._write()
        enclosing = current()
        if enclosing is not None and enclosing.id == self.parent:
            enclosing._from_children.update(o["path"] for o in self.outputs)
            enclosing._from_children.update(self.writes)
        return path

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

        # Reads of files the step wrote itself are not inputs; files read and then rewritten are.
        reads = [
            p
            for p in self.reads
            if p in self._first_read
            and p not in self._from_children
            and (p in self._overwritten or os.path.isfile(p))
        ]
        undeclared_reads = [p for p in reads if not covered(p, declared_in)]
        if self.auto:
            for path in undeclared_reads:
                observed: dict[str, Any] = {
                    "path": path,
                    "rel": os.path.relpath(path, self.cwd),
                    "param": None,
                }
                observed.update(self._overwritten.get(path) or identify(path))
                observed["how"] = "observed"
                self.inputs.append(observed)
            undeclared_reads = []
        undeclared_writes = [p for p in written if not covered(p, declared_out)]
        return {
            "undeclared_reads": undeclared_reads,
            "undeclared_writes": undeclared_writes,
            "missing_outputs": [o["path"] for o in self.outputs if o["kind"] == "missing"],
            "missing_inputs": [i["path"] for i in self.inputs if i["kind"] == "missing"],
        }

    def _document(self, checks: dict[str, Any], ended: str | None) -> dict[str, Any]:
        return {
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
            "ended": ended,
            "cwd": self.cwd,
            "argv": list(sys.argv),
            "params": self.params,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "observed": {
                "reads": list(self.reads),
                "writes": list(self.writes),
                "subprocesses": self.subprocesses,
                "workers": self.workers,
            },
            **checks,
            "code": code_identity(self.function_file, self.entry),
            "env": environment(),
            "shephex": _shephex_identity(self.cwd),
        }

    def _save(self, record: dict[str, Any]) -> Path:
        directory = Path(self.cwd) / RECORD_DIR
        directory.mkdir(exist_ok=True)
        self.path = directory / f"{self.id}.json"
        self.path.write_text(json.dumps(record, indent=1))
        sink = os.environ.get("CHRONEX_RECORD_LIST")
        if sink and not self._listed:
            self._listed = True
            with open(sink, "a") as stream:
                stream.write(f"{self.path}\n")
        return self.path

    def _write_start(self) -> None:
        """Write the record as `running`, so a process that dies still leaves it behind."""
        with _guard.quiet():
            checks: dict[str, Any] = {
                "undeclared_reads": [],
                "undeclared_writes": [],
                "missing_outputs": [],
                "missing_inputs": [],
            }
            self._save(self._document(checks, ended=None))

    def _write(self) -> Path:
        with _guard.quiet():
            return self._save(self._document(self._settle(), ended=_now()))


def _shephex_identity(cwd: str) -> dict[str, Any] | None:
    meta = Path(cwd) / "shephex" / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):  # pragma: no cover
        return None
    return {"identifier": data.get("identifier"), "directory": cwd}
