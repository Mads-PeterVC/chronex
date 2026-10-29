"""Label one chunk of the configurations with the oracle (one array task per chunk)."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import toymodel

import chronex
from chronex import In, Out

ORACLE = "configs/oracle.json"


@chronex.step
def label(
    structures: In[Path], oracle: In[Path], energies: Out[Path], chunk: int, chunks: int
) -> None:
    configs = np.load(structures)[chunk::chunks]
    params = json.loads(oracle.read_text())
    energies.parent.mkdir(parents=True, exist_ok=True)
    np.save(energies, toymodel.oracle_energy(configs, params))
    if os.environ.get("TOY_FAIL_CHUNK") == str(chunk):
        raise RuntimeError("post-processing check failed")  # planted fault: fails after writing


parser = argparse.ArgumentParser()
parser.add_argument("--chunk", type=int, required=True)
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()
label(
    Path("data/structures.npy"),
    Path(ORACLE),
    Path(f"runs/label/chunk-{args.chunk}/energies.npy"),
    args.chunk,
    args.chunks,
)
