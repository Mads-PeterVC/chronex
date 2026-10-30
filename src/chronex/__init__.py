"""chronex: provenance records for computational research.

Mark up a step in whichever way costs the least in that piece of code::

    @chronex.step                                   # a function with typed paths
    def fit(data: In[Path], model: Out[Path], alpha: float = 1e-3) -> None: ...

    with chronex.step("fit", alpha=alpha) as s:     # a block
        x = np.load(s.input("data.npy"))

    chronex.track(alpha=alpha)                      # the rest of a script
    x = np.load(chronex.input("data.npy"))

or not at all, with `chronex run -- python script.py`. Each produces one JSON record per
step in `.chronex/`; `chronex check` links them by file hash and reports problems.
"""

__version__ = "0.0.1"

from chronex.api import IN, OUT, In, Out, input, output, step, track
from chronex.record import Step, current

__all__ = ["IN", "OUT", "In", "Out", "Step", "current", "input", "output", "step", "track"]
