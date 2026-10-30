"""``chronex run -- cmd``: record a command without touching its code.

Python processes started by the command record themselves (see ``_boot/sitecustomize.py``):
every file they open is an input or an output. For anything else (shell, compiled tools) the
wrapper records the command itself, with the inputs given by ``--in`` and the outputs given by
``--out`` or found by comparing ``--watch`` directories before and after.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import chronex
from chronex.record import Step

BOOT = str(Path(chronex.__file__).parent / "_boot")


def _snapshot(directories: list[str]) -> dict[str, tuple[int, int]]:
    state = {}
    for directory in directories:
        for path in Path(directory).rglob("*"):
            if path.is_file() and ".chronex" not in path.parts:
                stat = path.stat()
                state[str(path.resolve())] = (stat.st_size, stat.st_mtime_ns)
    return state


def _describe(returncode: int) -> str:
    if returncode < 0:
        return f"killed: {signal.Signals(-returncode).name}"
    return f"exit code {returncode}"


@contextlib.contextmanager
def _forwarding_sigterm() -> Iterator[list[subprocess.Popen[bytes]]]:
    """Pass SIGTERM on to the command (a Slurm time limit hits chronex first).

    Installed before the command starts, so no SIGTERM is lost. SIGINT is left to the
    terminal, which sends it to the command as well.
    """
    started: list[subprocess.Popen[bytes]] = []
    if threading.current_thread() is not threading.main_thread():
        yield started
        return

    def forward(signum: int, frame: types.FrameType | None) -> None:
        for process in started:
            process.send_signal(signum)

    previous = signal.signal(signal.SIGTERM, forward)
    previous_int = signal.signal(signal.SIGINT, lambda signum, frame: None)
    try:
        yield started
    finally:
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_int)


def run(
    command: list[str],
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    watch: list[str] | None = None,
    name: str | None = None,
    quiet: bool = False,
) -> int:
    inputs, outputs, watch = inputs or [], outputs or [], watch or []
    declared = bool(inputs or outputs or watch)
    wrapper = Step(name or Path(command[0]).name, {"argv": command}, kind="command")
    with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as listing:
        records_file = listing.name
    env = dict(os.environ)
    env["CHRONEX_AUTO"] = "1"
    env["CHRONEX_PARENT"] = wrapper.id
    env["CHRONEX_RECORD_LIST"] = records_file
    if name:
        env["CHRONEX_NAME"] = name
    env["PYTHONPATH"] = os.pathsep.join(p for p in (BOOT, env.get("PYTHONPATH")) if p)

    given = {"--in": inputs, "--out": outputs, "--watch": watch}
    for option in _misplaced(command, given):
        print(
            f"chronex: {option} after -- goes to {command[0]}, not to chronex run; "
            "put chronex's options before --",
            file=sys.stderr,
        )
    before = _snapshot(watch)
    with _forwarding_sigterm() as started:
        try:
            started.append(subprocess.Popen(command, env=env))
        except OSError as error:
            os.unlink(records_file)
            print(f"chronex run: cannot run {command[0]}: {error.strerror}", file=sys.stderr)
            return 127 if isinstance(error, FileNotFoundError) else 126
        wrapper._write_start()  # if chronex itself is killed, the command shows as incomplete
        returncode = started[0].wait()
    after = _snapshot(watch)
    children = [line for line in Path(records_file).read_text().splitlines() if line]
    os.unlink(records_file)

    # The Python processes recorded themselves; unless files are declared, the command adds
    # nothing to their records, and is not recorded.
    keep = declared or not children
    recorded = []
    for child in children:
        record = json.loads(Path(child).read_text())
        recorded.append(record)
        changed = False
        if record["status"] == "running":  # killed before it could finish its record
            record["status"] = "failed"
            record["error"] = (
                f"the process ended without finishing the step ({_describe(returncode)})"
            )
            changed = True
        elif record["status"] == "completed" and returncode != 0:  # sys.exit(1), invisible inside
            record["status"] = "failed"
            record["error"] = _describe(returncode)
            changed = True
        if not keep and record["parent"] == wrapper.id:
            record["parent"] = None
            changed = True
        if changed:
            Path(child).write_text(json.dumps(record, indent=1))

    if not keep:
        if wrapper.path is not None:
            wrapper.path.unlink(missing_ok=True)
        if not quiet:
            for record in recorded:
                print(_summary(record), file=sys.stderr)
        return _exit_code(returncode)

    if not children and not declared:
        print(
            f"chronex: {command[0]} recorded no Python steps and declares no files; "
            "give its files with --in, --out or --watch",
            file=sys.stderr,
        )
    wrapper.start()
    for pattern in inputs:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            wrapper.input(path)
    for path in outputs:
        wrapper.output(path)
    for path in sorted(after):
        if before.get(path) != after[path]:
            wrapper.output(path)
    wrapper.subprocesses.append(" ".join(command))
    record = wrapper.finish(None if returncode == 0 else _describe(returncode))
    for entry in wrapper.inputs:
        if entry["kind"] == "missing":
            print(f"chronex: declared input {entry['rel']} did not exist", file=sys.stderr)
    for entry in wrapper.outputs:
        if entry["kind"] == "missing":
            print(f"chronex: declared output {entry['rel']} was not written", file=sys.stderr)
    if inputs and not (outputs or watch):
        print(
            f"chronex: {wrapper.name} declares no outputs, so no later step can link to it; "
            "give them with --out or --watch",
            file=sys.stderr,
        )
    if not quiet:
        for entry in [json.loads(record.read_text()), *recorded]:
            print(_summary(entry), file=sys.stderr)
    return _exit_code(returncode)


def _summary(record: dict[str, Any]) -> str:
    """One line saying what a step's record holds."""
    inputs, outputs = record["inputs"], record["outputs"]
    status = str(record["status"]) + (f": {record['error']}" if record.get("error") else "")
    files = (
        f"{len(inputs)} {'input' if len(inputs) == 1 else 'inputs'}, "
        f"{len(outputs)} {'output' if len(outputs) == 1 else 'outputs'}"
    )
    return f"chronex: recorded {record['name']} ({status}; {files})"


def _misplaced(command: list[str], given: dict[str, list[str]]) -> list[str]:
    """chronex run's own options found after ``--``, where they go to the command instead."""
    return [option for option, values in given.items() if option in command[1:] and not values]


def _exit_code(returncode: int) -> int:
    """A shell's exit code for the command: 128 + the signal that killed it, if one did."""
    return 128 - returncode if returncode < 0 else returncode
