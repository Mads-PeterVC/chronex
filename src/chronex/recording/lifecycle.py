"""The steps open in this process, and what ends them: SIGTERM, and a fork leaving them behind."""

from __future__ import annotations

import contextlib
import os
import signal
import threading
import types
from typing import TYPE_CHECKING

from chronex.recording import audit

if TYPE_CHECKING:
    from chronex.recording.step import Step

stack: list[Step] = []


def current() -> Step | None:
    """The innermost active step, if any."""
    return stack[-1] if stack else None


def _on_sigterm(signum: int, frame: types.FrameType | None) -> None:
    """Finish every open step as killed, then die of SIGTERM as the process would have."""
    for step in list(reversed(stack)):
        if step._open:
            step.finish("killed: SIGTERM")
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    os.kill(os.getpid(), signal.SIGTERM)


def catch_sigterm() -> None:
    """Install the SIGTERM handler, unless something else already handles SIGTERM."""
    if threading.current_thread() is not threading.main_thread():
        return
    if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        signal.signal(signal.SIGTERM, _on_sigterm)


def _forget_in_child() -> None:
    """A forked child inherits the parent's open steps, which are the parent's to finish."""
    for step in stack:
        step._open = False
        audit.unlisten(step._listen)
    stack.clear()
    if signal.getsignal(signal.SIGTERM) is _on_sigterm:
        with contextlib.suppress(ValueError):  # not the main thread
            signal.signal(signal.SIGTERM, signal.SIG_DFL)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_in_child)


def release_sigterm() -> None:
    if stack or threading.current_thread() is not threading.main_thread():
        return
    if signal.getsignal(signal.SIGTERM) is _on_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
