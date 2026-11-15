"""Stand-ins: what a large-file tool keeps in a file's place.

Which stand-ins count is the validator's to say. astra-tools recognises three, and never
fetches what they stand for:

- Git LFS: a pointer file at the path (`version https://git-lfs.github.com/spec/v1`, then
  `oid sha256:…` and `size …`);
- git-annex: a symlink into `annex/objects/` at the path, or an unlocked pointer file there,
  whose one line is a path into `/annex/objects/`;
- DVC: a `<path>.dvc` file beside the path.

A stand-in isn't the content, but it can give the content's hash and size, which the checker
compares: a Git LFS pointer gives both, a git-annex link both for a key of its `SHA256` and
`SHA256E` backends, and a DVC file no SHA-256.

It can also say where the content is in this clone, where it is: a git-annex link leads to it
once it is fetched, and DVC puts it at the path beside its file. A pointer file, of Git LFS or
of git-annex, is there only while the content isn't, as the tool puts the content in its place.
Nothing here asks a tool, or a remote, whether it has the content: fetching is a runner's.

They are an extension point: another package adds one by registering an object
that has `StandIn`'s members in the entry-point group `astra.standins`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from astra._internal.sources.reader import Reader, WorktreeReader

GROUP = "astra.standins"
"""The entry-point group other packages register their stand-ins in."""


class StandIn(Protocol):
    """A kind of stand-in a tool keeps in a file's place."""

    @property
    def name(self) -> str:
        """The tool's name, as messages give it."""
        ...

    def place(self, path: str) -> str:
        """Where the tool keeps the stand-in for the file at `path`: what git tracks for it."""
        ...

    def recognises(self, reader: Reader, path: str) -> bool:
        """Whether what is at `place(path)` in `reader` stands in for the file at `path`."""
        ...

    def gives(self, reader: Reader, path: str) -> tuple[str, int] | None:
        """The hash (`sha256:` and the digest) and the size of the file that what is at
        `place(path)`, which it recognises, stands in for; None where it doesn't give both."""
        ...

    def content(self, reader: Reader, path: str) -> Path | None:
        """The file that holds, in this clone, the content that what is at `place(path)`, which
        it recognises, stands in for; None where the content isn't here, or `reader` reads a
        commit, whose store is the tool's to read."""
        ...


_LFS_VERSION = "version https://git-lfs.github.com/spec/v1"
_LFS_OID = re.compile(r"sha256:[0-9a-f]{64}")
_LFS_SIZE = re.compile(r"[0-9]+")
_ANNEX_SHA256 = re.compile(r"SHA256E?-s([0-9]+)--([0-9a-f]{64})")


@dataclass(frozen=True)
class GitLfs:
    """A Git LFS pointer file, kept at the path itself."""

    name: str = "Git LFS"

    def place(self, path: str) -> str:
        return path

    def recognises(self, reader: Reader, path: str) -> bool:
        return self.gives(reader, path) is not None

    def gives(self, reader: Reader, path: str) -> tuple[str, int] | None:
        entry = reader.stat(path)
        if entry is None or entry.kind != "file":
            return None
        try:
            lines = reader.read(path).decode("utf-8").split("\n")
        except UnicodeDecodeError:
            return None
        if lines[0] != _LFS_VERSION or lines[-1] != "":
            return None
        fields = {key: value for key, _, value in (line.partition(" ") for line in lines[1:-1])}
        oid, size = fields.get("oid", ""), fields.get("size", "")
        if not (_LFS_OID.fullmatch(oid) and _LFS_SIZE.fullmatch(size)):
            return None
        return oid, int(size)

    def content(self, reader: Reader, path: str) -> Path | None:
        return None  # a pointer is at the path only while the content isn't


@dataclass(frozen=True)
class GitAnnex:
    """A git-annex link at the path itself: a symlink into `annex/objects/`, or an unlocked
    pointer file naming a path there."""

    name: str = "git-annex"

    def place(self, path: str) -> str:
        return path

    def recognises(self, reader: Reader, path: str) -> bool:
        return self._key(reader, path) is not None

    def gives(self, reader: Reader, path: str) -> tuple[str, int] | None:
        """For a key of the `SHA256` and `SHA256E` backends, `SHA256E-s<size>--<digest>…`."""
        key = self._key(reader, path)
        found = None if key is None else _ANNEX_SHA256.match(key.rpartition("/")[2])
        return None if found is None else (f"sha256:{found[2]}", int(found[1]))

    def content(self, reader: Reader, path: str) -> Path | None:
        """What a link leads to, once fetched; a pointer file is there only while the content
        isn't."""
        entry = reader.stat(path)
        if not isinstance(reader, WorktreeReader) or entry is None or entry.target is None:
            return None
        target = (reader.top / path).parent / entry.target
        return target if target.is_file() else None

    def _key(self, reader: Reader, path: str) -> str | None:
        """The path into `annex/objects/` that the link at `path` names, if it is one."""
        entry = reader.stat(path)
        if entry is not None and entry.kind == "symlink" and entry.target is not None:
            return entry.target if "/annex/objects/" in f"/{entry.target}" else None
        if entry is None or entry.kind != "file":
            return None
        line = reader.read(path).removesuffix(b"\n")
        if not line.startswith(b"/annex/objects/") or b"\n" in line:
            return None
        return line.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Dvc:
    """A DVC file, `<path>.dvc`, beside the path."""

    name: str = "DVC"

    def place(self, path: str) -> str:
        return f"{path}.dvc"

    def recognises(self, reader: Reader, path: str) -> bool:
        entry = reader.stat(self.place(path))
        return entry is not None and entry.kind == "file"

    def gives(self, reader: Reader, path: str) -> tuple[str, int] | None:
        return None  # a DVC file gives an MD5, not a SHA-256

    def content(self, reader: Reader, path: str) -> Path | None:
        """The file at the path itself, which DVC writes or links from its cache."""
        file = reader.top / path if isinstance(reader, WorktreeReader) else None
        return file if file is not None and file.is_file() else None


BUILT_IN: tuple[StandIn, ...] = (GitLfs(), GitAnnex(), Dvc())
"""The stand-ins astra-tools recognises itself."""


def registered() -> tuple[StandIn, ...]:
    """The built-in stand-ins, then each one another package registers in `GROUP`."""
    from importlib.metadata import entry_points

    return (*BUILT_IN, *(point.load() for point in entry_points(group=GROUP)))
