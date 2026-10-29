"""Stage the fitted model as a shared file for the Monte Carlo jobs."""

import shutil
from pathlib import Path

import chronex
from chronex import In, Out


@chronex.step
def stage(model: In[Path], staged: Out[Path]) -> None:
    staged.parent.mkdir(exist_ok=True)
    shutil.copyfile(model, staged)


stage(Path("model/eci.json"), Path("staging/eci.json"))
