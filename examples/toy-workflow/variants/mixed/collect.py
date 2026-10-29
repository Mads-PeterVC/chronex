"""Copy every labelling experiment's energies into data/labels/, named by chunk."""

import json
import shutil
from pathlib import Path

import chronex
from chronex import In, Out


@chronex.step
def collect(energies: In[list[Path]], options: In[list[Path]], labels: Out[Path]) -> None:
    labels.mkdir(parents=True, exist_ok=True)
    for source, option in zip(energies, options, strict=True):
        chunk = json.loads(option.read_text())["kwargs"]["chunk"]
        shutil.copyfile(source, labels / f"chunk-{chunk}.npy")


experiments = sorted(Path("runs/label").glob("*-exp"))
collect(
    [e / "energies.npy" for e in experiments],
    [e / "shephex/options.json" for e in experiments],
    Path("data/labels"),
)
