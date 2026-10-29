"""Run the toy workflow the way an agent would: one command per step, in a fresh workspace.

    uv run python examples/toy-workflow/drive.py decorator /tmp/toy-decorator --faults

Variants are the directories in ``variants/``, plus ``wrapper``: the plain scripts run
through ``chronex run``. With ``--faults``, four realistic mistakes are planted:

1. failed-but-used: labelling chunk 3 writes its energies, then fails; collect copies it anyway.
2. hand-edited intermediate: a collected label file is edited between collect and fit.
3. hidden read: ``configs/prior.json`` exists, and the fit reads it from inside ``toymodel``.
4. re-staged model: after two Monte Carlo seeds, the model is refitted and re-staged, so the
   last two seeds use a different model than the first two.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CHUNKS = 4
SEEDS = [0, 1, 2, 3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--faults", action="store_true")
    args = parser.parse_args()

    variant = args.variant
    scripts = HERE / "variants" / ("plain" if variant == "wrapper" else variant)
    if not scripts.is_dir():
        raise SystemExit(f"no variant {variant}")
    work: Path = args.workspace
    work.mkdir(parents=True, exist_ok=False)
    shutil.copytree(HERE / "configs", work / "configs")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(HERE), env.get("PYTHONPATH")) if p)
    env["MPLBACKEND"] = "Agg"
    if args.faults:
        env["TOY_FAIL_CHUNK"] = "3"

    def step(script: str, *arguments: object) -> None:
        command = [sys.executable, str(scripts / f"{script}.py"), *map(str, arguments)]
        if variant == "wrapper":
            command = [sys.executable, "-m", "chronex.cli", "run", "--", *command]
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True)
        status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
        print(f"  {script} {' '.join(map(str, arguments))}: {status}")
        if result.returncode != 0 and "post-processing check failed" not in result.stderr:
            print(result.stderr[-2000:])

    step("generate", "--n", 240, "--seed", 0)
    if variant == "mixed":
        step("label", "--chunks", CHUNKS)
    else:
        for chunk in range(CHUNKS):
            step("label", "--chunk", chunk, "--chunks", CHUNKS)
    step("collect", *(() if variant == "mixed" else ("--chunks", CHUNKS)))
    if args.faults:  # 2: someone "fixes" an outlier by hand
        path = work / "data/labels/chunk-1.npy"
        energies = np.load(path)
        energies[0] *= 1.5
        np.save(path, energies)
        # 3: a prior left behind from an earlier experiment
        (work / "configs/prior.json").write_text(json.dumps({"eci": [0.0, 0.0, 0.4, -0.1]}))
    step("fit", "--alpha", 1e-3, *(() if variant == "mixed" else ("--chunks", CHUNKS)))
    step("stage")
    first, second = SEEDS[:2], SEEDS[2:]
    for batch in (first, second):
        if args.faults and batch is second:  # 4: refit with another alpha and re-stage
            step("fit", "--alpha", 0.1, *(() if variant == "mixed" else ("--chunks", CHUNKS)))
            step("stage")
        if variant == "mixed":
            step("scan", "--seeds", *batch)
        else:
            for seed in batch:
                step("scan", "--seed", seed)
    step("export")
    step("plot")


if __name__ == "__main__":
    main()
