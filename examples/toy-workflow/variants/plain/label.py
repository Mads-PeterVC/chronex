"""Label one chunk of the configurations with the oracle (one array task per chunk)."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import toymodel

ORACLE = "configs/oracle.json"

parser = argparse.ArgumentParser()
parser.add_argument("--chunk", type=int, required=True)
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()

configs = np.load("data/structures.npy")[args.chunk :: args.chunks]
params = json.loads(Path(ORACLE).read_text())
out = Path(f"runs/label/chunk-{args.chunk}")
out.mkdir(parents=True, exist_ok=True)
np.save(out / "energies.npy", toymodel.oracle_energy(configs, params))
if os.environ.get("TOY_FAIL_CHUNK") == str(args.chunk):
    raise RuntimeError("post-processing check failed")  # planted fault: fails after writing
