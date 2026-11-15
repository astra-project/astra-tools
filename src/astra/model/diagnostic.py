"""A diagnostic: a rule broken, or a note, and where.

Its code is a rule's in the specification's table of rules, or one of astra-tools' own, and its
level is the rule's: a `MUST` broken is an error and a `SHOULD` a warning. A note breaks no rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["error", "warning", "note"]


@dataclass(frozen=True)
class Location:
    """Where a diagnostic is: a document, and a place in it."""

    file: str  # the document's path from its repository's top
    pointer: str  # JSON Pointer into it; "" for the whole file
    line: int | None = None
    column: int | None = None
    key: str | None = None  # the map key or field the diagnostic names
    commit: str | None = None  # set when the file was read at a commit
    url: str | None = None  # set when it came from a remote


@dataclass(frozen=True)
class Diagnostic:
    """A rule broken: its code, its level, and where."""

    code: str
    level: Level
    message: str
    location: Location
    related: tuple[Location, ...] = ()
