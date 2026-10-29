"""Merge the per-seed curves into one table with awk."""

import subprocess
from pathlib import Path

import chronex
from chronex import In, Out


@chronex.step
def export(curves: In[list[Path]], table: Out[Path]) -> None:
    table.parent.mkdir(exist_ok=True)
    with open(table, "w") as stream:
        subprocess.run(["awk", "FNR > 1 || NR == 1", *map(str, curves)], stdout=stream, check=True)


export(sorted(Path("runs/scan").glob("seed-*/curve.csv")), Path("results/curves.csv"))
