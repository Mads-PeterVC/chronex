"""Merge the per-seed curves into one table with awk."""

import subprocess
from pathlib import Path

curves = sorted(Path("runs/scan").glob("seed-*/curve.csv"))
Path("results").mkdir(exist_ok=True)
with open("results/curves.csv", "w") as table:
    subprocess.run(["awk", "FNR > 1 || NR == 1", *map(str, curves)], stdout=table, check=True)
