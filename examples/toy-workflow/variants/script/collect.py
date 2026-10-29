"""Copy every chunk's labels into data/labels/."""

import argparse
import shutil
from pathlib import Path

import chronex

parser = argparse.ArgumentParser()
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()
chronex.track(**vars(args))

Path("data/labels").mkdir(parents=True, exist_ok=True)
for chunk in range(args.chunks):
    shutil.copyfile(
        chronex.input(f"runs/label/chunk-{chunk}/energies.npy"),
        chronex.output(f"data/labels/chunk-{chunk}.npy"),
    )
