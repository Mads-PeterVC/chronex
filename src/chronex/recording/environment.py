"""Where a step ran: host, Python, package versions and a small, safe slice of the environment."""

from __future__ import annotations

import os
import platform
import socket
import sys
import warnings
from typing import Any

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


def _package_versions() -> dict[str, str]:
    versions = {}
    for name, module in list(sys.modules.items()):
        if "." in name or name.startswith("_") or name in sys.stdlib_module_names:
            continue
        with warnings.catch_warnings():  # e.g. click deprecates its __version__
            warnings.simplefilter("ignore", DeprecationWarning)
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
        "executable": os.path.abspath(sys.executable),
        "variables": {k: os.environ[k] for k in SAFE_VARIABLES if k in os.environ},
        "packages": _package_versions(),
    }
