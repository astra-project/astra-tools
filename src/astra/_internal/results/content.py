"""The content of a file an analysis names, an input's or a result's bytes: whether it is in
this clone, which tool keeps it, and its hash.

At the file's path there is its content, a stand-in for it (`sources.standins`), or neither.
The content is here where the path holds it or a stand-in leads to it, and its hash is the one a
stand-in gives of it, or its own. Nothing is fetched and no tool is asked: a stand-in whose
content isn't here says which tool keeps it, and getting it is a runner's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from astra._internal.results import hashing
from astra._internal.sources.reader import Reader
from astra._internal.sources.standins import StandIn


@dataclass(frozen=True)
class Content:
    """What is at the path of a file an analysis names."""

    reader: Reader
    path: str
    standin: StandIn | None = None  # the stand-in there, where one is
    local: Path | None = None  # the file its content is in, in this clone, where it is here

    @property
    def here(self) -> bool:
        """Whether reading the path gives the content, through a stand-in's link too."""
        if self.standin is not None:
            return self.local is not None
        entry = self.reader.stat(self.path)
        return entry is not None and entry.kind == "file"

    @property
    def kept_by(self) -> str | None:
        """The tool whose stand-in is at the path."""
        return None if self.standin is None else self.standin.name

    def digest(self) -> hashing.Digest | None:
        """The content's hash and size: what the stand-in gives of it, never the stand-in's
        own, or the content's where it is here; None where neither can be told."""
        if self.standin is None:
            return hashing.digest(self.reader, self.path)
        given = self.standin.gives(self.reader, self.path)
        if given is not None:
            return hashing.Digest(*given)
        return None if self.local is None else hashing.digest_file(self.local)


def look(reader: Reader, path: str, standins: Sequence[StandIn]) -> Content:
    """What is at `path` in `reader`: the first of `standins` that recognises it, with where
    its content is here, or the file itself."""
    for standin in standins:
        if standin.recognises(reader, path):
            return Content(reader, path, standin, standin.content(reader, path))
    return Content(reader, path)
