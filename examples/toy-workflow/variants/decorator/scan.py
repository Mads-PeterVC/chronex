"""Monte Carlo of the staged model over temperature (one array task per seed)."""

import argparse
import csv
import json
from pathlib import Path

import toymodel

import chronex
from chronex import In, Out


@chronex.step
def scan(model: In[Path], curve: Out[Path], seed: int) -> None:
    eci = json.loads(model.read_text())["eci"]
    rows = toymodel.metropolis(eci, toymodel.TEMPERATURES, seed=seed)
    curve.parent.mkdir(parents=True, exist_ok=True)
    with open(curve, "w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["seed", *rows[0]])
        writer.writeheader()
        writer.writerows({"seed": seed, **row} for row in rows)


parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, required=True)
args = parser.parse_args()
scan(Path("staging/eci.json"), Path(f"runs/scan/seed-{args.seed}/curve.csv"), args.seed)
