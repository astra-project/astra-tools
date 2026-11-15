"""The public surface of astra-tools: everything a tool built on it imports, from here.

Three questions of an analysis, each a function of the files and git, none of which runs a
recipe, and each answered in plain data that writes as JSON (`astra.model`):

- `validate`: is it valid (`ValidationReport`);
- `resolve`: what does it mean, with every rule of the specification already applied
  (`ResolvedAnalysis`): its analyses and what they declare, each universe's selection, and its
  planned results, each with its places, what it reads and its command as it runs;
- `status`: do its results' records still hold (`StatusReport`): the resolved analysis again,
  and each result's status. It is what the specification's checker answers.

What a tool writes: `init_analysis`, an empty analysis where a folder has none, and
`write_records`, a result's record at each of its places.

And, apart from any analysis, the papers that evidence cites: `paper` looks one up in the paper
cache, `add_paper` puts one there and `verify_quote` seeks a quote in one. These aren't
functions of the files and git: the cache is this machine's, `add_paper` uses the network, and
matching a quote is astra-tools' own, as the specification has no rule on it.

What to build, in what order, where and in which environment is a runner's own business, and
nothing here says it.
"""

from __future__ import annotations

import os
from pathlib import Path

from astra._internal.analysis.resolve import read as _read
from astra._internal.analysis.validate import validate as _validate
from astra._internal.documents import scaffold as _scaffold
from astra._internal.papers import library as _library
from astra._internal.results.records import write_records
from astra._internal.results.status import status as _status
from astra._internal.sources.reader import worktree as _worktree
from astra._internal.sources.remote import Remotes as _Remotes
from astra.errors import (
    CacheError,
    GitError,
    InvalidAnalysisError,
    NoAnalysisError,
    PaperError,
    RequestError,
)
from astra.model.diagnostic import Diagnostic, Location
from astra.model.paper import Paper, QuoteStatus
from astra.model.provenance_record import (
    Environment,
    Generation,
    ProvenanceRecord,
    RecordedInput,
    Runner,
)
from astra.model.resolved_analysis import (
    Analysis,
    Commit,
    Decision,
    Evidence,
    FragmentSelector,
    Input,
    Insight,
    Option,
    Output,
    Place,
    ResolvedAnalysis,
    Resources,
    Result,
    Source,
    TextQuoteSelector,
    Universe,
)
from astra.model.status_report import EvidenceStatus, Status, StatusReport
from astra.model.validation_report import ValidationReport

__all__ = [
    "Analysis",
    "CacheError",
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
    "Paper",
    "PaperError",
    "Place",
    "ProvenanceRecord",
    "QuoteStatus",
    "RecordedInput",
    "RequestError",
    "ResolvedAnalysis",
    "Resources",
    "Result",
    "Runner",
    "Source",
    "Status",
    "StatusReport",
    "TextQuoteSelector",
    "Universe",
    "ValidationReport",
    "add_paper",
    "init_analysis",
    "paper",
    "resolve",
    "status",
    "validate",
    "verify_quote",
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
    return _validate(*_worktree(path), _Remotes(offline=offline))


def resolve(
    path: str | os.PathLike[str] | None = None, *, offline: bool = False
) -> ResolvedAnalysis:
    """The analysis whose folder is `path`, read as `validate` reads it, resolved
    (`astra.model.resolved_analysis`). Raises InvalidAnalysisError where the analysis breaks a
    `MUST`, and otherwise as `validate` does."""
    return _read(path, _Remotes(offline=offline)).analysis


def status(
    path: str | os.PathLike[str] | None = None, *, at: str | None = None, offline: bool = False
) -> StatusReport:
    """The status of the analysis whose folder is `path`, read as `validate` reads it: the
    analysis as it resolved, each planned result's status by the specification's check rules,
    and its evidence's (`astra.model.status_report`), so that one call tells a runner both what
    the results are and how each stands. With `at`, a revision of the repository that holds the
    analysis (a commit, a branch, a tag), the analysis is read as it is at that commit, with its
    records and bytes read there. Raises InvalidAnalysisError where the analysis breaks a
    `MUST`, RequestError where `at` names no commit, and otherwise as `validate` does."""
    remotes = _Remotes(offline=offline)
    return _status(_read(path, remotes, at), remotes)


def init_analysis(directory: str | os.PathLike[str]) -> None:
    """Converge `directory` into an analysis: where it has no `astra.yaml`, write one with a
    `spec_version` and a label and nothing declared, the folder made if need be.

    Idempotent: an `astra.yaml` already there is left exactly as it is, so a second call changes
    nothing, and a folder that holds an analysis is safe to pass. Nothing else is written or
    looked at, so a tool scaffolds into a folder under its own conventions; `astra init` adds a
    `.gitignore` and a git repository. Raises OSError where the file can't be written."""
    _scaffold.init_analysis(Path(directory))


def paper(doi: str, *, version: int | None = None) -> Paper | None:
    """The paper of `doi` in the paper cache, at `version` where evidence gives one; None where
    it isn't there. Raises CacheError where the cache can't be used."""
    return _library.paper(doi, version)


def add_paper(
    doi: str, *, version: int | None = None, pdf: str | os.PathLike[str] | None = None
) -> Paper:
    """Put the paper of `doi` in the paper cache, and give it: the PDF at `pdf`, or, with none,
    the one arXiv has for an arXiv DOI (`10.48550/arXiv.<id>`), at `version` where one is
    given. No other paper is downloaded. One already in the cache is given as it is. Raises
    PaperError where no PDF can be got or the file isn't a PDF, CacheError where the cache
    can't be used, and OSError where `pdf` can't be read."""
    return _library.add_paper(doi, version, pdf)


def verify_quote(
    doi: str,
    quote: TextQuoteSelector,
    *,
    version: int | None = None,
    location: FragmentSelector | None = None,
) -> QuoteStatus:
    """Whether `quote` is in the cached paper of `doi`, the fields being an `Evidence`'s own:
    `found`, with the page it is on; `elsewhere` where `location` gives a page of a PDF and the
    quote is on another; `not_found`; and `no_paper` where the paper isn't in the cache. The
    match allows for what extracting a PDF's text changes. Raises PaperError where the PDF's
    text can't be read, and CacheError where the cache can't be used."""
    return _library.verify_quote(doi, quote, version, location)
