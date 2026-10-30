"""A problem found in the graph, attached to the step it is about."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEVELS = ("error", "warn", "info")


@dataclass
class Flag:
    level: str  # error, warn or info
    code: str
    text: str
    refs: list[str] = field(default_factory=list)  # ids of related steps
    path: str | None = None  # the file it is about, if any

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "text": self.text,
            "path": self.path,
            "refs": self.refs,
        }
