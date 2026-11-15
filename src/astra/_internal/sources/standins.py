"""Stand-ins: what a large-file tool keeps in a file's place.

Which stand-ins count is the validator's to say. astra-tools recognises three, and never
fetches what they stand for:

- Git LFS: a pointer file at the path (`version https://git-lfs.github.com/spec/v1`, then
  `oid sha256:…` and `size …`);
- git-annex: a symlink at the path whose target, a relative one, names a file in an
  `annex/objects/` folder of the tree, or an unlocked pointer file there, whose one line is a
  path into `/annex/objects/`;
- DVC: a `<path>.dvc` file beside the path.

A stand-in isn't the content, but it can give the content's hash and size, which the checker
compares: a Git LFS pointer gives both, a git-annex link both for a key of its `SHA256` and
`SHA256E` backends, and a DVC file no SHA-256.

It can also say where the content is on disk, where it is in this clone. A link is followed
only for that, as the operating system follows it: a git-annex link to the file it names, once
it is fetched, where that file really is in an `annex/objects` folder, so in a submodule or a
linked worktree too, whose store is outside the tree; and what is at the path beside a DVC
file, wherever DVC's cache is. A pointer file, of Git LFS or of git-annex, is there only while
the content isn't, as the tool puts the content in its place. A link that is no stand-in's is
never followed. Nothing asks a tool, or a remote, whether it has the content: fetching is a
runner's.

A file an analysis names, an input's or a result's, is read one way, `look`: it is its content,
a stand-in for it, or neither.

They are an extension point: another package adds one by registering an object
that has `StandIn`'s members in the entry-point group `astra.standins`.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from astra._internal.sources import paths
from astra._internal.sources.reader import Reader

GROUP = "astra.standins"
"""The entry-point group other packages register their stand-ins in."""

_POINTER_MAX = 1024
"""No pointer file is longer: Git LFS's is under 1024 bytes by its specification, and
git-annex's is one line that names a key, which fits a file name. A longer file isn't one, and
isn't read to see."""


def _pointer(reader: Reader, path: str) -> bytes | None:
    """The bytes of the file at `path` where it is short enough to be a pointer file; None for
    a longer one, of which only that much is read, and for what isn't a file."""
    entry = reader.stat(path)
    if entry is None or entry.kind != "file":
        return None
    head = reader.read(path, _POINTER_MAX + 1)
    return head if len(head) <= _POINTER_MAX else None


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
        """The file on disk that holds the content that what is at `place(path)`, which it
        recognises, stands in for (`Reader.follow`); None where the content isn't in this
        clone."""
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
        data = _pointer(reader, path)
        try:
            lines = None if data is None else data.decode("utf-8").split("\n")
        except UnicodeDecodeError:
            lines = None
        if lines is None:
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
        """The file a link leads to, once it is fetched, where that really is in an
        `annex/objects` folder: a link dressed as git-annex's that leads elsewhere isn't
        followed. A pointer file is there only while the content isn't."""
        entry = reader.stat(path)
        if entry is None or entry.kind != "symlink" or self._key(reader, path) is None:
            return None
        file = reader.follow(path)
        return file if file is not None and "/annex/objects/" in file.as_posix() else None

    def _key(self, reader: Reader, path: str) -> str | None:
        """The path into `annex/objects/` that the link at `path` names, if it is one: a
        symlink's target, as a path of the same tree, or a pointer file's one line."""
        entry = reader.stat(path)
        if entry is not None and entry.kind == "symlink" and entry.target is not None:
            if posixpath.isabs(entry.target):  # git-annex's links are relative
                return None
            target = paths.join(posixpath.dirname(path), entry.target)
            return target if target is not None and "/annex/objects/" in f"/{target}" else None
        line = (_pointer(reader, path) or b"").removesuffix(b"\n")
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
        """What is at the path itself, where DVC writes the file or links it from its cache,
        which can be anywhere."""
        return reader.follow(path)


BUILT_IN: tuple[StandIn, ...] = (GitLfs(), GitAnnex(), Dvc())
"""The stand-ins astra-tools recognises itself."""


@dataclass(frozen=True)
class Found:
    """What is at the path of a file an analysis names: its content, a stand-in for it, or
    neither."""

    here: bool = False  # whether the content is in this clone: at the path, or where a
    # stand-in leads
    standin: StandIn | None = None  # the stand-in there, where one is
    file: Path | None = None  # for a stand-in whose content is here, the file that holds it

    @property
    def kept_by(self) -> str | None:
        """The tool whose stand-in is at the path."""
        return None if self.standin is None else self.standin.name


def look(reader: Reader, path: str, standins: Sequence[StandIn]) -> Found:
    """What is at `path` in `reader`: the first of `standins` that recognises it, with where
    its content is, or the file itself."""
    for standin in standins:
        if standin.recognises(reader, path):
            file = standin.content(reader, path)
            return Found(file is not None, standin, file)
    entry = reader.stat(path)
    return Found(entry is not None and entry.kind == "file")


def registered() -> tuple[StandIn, ...]:
    """The built-in stand-ins, then each one another package registers in `GROUP`."""
    from importlib.metadata import entry_points

    return (*BUILT_IN, *(point.load() for point in entry_points(group=GROUP)))
