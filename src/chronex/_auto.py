"""Zero-touch recording of a whole Python process, started from ``sitecustomize``."""

from __future__ import annotations

import sys
from pathlib import Path

from chronex.api import _finish_at_exit
from chronex.record import Step


class _ProcessStep(Step):
    """A step whose name comes from ``sys.argv``, which is not set yet at interpreter start.

    It writes no start record, as its id is not final until then; ``chronex run`` records
    a process that dies without finishing.
    """

    def _write_start(self) -> None:
        pass

    def _write(self) -> Path:
        if sys.argv and sys.argv[0]:
            self.name = Path(sys.argv[0]).stem
            self.params = {"argv": sys.argv[1:]}
            self.id = self.id.replace("-python-", f"-{self.name}-", 1)
        main = getattr(sys.modules.get("__main__"), "__file__", None)
        self.function_file = main
        return super()._write()


def start() -> None:
    step = _ProcessStep("python", kind="command", auto=True)
    step.start()
    _finish_at_exit(step)
