"""Re-entrancy guard: chronex's own file access must not be observed by its audit hook."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_state = threading.local()


def active() -> bool:
    return getattr(_state, "depth", 0) > 0


@contextmanager
def quiet() -> Iterator[None]:
    _state.depth = getattr(_state, "depth", 0) + 1
    try:
        yield
    finally:
        _state.depth -= 1
