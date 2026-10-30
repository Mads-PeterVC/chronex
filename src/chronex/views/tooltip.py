"""The text of a step's tooltip: parameters across runs, code version, when it ran, flags."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from typing import Any

from chronex.graph import Record
from chronex.views.lineage import commit

MAX_LISTED = 8  # tooltip lines of one kind before "and N more"


def tooltip(name: str, runs: list[Record], flags: list[tuple[str, str, str]]) -> str:
    statuses: dict[str, int] = defaultdict(int)
    for r in runs:
        statuses[r["status"]] += 1
    counts = ", ".join(f"{n} {status}" for status, n in sorted(statuses.items()))
    runs_text = "1 run" if len(runs) == 1 else f"{len(runs)} runs"
    lines = [f"{name}: {runs_text} ({counts})"]
    for key, value in _params(runs).items():
        lines.append(f"{key} = {value}")
    lines += _code(runs)
    lines.append("ran: " + _span(runs))
    for r in runs:
        if r.get("error"):
            lines.append(f"error: {r['error']}")
            break
    if flags:
        lines.append("flags:")
        lines += listed(f"{level} {code}: {text}" for level, code, text in flags)
    return "\n".join(lines)


def _params(runs: list[Record]) -> dict[str, str]:
    """Each parameter's value, or its range or set of values across runs."""
    found: dict[str, list[Any]] = defaultdict(list)
    for r in runs:
        for key, value in r["params"].items():
            if key == "argv":
                key, value = "command", " ".join(map(str, _command(r)))
            found[key].append(value)
    shown = {}
    for key, values in found.items():
        distinct = sorted({json.dumps(v, sort_keys=True) for v in values})
        if len(distinct) == 1:
            shown[key] = _short(values[0])
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            shown[key] = f"{min(values):g}–{max(values):g} ({len(distinct)} values)"
        else:
            listed = [_short(json.loads(v)) for v in distinct[:4]]
            more = f" and {len(distinct) - 4} more" if len(distinct) > 4 else ""
            shown[key] = ", ".join(listed) + more
    return shown


def _command(record: Record) -> list[Any]:
    """The command line; a Python process recorded itself with only its script's arguments."""
    argv: list[Any] = record["params"]["argv"]
    if record.get("auto") and record.get("argv"):
        return ["python", os.path.basename(record["argv"][0]), *argv]
    return argv


def _code(runs: list[Record]) -> list[str]:
    """Which file the code ran from and its version, then the latest run's cell or -c code."""
    entries = sorted({os.path.basename(r["code"]["entry"]) for r in runs if r["code"]["entry"]})
    commits = sorted({commit(g) for r in runs for g in r["code"]["git"]})
    where = ", ".join(entries[:3]) + (f" and {len(entries) - 3} more" if len(entries) > 3 else "")
    if commits:
        version = "at " + ", ".join(commits)
    elif any(r["code"]["files"] or r["code"]["inline"] for r in runs):
        version = "not in git"
    else:
        version = ""
    line = " ".join(part for part in (where, version) if part)
    lines = [f"code: {line}"] if line else []
    inline = runs[-1]["code"]["inline"]
    if inline:
        source = [
            text[:79] + "…" if len(text) > 80 else text
            for text in inline["source"].splitlines()
            if text.strip()
        ]
        lines.append("cell:" if runs[-1]["code"]["entry"] else "code given with -c:")
        lines += listed(source)
    return lines


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _span(runs: list[Record]) -> str:
    start = min(r["started"] for r in runs)
    end = max(r["ended"] or r["started"] for r in runs)
    first = dt.datetime.fromisoformat(start)
    last = dt.datetime.fromisoformat(end)
    if first.date() == last.date():
        return f"{first:%Y-%m-%d %H:%M}–{last:%H:%M} UTC"
    return f"{first:%Y-%m-%d %H:%M} – {last:%Y-%m-%d %H:%M} UTC"


def listed(lines: Any, indent: str = "  ") -> list[str]:
    lines = list(lines)
    shown = [f"{indent}{line}" for line in lines[:MAX_LISTED]]
    if len(lines) > MAX_LISTED:
        shown.append(f"{indent}and {len(lines) - MAX_LISTED} more")
    return shown
