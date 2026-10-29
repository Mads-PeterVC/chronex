"""Monte Carlo of the staged model over temperature (one array task per seed)."""

import argparse
import csv
import json
from pathlib import Path

import toymodel

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, required=True)
args = parser.parse_args()

eci = json.loads(Path("staging/eci.json").read_text())["eci"]
rows = toymodel.metropolis(eci, toymodel.TEMPERATURES, seed=args.seed)
out = Path(f"runs/scan/seed-{args.seed}")
out.mkdir(parents=True, exist_ok=True)
with open(out / "curve.csv", "w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["seed", *rows[0]])
    writer.writeheader()
    writer.writerows({"seed": args.seed, **row} for row in rows)
