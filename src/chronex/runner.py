"""``chronex run -- cmd``: record a command without touching its code.

Python processes started by the command record themselves (see ``_boot/sitecustomize.py``):
every file they open is an input or an output. For anything else (shell, compiled tools) the
wrapper records the command itself, with the inputs given by ``--in`` and the outputs given by
``--out`` or found by comparing ``--watch`` directories before and after.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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


def run(
    command: list[str],
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    watch: list[str] | None = None,
    name: str | None = None,
    quiet: bool = False,
) -> int:
    inputs, outputs, watch = inputs or [], outputs or [], watch or []
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

    before = _snapshot(watch)
    returncode = subprocess.call(command, env=env)
    after = _snapshot(watch)
    children = [line for line in Path(records_file).read_text().splitlines() if line]
    os.unlink(records_file)

    for child in children:  # sys.exit(1) and kills are invisible from inside the process
        record = json.loads(Path(child).read_text())
        if record["status"] == "running":
            record["status"] = "failed"
            record["error"] = (
                f"the process ended without finishing the step (exit code {returncode})"
            )
        elif record["status"] == "completed" and returncode != 0:
            record["status"] = "failed"
            record["error"] = f"exit code {returncode}"
        else:
            continue
        Path(child).write_text(json.dumps(record, indent=1))

    declared = bool(inputs or outputs or watch)
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
    record = wrapper.finish(None if returncode == 0 else f"exit code {returncode}")
    if not quiet:
        steps = f" and {len(children)} Python step(s)" if children else ""
        print(f"chronex: recorded {wrapper.name}{steps} in {record.parent}", file=sys.stderr)
    return returncode
