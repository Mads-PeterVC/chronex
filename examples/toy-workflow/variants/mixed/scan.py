"""Monte Carlo of the staged model over temperature, one shephex experiment per seed."""

import argparse
import csv
import json
import os
from pathlib import Path

import shephex
import toymodel

import chronex
from chronex import Out


@shephex.hexperiment(procedure_type="ScriptProcedure", hex_directory="runs/scan")
@chronex.step
def scan(seed: int, curve: Out[str] = "curve.csv") -> None:
    model = chronex.input(shephex.shared_path("eci.json"))
    eci = json.loads(model.read_text())["eci"]
    rows = toymodel.metropolis(eci, toymodel.TEMPERATURES, seed=seed)
    with open(curve, "w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["seed", *rows[0]])
        writer.writeheader()
        writer.writerows({"seed": seed, **row} for row in rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    args = parser.parse_args()
    os.environ["SHEPHEX_SHARED"] = str(Path("staging").resolve())  # the remote shared directory
    shephex.LocalExecutor().execute([scan(seed=seed) for seed in args.seeds])
