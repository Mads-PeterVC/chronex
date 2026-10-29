"""Copy every chunk's labels into data/labels/."""

import argparse
import shutil
from pathlib import Path

import chronex

parser = argparse.ArgumentParser()
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()

with chronex.step("collect") as s:
    Path("data/labels").mkdir(parents=True, exist_ok=True)
    for chunk in range(args.chunks):
        shutil.copyfile(
            s.input(f"runs/label/chunk-{chunk}/energies.npy"),
            s.output(f"data/labels/chunk-{chunk}.npy"),
        )
