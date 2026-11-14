"""The public surface of astra-tools: everything a tool built on it imports, from here.

Four questions of an analysis, each a function of the files and git, none of which runs a recipe:

- `validate`: is it valid;
- `resolve`: what does it mean, its planned results with their places, what each reads and the
  options each is made with, and through `Resolved.view` how it looks in one universe;
- `check`: do its results' records still hold;
- `history`: what does git keep of those records.

`bind` gives the stack of an analysis that needn't be valid. Beside them are what a runner
writes and fills in: the record format (`Record`, `write_record`, `timestamp`), a file's
`Digest` as a record gives it (`digest_file`), and the grammar of a recipe's command (`fill`).
`astra.scaffold.create_boilerplate` writes a new analysis.

What to build, in what order, where and in which environment is a runner's own business, and
nothing here says it.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable
from pathlib import Path

from astra.cache import CacheError
from astra.check import Change, Checked, CheckReport, EvidenceStatus, Reason, Status
from astra.check import check as check_resolved
from astra.diagnostics import Diagnostic, Location
from astra.grammar import fill
from astra.hashing import Digest, digest_file
from astra.history import History, NotInHistoryError
from astra.model import Analysis, Resources
from astra.records import Record, RecordedInput, Runner, timestamp, write_record
from astra.resolve import Key, Note, Read, Resolved, Result
from astra.resolve import resolve as resolve_stack
from astra.sources.git import GitError, Repository
from astra.sources.reader import CommitReader, Reader, WorktreeReader
from astra.sources.remote import Remotes
from astra.stack import Bound, Element, Identity, Stack
from astra.stack import bind as bind_reader
from astra.universes import Place, RequestError
from astra.validate import ValidationReport, validated
from astra.validate import validate as validate_reader
from astra.view import UniverseView

__all__ = [
    "Analysis",
    "Bound",
    "CacheError",
    "Change",
    "CheckReport",
    "Checked",
    "Diagnostic",
    "Digest",
    "Element",
    "EvidenceStatus",
    "GitError",
    "History",
    "Identity",
    "InvalidAnalysisError",
    "Key",
    "Location",
    "NoAnalysisError",
    "NotInHistoryError",
    "Note",
    "Place",
    "Read",
    "Reason",
    "Record",
    "RecordedInput",
    "RequestError",
    "Resolved",
    "Resources",
    "Result",
    "Runner",
    "Status",
    "UniverseView",
    "ValidationReport",
    "bind",
    "check",
    "digest_file",
    "fill",
    "history",
    "resolve",
    "timestamp",
    "validate",
    "write_record",
]


class NoAnalysisError(Exception):
    """No `astra.yaml` where an analysis is asked for: a usage error, not a broken rule."""


class InvalidAnalysisError(Exception):
    """The analysis breaks a `MUST`, so it resolves to nothing, and has no view and no history:
    `report` says where. `check` gives what statuses it can instead."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"{report.root} breaks a MUST: `astra validate` says where")
        self.report = report


def validate(
    path: str | os.PathLike[str] | None = None, *, offline: bool = False
) -> ValidationReport:
    """The validator's report on the analysis whose folder is `path`, the current folder by
    default. Nothing is searched for: the folder holds the analysis's `astra.yaml`.

    It is read in the working tree of the git repository that holds it. A commit is got from a
    remote into the cache, once; `offline`, nothing is fetched, and only the commits kept
    from earlier fetches can be got. Raises NoAnalysisError where there is no analysis,
    GitError where git can't be run, CacheError where the cache can't be used, and OSError
    where a file can't be read.
    """
    reader, root = _root(path)
    return validate_reader(reader, root, Remotes(offline=offline))


def bind(path: str | os.PathLike[str] | None = None, *, offline: bool = False) -> Bound:
    """The stack whose root is the analysis whose folder is `path`, read as `validate` reads it,
    with the parse and schema diagnostics of its files. Its `stack` is None where the root's
    file isn't a valid document, or the root is in no repository. Raises as `validate` does."""
    reader, root = _root(path)
    return bind_reader(reader, root, remotes=Remotes(offline=offline))


def resolve(path: str | os.PathLike[str] | None = None, *, offline: bool = False) -> Resolved:
    """The analysis whose folder is `path`, read as `validate` reads it, resolved: its planned
    results, each after every result it reads, with its places, what each entry of its output's
    `inputs` reads and the option each entry of its `decisions` selects (`resolve.resolve`).
    Raises InvalidAnalysisError where the analysis breaks a `MUST`, and otherwise as `validate`
    does."""
    return resolve_stack(_valid(path, Remotes(offline=offline)))


