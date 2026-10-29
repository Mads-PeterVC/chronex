"""Fit the cluster expansion to the collected labels."""

import argparse
import json
from pathlib import Path

import numpy as np
import toymodel

import chronex

parser = argparse.ArgumentParser()
parser.add_argument("--alpha", type=float, default=1e-3)
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()

with chronex.step("fit", alpha=args.alpha) as s:
    structures = np.load(s.input("data/structures.npy"))
    configs = np.concatenate([structures[c :: args.chunks] for c in range(args.chunks)])
    energies = np.concatenate(
        [np.load(s.input(f"data/labels/chunk-{c}.npy")) for c in range(args.chunks)]
    )
    model = toymodel.fit_eci(configs, energies, args.alpha)
    Path("model").mkdir(exist_ok=True)
    Path(s.output("model/eci.json")).write_text(json.dumps(model, indent=1))
