"""Copy every chunk's labels into data/labels/."""

import argparse
import shutil
from pathlib import Path

import chronex
from chronex import In, Out


@chronex.step
def collect(chunks: In[list[Path]], labels: Out[list[Path]]) -> None:
    for source, target in zip(chunks, labels, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


parser = argparse.ArgumentParser()
parser.add_argument("--chunks", type=int, default=4)
args = parser.parse_args()
collect(
    [Path(f"runs/label/chunk-{c}/energies.npy") for c in range(args.chunks)],
    [Path(f"data/labels/chunk-{c}.npy") for c in range(args.chunks)],
)
