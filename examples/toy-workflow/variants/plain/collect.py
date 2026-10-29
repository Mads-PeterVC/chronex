"""Copy every chunk's labels into data/labels/."""

import argparse
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()

Path("data/labels").mkdir(parents=True, exist_ok=True)
for chunk in range(args.chunks):
    shutil.copyfile(f"runs/label/chunk-{chunk}/energies.npy", f"data/labels/chunk-{chunk}.npy")
