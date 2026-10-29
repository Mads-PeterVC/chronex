"""The ways to mark up code: a decorator with typed paths, a block, or a whole script.

All three produce the same record. Inside any of them, ``chronex.input(path)`` and
``chronex.output(path)`` declare files the signature cannot name in advance. Outside a step
they do nothing, so annotated code also runs untracked.
"""

from __future__ import annotations

import atexit
import functools
import inspect
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType
from typing import (
    Annotated,
    Any,
    ParamSpec,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from chronex.record import Step, current

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")


class _Role:
    def __init__(self, role: str) -> None:
        self.role = role

    def __repr__(self) -> str:
        return f"chronex.{self.role}"


IN = _Role("In")
OUT = _Role("Out")

In = Annotated[T, IN]
"""A parameter holding input path(s): ``data: In[Path]`` or ``chunks: In[list[Path]]``."""
Out = Annotated[T, OUT]
"""A parameter holding output path(s), hashed when the function returns."""


def _paths(value: Any) -> Iterator[str | os.PathLike[str]]:
    if value is None:
        return
    if isinstance(value, (str, os.PathLike)):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _paths(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _paths(item)
    else:
        raise TypeError(f"expected a path or a collection of paths, got {type(value).__name__}")


def _roles(function: Callable[..., Any]) -> dict[str, _Role]:
    hints = get_type_hints(function, include_extras=True)
    roles = {}
    for name, hint in hints.items():
        if get_origin(hint) is Annotated:
            for meta in get_args(hint)[1:]:
                if meta is IN or meta is OUT:
                    roles[name] = meta
    return roles


def _decorate(function: Callable[P, R], name: str) -> Callable[P, R]:
    if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
        raise TypeError(
            f"{function.__qualname__} is a generator, which runs after the call returns; record "
            f"the loop that consumes it with a block instead: with chronex.step({name!r}): ..."
        )
    signature = inspect.signature(function)
    roles = _roles(function)
    source = inspect.getsourcefile(function)
    qualified = f"{function.__module__}:{function.__qualname__}"

    def begin(*args: Any, **kwargs: Any) -> Step:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        params = {k: v for k, v in bound.arguments.items() if k not in roles}
        step = Step(name, params, kind="function", function_file=source, function=qualified)
        for param, role in roles.items():
            for path in _paths(bound.arguments[param]):
                (step.input if role is IN else step.output)(path, param)
        return step.start()

    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def coroutine(*args: Any, **kwargs: Any) -> Any:
            step = begin(*args, **kwargs)
            try:
                result = await function(*args, **kwargs)
            except BaseException as error:
                step.finish(error)
                raise
            step.finish()
            return result

        return coroutine  # type: ignore[return-value]

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        step = begin(*args, **kwargs)
        try:
            result = function(*args, **kwargs)
        except BaseException as error:
            step.finish(error)
            raise
        step.finish()
        return result

    return wrapper


class StepSpec:
    """``chronex.step("name", **params)``: a decorator, or a ``with`` block."""

    def __init__(self, name: str | None, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self._steps: list[Step] = []

    def __call__(self, function: Callable[P, R]) -> Callable[P, R]:
        return _decorate(function, self.name or function.__name__)

    def __enter__(self) -> Step:
        if self.name is None:
            raise TypeError("a step used as a block needs a name: chronex.step('fit')")
        step = Step(self.name, self.params, kind="block")
        self._steps.append(step)
        return step.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._steps.pop().finish(exc)


@overload
def step(function: Callable[P, R], /) -> Callable[P, R]: ...
@overload
def step(name: str | None = None, /, **params: Any) -> StepSpec: ...
def step(arg: Any = None, /, **params: Any) -> Any:
    """Record a function call, or a block, as a step.

    As a decorator, parameters annotated ``In[...]`` / ``Out[...]`` are the step's files and
    every other argument is a recorded parameter::

        @chronex.step
        def fit(data: In[Path], model: Out[Path], alpha: float = 1e-3) -> None: ...

    As a block, files are declared where they are used::

        with chronex.step("fit", alpha=alpha) as s:
            x = np.load(s.input("data.npy"))
            np.save(s.output("model.npy"), fit(x))
    """
    if callable(arg):
        return _decorate(arg, arg.__name__)
    return StepSpec(arg, params)


def input(path: T, param: str | None = None) -> T:
    """Declare an input of the current step and return ``path``; a no-op outside a step."""
    active = current()
    if active is not None:
        active.input(path, param)  # type: ignore[arg-type]
    return path


def output(path: T, param: str | None = None) -> T:
    """Declare an output of the current step and return ``path``; a no-op outside a step."""
    active = current()
    if active is not None:
        active.output(path, param)  # type: ignore[arg-type]
    return path


def track(name: str | None = None, *, auto: bool = False, **params: Any) -> Step:
    """Record the rest of this script as one step, finished when the interpreter exits.

    One line at the top of a script. Files are then declared with ``chronex.input`` and
    ``chronex.output``; an uncaught exception marks the step failed.
    """
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    step_name = name or (Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "script")
    active = Step(step_name, params, kind="script", auto=auto, function_file=main)
    active.start()
    _finish_at_exit(active)
    return active


def _finish_at_exit(active: Step) -> None:
    previous = sys.excepthook

    def excepthook(
        kind: type[BaseException], error: BaseException, tb: TracebackType | None
    ) -> None:
        if active._open:
            active.finish(error)
        previous(kind, error, tb)

    sys.excepthook = excepthook

    def finish() -> None:
        if active._open:
            active.finish()

    atexit.register(finish)
