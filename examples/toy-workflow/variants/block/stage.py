"""Stage the fitted model as a shared file for the Monte Carlo jobs."""

import shutil
from pathlib import Path

import chronex

with chronex.step("stage") as s:
    Path("staging").mkdir(exist_ok=True)
    shutil.copyfile(s.input("model/eci.json"), s.output("staging/eci.json"))