def check(
    path: str | os.PathLike[str] | None = None,
    *,
    at: str | None = None,
    universes: Iterable[str] | None = None,
    outputs: Iterable[str] | None = None,
    offline: bool = False,
) -> CheckReport:
    """The checker's report on the analysis whose folder is `path`, read as `validate` reads
    it: each planned result's record and bytes statuses at each of its places, and its
    evidence's, all of them or those `universes` and `outputs` narrow it to (`check.check`).
    With `at`, a revision of the repository that holds the analysis (a commit, a branch, a tag),
    the analysis is checked as it is at that commit, with its records and bytes read there.
    Where the analysis breaks a `MUST`, the report holds the errors, and only the results whose
    planning is determined get statuses: none where the root's file isn't a valid document or
    it is in no repository. Where it is valid, the report holds the analysis as it resolved
    (`CheckReport.resolved`), so that one call tells a runner both what the results are and how
    each stands. Raises RequestError where `at` names no commit or a universe or an output asked
    for isn't there, or is a switch, and otherwise as `validate` does."""
    remotes = Remotes(offline=offline)
    reader, report, stack = _read(path, at, remotes)
    errors = tuple(diagnostic for diagnostic in report.diagnostics if diagnostic.level == "error")
    if stack is None:  # no result's planning is determined
        commit = reader.commit if isinstance(reader, CommitReader) else "worktree"
        return CheckReport(report.root, commit, (), (), errors)
    return check_resolved(resolve_stack(stack), universes, outputs, remotes, errors)


def history(path: str | os.PathLike[str] | None = None, *, offline: bool = False) -> History:
    """The history of the records of the planned results of the analysis whose folder is
    `path`, read as `validate` reads it, and read from git on demand: each query is one call of
    what this gives, `timeline`, `lineage`, `find` or `get` (`history.History`). Raises
    InvalidAnalysisError where the analysis breaks a `MUST`, and otherwise as `validate` does."""
    remotes = Remotes(offline=offline)
    return History(resolve_stack(_valid(path, remotes)), remotes)


def _valid(path: str | os.PathLike[str] | None, remotes: Remotes) -> Stack:
    """The stack whose root is the analysis in `path`, read in the working tree, where it is
    valid. Raises InvalidAnalysisError where it isn't."""
    _, report, stack = _read(path, None, remotes)
    if not report.valid:  # an invalid analysis resolves to nothing
        raise InvalidAnalysisError(report)
    assert stack is not None  # a valid analysis has a stack
    return stack


def _read(
    path: str | os.PathLike[str] | None, at: str | None, remotes: Remotes
) -> tuple[Reader, ValidationReport, Stack | None]:
    """The reader of the analysis in `path`, in the working tree or at the revision `at`, its
    validation report, and the stack it judged (`validate.validated`). Raises RequestError
    where `at` names no commit."""
    reader, root = _root(path)
    if at is not None and reader.repo is not None:
        commit = reader.repo.commit(at)
        if commit is None:
            raise RequestError(f"`{at}` names no commit of {reader.repo.top}")
        reader = CommitReader(reader.repo, commit, None, remotes)
        entry = reader.stat(posixpath.join(root, "astra.yaml"))
        if entry is None or entry.kind != "file":
            raise NoAnalysisError(f"{root or '.'} has no astra.yaml file at {commit}")
    report, stack = validated(reader, root, remotes)
    return reader, report, stack


def _root(path: str | os.PathLike[str] | None) -> tuple[Reader, str]:
    """The reader of the working tree that holds the folder `path`, and the folder's path in
    it. Raises NoAnalysisError where the folder holds no `astra.yaml` file."""
    folder = Path.cwd() if path is None else Path(path)
    if not folder.is_dir():
        raise NoAnalysisError(f"{folder} isn't a folder: give the folder of an analysis")
    repo = Repository.discover(folder)
    reader: Reader
    if repo is None:
        # Outside a repository, a file's path is from the analysis's folder.
        reader, root = WorktreeReader(folder, None), ""
    else:
        reader = WorktreeReader(repo.top, repo)
        root = "/".join(folder.resolve().relative_to(repo.top).parts)
    entry = reader.stat(posixpath.join(root, "astra.yaml"))
    if entry is None or entry.kind != "file":  # a symlink isn't one
        raise NoAnalysisError(f"{folder} has no astra.yaml file: give the folder of an analysis")
    return reader, root
