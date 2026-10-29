"""Generate distinct random configurations."""

import argparse
from pathlib import Path

import numpy as np
import toymodel

import chronex
from chronex import Out


@chronex.step
def generate(structures: Out[Path], n: int, seed: int) -> None:
    structures.parent.mkdir(exist_ok=True)
    np.save(structures, toymodel.generate(n, seed))


parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=240)
parser.add_argument("--seed", type=int, default=0)
args = parser.parse_args()
generate(Path("data/structures.npy"), args.n, args.seed)
