"""What ran and where: code identity and a small, safe slice of the environment."""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

from chronex import _guard
from chronex.hashing import file_sha256

# chronex's own modules are recorded by version, not as part of the user's code.
_CHRONEX_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "")

# Only these environment variables are recorded; the full environment may hold secrets.
SAFE_VARIABLES = (
    "SLURM_JOB_ID",
    "SLURM_ARRAY_JOB_ID",
    "SLURM_ARRAY_TASK_ID",
    "SLURM_CLUSTER_NAME",
    "SLURM_JOB_PARTITION",
    "SLURM_JOB_NODELIST",
    "APPTAINER_CONTAINER",
    "SINGULARITY_CONTAINER",
    "GRIMOIRE_IMAGE",
    "SHEPHEX_SHARED",
)


def _git(root: Path, *args: str) -> str | None:
    try:
        with _guard.quiet():
            result = subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10
            )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


@cache
def git_state(directory: str) -> dict[str, Any] | None:
    """Commit, dirtiness and a hash of the uncommitted diff of the repository holding a path.

    Cached per process: a step's code does not change while the process runs.
    """
    root = _git(Path(directory), "rev-parse", "--show-toplevel")
    if root is None:
        return None
    diff = _git(Path(root), "diff", "HEAD") or ""
    status = _git(Path(root), "status", "--porcelain", "--untracked-files=no") or ""
    return {
        "root": root,
        "commit": _git(Path(root), "rev-parse", "HEAD"),
        "dirty": bool(status),
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest() if diff else None,
    }


def _local_module_files(roots: set[str]) -> dict[str, str]:
    """Files of loaded modules that live under one of ``roots`` (the user's own code)."""
    files = {}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not path or not path.endswith(".py"):
            continue
        path = os.path.realpath(path)
        if "site-packages" in path or path.startswith(_CHRONEX_DIR):
            continue
        if any(path.startswith(root) for root in roots) and os.path.isfile(path):
            files[path] = file_sha256(path)
    return files


def main_file() -> str | None:
    """The script being run.

    ``__main__.__file__``, or ``sys.argv[0]`` when that is gone: Python 3.15 clears it before
    ``atexit`` handlers run.
    """
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if isinstance(main, str):
        return main
    if sys.argv and sys.argv[0] and os.path.isfile(sys.argv[0]):
        return os.path.abspath(sys.argv[0])
    return None


def inline_source() -> str | None:
    """The code given with ``python -c``, if that is how this process runs."""
    argv = getattr(sys, "orig_argv", [])
    if sys.argv[:1] != ["-c"] or "-c" not in argv[:-1]:
        return None
    return str(argv[argv.index("-c") + 1])


def script_name() -> str:
    """A step name for the whole process: the script's name, or ``inline`` for ``-c``."""
    if not sys.argv or not sys.argv[0]:
        return "script"
    if sys.argv[0] == "-c":
        return "inline"
    return Path(sys.argv[0]).stem


def code_identity(function_file: str | None = None, entry: str | None = None) -> dict[str, Any]:
    """The entry script, the step's own file, every loaded local module, and their git state."""
    main = entry or main_file()
    anchors = [p for p in (main, function_file) if p]
    roots = set()
    # Directories on PYTHONPATH hold the user's own modules too (but not chronex's boot dir).
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if entry and "_boot" not in entry and os.path.isdir(entry):
            roots.add(os.path.join(os.path.realpath(entry), ""))
    for anchor in anchors:
        directory = str(Path(anchor).resolve().parent)
        state = git_state(directory)
        roots.add(os.path.join(state["root"] if state else directory, ""))
    files = _local_module_files(roots)
    for anchor in anchors:
        real = os.path.realpath(anchor)
        if os.path.isfile(real):
            files[real] = file_sha256(real)
    repos = {}
    for path in files:
        state = git_state(str(Path(path).parent))
        if state:
            repos[state["root"]] = state
    return {
        "entry": os.path.realpath(main) if main else None,
        "inline": _inline(),
        "files": files,
        "git": list(repos.values()),
    }


def _inline() -> dict[str, str] | None:
    source = inline_source()
    if source is None:
        return None
    return {"source": source, "sha": hashlib.sha256(source.encode()).hexdigest()}


def _package_versions() -> dict[str, str]:
    versions = {}
    for name, module in list(sys.modules.items()):
        if "." in name or name.startswith("_") or name in sys.stdlib_module_names:
            continue
        version = getattr(module, "__version__", None)
        if isinstance(version, str):
            versions[name] = version
    from chronex import __version__

    versions["chronex"] = __version__
    return dict(sorted(versions.items()))


def environment() -> dict[str, Any]:
    return {
        "host": socket.gethostname(),
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}",
        "executable": sys.executable,
        "variables": {k: os.environ[k] for k in SAFE_VARIABLES if k in os.environ},
        "packages": _package_versions(),
    }
