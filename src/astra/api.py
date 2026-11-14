"""The public surface of astra-tools: everything a tool built on it imports, from here.

Three questions of an analysis, each a function of the files and git, none of which runs a
recipe, and each answered in plain data that writes as JSON:

- `validate`: is it valid (`ValidationReport`);
- `resolve`: what does it mean, with every rule of the specification already applied
  (`ResolvedAnalysis`): its analyses and what they declare, each universe's selection, and its
  planned results, each with its places, what it reads and its command as it runs;
- `check`: do its results' records still hold (`CheckReport`): the resolved analysis again, and
  each result's status.

And what a runner writes back: `write_records`, a result's record at each of its places.
`astra.scaffold.create_boilerplate` writes a new analysis.

What to build, in what order, where and in which environment is a runner's own business, and
nothing here says it.
"""

from __future__ import annotations

import os

from astra.cache import CacheError
from astra.check import CheckReport, EvidenceStatus, Status
from astra.check import check as _check
from astra.diagnostics import Diagnostic, Location
from astra.model import FragmentSelector, Resources, TextQuoteSelector
from astra.records import (
    Environment,
    Generation,
    ProvenanceRecord,
    RecordedInput,
    Runner,
    write_records,
)
from astra.resolve import read as _read
from astra.resolved import (
    Analysis,
    Commit,
    Decision,
    Evidence,
    Input,
    Insight,
    Option,
    Output,
    Place,
    ResolvedAnalysis,
    Result,
    Source,
    Universe,
)
from astra.sources.git import GitError
from astra.sources.reader import NoAnalysisError, worktree
from astra.sources.remote import Remotes
from astra.universes import RequestError
from astra.validate import InvalidAnalysisError, ValidationReport
from astra.validate import validate as _validate

__all__ = [
    "Analysis",
    "CacheError",
    "CheckReport",
    "Commit",
    "Decision",
    "Diagnostic",
    "Environment",
    "Evidence",
    "EvidenceStatus",
    "FragmentSelector",
    "Generation",
    "GitError",
    "Input",
    "Insight",
    "InvalidAnalysisError",
    "Location",
    "NoAnalysisError",
    "Option",
    "Output",
    "Place",
    "ProvenanceRecord",
    "RecordedInput",
    "RequestError",
    "ResolvedAnalysis",
    "Resources",
    "Result",
    "Runner",
    "Source",
    "Status",
    "TextQuoteSelector",
    "Universe",
    "ValidationReport",
    "check",
    "resolve",
    "validate",
    "write_records",
]


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
    return _validate(*worktree(path), Remotes(offline=offline))


def resolve(
    path: str | os.PathLike[str] | None = None, *, offline: bool = False
) -> ResolvedAnalysis:
    """The analysis whose folder is `path`, read as `validate` reads it, resolved
    (`astra.resolved`). Raises InvalidAnalysisError where the analysis breaks a `MUST`, and
    otherwise as `validate` does."""
    return _read(path, Remotes(offline=offline)).analysis


def check(
    path: str | os.PathLike[str] | None = None, *, at: str | None = None, offline: bool = False
) -> CheckReport:
    """The checker's report on the analysis whose folder is `path`, read as `validate` reads
    it: the analysis as it resolved, each planned result's status, and its evidence's
    (`astra.check`), so that one call tells a runner both what the results are and how each
    stands. With `at`, a revision of the repository that holds the analysis (a commit, a
    branch, a tag), the analysis is checked as it is at that commit, with its records and bytes
    read there. Raises InvalidAnalysisError where the analysis breaks a `MUST`, RequestError
    where `at` names no commit, and otherwise as `validate` does."""
    remotes = Remotes(offline=offline)
    return _check(_read(path, remotes, at), remotes)
