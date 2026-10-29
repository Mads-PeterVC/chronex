"""Label every chunk with the oracle, one shephex experiment per chunk."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import shephex
import toymodel

import chronex
from chronex import In, Out

ORACLE = "configs/oracle.json"


@shephex.hexperiment(procedure_type="ScriptProcedure", hex_directory="runs/label")
@chronex.step
def label(
    structures: In[str],
    oracle: In[str],
    chunk: int,
    chunks: int,
    energies: Out[str] = "energies.npy",
) -> None:
    configs = np.load(structures)[chunk::chunks]
    params = json.loads(Path(oracle).read_text())
    np.save(energies, toymodel.oracle_energy(configs, params))
    if os.environ.get("TOY_FAIL_CHUNK") == str(chunk):
        raise RuntimeError("post-processing check failed")  # planted fault: fails after writing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=4)
    args = parser.parse_args()
    root = Path.cwd()
    experiments = [
        label(
            structures=str(root / "data/structures.npy"),
            oracle=str(root / ORACLE),
            chunk=chunk,
            chunks=args.chunks,
        )
        for chunk in range(args.chunks)
    ]
    shephex.LocalExecutor().execute(experiments)
