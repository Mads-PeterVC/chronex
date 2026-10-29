"""Generate distinct random configurations."""

import argparse
from pathlib import Path

import numpy as np
import toymodel

import chronex

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=240)
parser.add_argument("--seed", type=int, default=0)
args = parser.parse_args()
chronex.track(**vars(args))

Path("data").mkdir(exist_ok=True)
np.save(chronex.output("data/structures.npy"), toymodel.generate(args.n, args.seed))
