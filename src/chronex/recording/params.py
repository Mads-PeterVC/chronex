"""A step's parameters as JSON: small values as they are, large ones as a summary with a hash."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

# Parameters with more values than this are recorded as a summary with a hash.
MAX_LISTED_VALUES = 100


def _summary(value: Any, **fields: Any) -> dict[str, Any]:
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}", **fields}


def _array_sha(value: Any) -> str | None:
    if getattr(getattr(value, "dtype", None), "hasobject", True):
        return None  # object arrays hold pointers, not values
    try:
        return hashlib.sha256(value.tobytes()).hexdigest()
    except Exception:
        return None


def jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [jsonable(v) for v in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=repr)
        if len(items) <= MAX_LISTED_VALUES:
            return items
        text = json.dumps(items, sort_keys=True, default=repr)
        return _summary(value, len=len(items), sha=hashlib.sha256(text.encode()).hexdigest())
    size = getattr(value, "size", None)
    if hasattr(value, "shape") and isinstance(size, int) and size > MAX_LISTED_VALUES:
        dtype = getattr(value, "dtype", None)
        return _summary(
            value,
            shape=list(value.shape),
            dtype=None if dtype is None else str(dtype),
            sha=_array_sha(value),
        )
    if hasattr(value, "tolist"):  # numpy scalars and small arrays
        try:
            return jsonable(value.tolist())
        except Exception:  # pragma: no cover
            pass
    return repr(value)
