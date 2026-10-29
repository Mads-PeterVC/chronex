"""Fit the cluster expansion to the collected labels."""

import argparse
import json
from pathlib import Path

import numpy as np
import toymodel

import chronex
from chronex import In, Out


@chronex.step
def fit(structures: In[Path], labels: In[list[Path]], model: Out[Path], alpha: float) -> None:
    chunks = len(labels)
    all_structures = np.load(structures)
    configs = np.concatenate([all_structures[c::chunks] for c in range(chunks)])
    energies = np.concatenate([np.load(path) for path in labels])
    model.parent.mkdir(exist_ok=True)
    model.write_text(json.dumps(toymodel.fit_eci(configs, energies, alpha), indent=1))


parser = argparse.ArgumentParser()
parser.add_argument("--alpha", type=float, default=1e-3)
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()
fit(
    Path("data/structures.npy"),
    [Path(f"data/labels/chunk-{c}.npy") for c in range(args.chunks)],
    Path("model/eci.json"),
    args.alpha,
)
