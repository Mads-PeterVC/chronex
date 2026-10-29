"""Stage the fitted model as a shared file for the Monte Carlo jobs."""

import shutil
from pathlib import Path

import chronex

chronex.track()

Path("staging").mkdir(exist_ok=True)
shutil.copyfile(chronex.input("model/eci.json"), chronex.output("staging/eci.json"))
