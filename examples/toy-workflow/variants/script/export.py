"""Merge the per-seed curves into one table with awk."""

import subprocess
from pathlib import Path

import chronex

chronex.track()

curves = [chronex.input(p) for p in sorted(Path("runs/scan").glob("seed-*/curve.csv"))]
Path("results").mkdir(exist_ok=True)
with open(chronex.output("results/curves.csv"), "w") as table:
    subprocess.run(["awk", "FNR > 1 || NR == 1", *map(str, curves)], stdout=table, check=True)
