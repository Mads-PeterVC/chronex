"""Stage the fitted model as a shared file for the Monte Carlo jobs."""

import shutil
from pathlib import Path

Path("staging").mkdir(exist_ok=True)
shutil.copyfile("model/eci.json", "staging/eci.json")
