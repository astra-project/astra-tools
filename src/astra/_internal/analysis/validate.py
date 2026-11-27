"""validate(): the validator's report on an analysis.

It binds the stack (`stack`): every `astra.yaml` of it, by the parse and schema rules and
astra-tools' `UNSUPPORTED_SPEC_VERSION`. Then it runs the validator rules (`rules`) on the
stack, or reports `NOT_IN_REPOSITORY` for a root in no repository, whose declarations aren't
followed. The two rules about the root's repository are checked here, whether or not its file
is a valid document: `NOT_IN_REPOSITORY`, and `MISSING_TOP_ANALYSIS`, that the top of its
repository, in the tree the root is read in, holds an `astra.yaml` file, which a symlink or a
folder isn't. A root read at a commit, an analysis from a commit judged as its own root
(`rules.commits`), is judged at that commit. The validator codes no check of this build reports
are listed in the report as `unchecked`.
"""

from __future__ import annotations

import posixpath

from astra._internal.analysis import rules
from astra._internal.analysis.rules.context import Context
from astra._internal.analysis.stack import bind
from astra._internal.documents import contract, load
from astra._internal.documents.catalogue import Catalogue
from astra._internal.sources.reader import CommitReader, Reader
from astra._internal.sources.remote import Remotes
from astra.model.diagnostic import Diagnostic, Location
from astra.model.validation_report import ValidationReport

CODES = frozenset({"NOT_IN_REPOSITORY", "MISSING_TOP_ANALYSIS"})
"""The validator codes checked here, beside those `load`, `contract` and the rules report."""


def _order(location: Location) -> tuple[bool, str, str, int, int]:
    """The working tree's files first, then each commit's, each file in order of place."""
    commit = location.commit
    file, line, column = location.file, location.line or 0, location.column or 0
    return commit is not None, commit or "", file, line, column


def _top(reader: Reader, root: str, catalogue: Catalogue) -> list[Diagnostic]:
    """`MISSING_TOP_ANALYSIS`, in the file of the root, whose folder is `root`, where the top of
    the tree `reader` reads holds no `astra.yaml` file. The message names that top as a path from
    the root's folder."""
    entry = reader.stat("astra.yaml")
    if entry is not None and entry.kind == "file":
        return []
    top = posixpath.relpath(".", root or ".")
    commit, url = (reader.commit, reader.url) if isinstance(reader, CommitReader) else (None, None)
    if commit is None:
        message = (
            f"the top of this analysis's repository, `{top}` from its folder, holds no astra.yaml "
            "file (a symlink or a folder isn't one): put one there; one with only a "
            "`spec_version` will do"
        )
    else:
        message = (
            f"the top of this analysis's repository, `{top}` from its folder, held no astra.yaml "
            f"file at `{commit}` (a symlink or a folder isn't one): declare a commit whose top "
            "holds one"
        )
    location = Location(posixpath.join(root, "astra.yaml"), "", None, None, None, commit, url)
    return [catalogue.diagnostic("MISSING_TOP_ANALYSIS", message, location)]


def unchecked(catalogue: Catalogue) -> tuple[str, ...]:
    """The validator codes of the catalogue that no check of this build reports."""
    checked = load.CODES | contract.CODES | CODES | rules.CODES
    return tuple(code for code in catalogue.codes("validator") if code not in checked)


def validate(reader: Reader, root: str, remotes: Remotes | None = None) -> ValidationReport:
    """The report on the analysis whose folder is `root` in `reader` ("" for its top), which
    holds its `astra.yaml`; commits are got from remotes through `remotes`. Raises OSError if a
    file of the stack can't be read."""
    return validated(reader, root, remotes)[0]


def validated(
    reader: Reader, root: str, remotes: Remotes | None = None
) -> tuple[ValidationReport, Context | None]:
    """The report, as `validate` gives it, and the stack it judged, with what the rules worked
    out of it: None where the root's file isn't a valid document, or it is in no repository. A
    valid report always has its stack."""
    file = posixpath.join(root, "astra.yaml")
    catalogue = Catalogue.load()
    stack, diagnostics = bind(reader, root, catalogue, remotes)
    found = list(diagnostics)
    context = None
    if reader.repo is None:
        # NOT_IN_REPOSITORY is about the folder, not the file, so it is reported beside the
        # parse and schema rules and UNSUPPORTED_SPEC_VERSION.
        message = (
            "the analysis's folder isn't in the working tree of a git repository: "
            "make one with `git init`, or move the analysis into one"
        )
        location = Location(file, "", None, None)
        found.append(catalogue.diagnostic("NOT_IN_REPOSITORY", message, location))
    else:
        found.extend(_top(reader, root, catalogue))
        if stack is not None:
            context = Context(stack, catalogue)
            found.extend(rules.check(context))
    # A MUST broken in an analysis from a commit can be found both under this root and as that
    # analysis's own root (`rules.commits`): it is reported once.
    unique = dict.fromkeys(found)
    ordered = sorted(unique, key=lambda d: _order(d.location) + (d.code,))
    valid = all(diagnostic.level != "error" for diagnostic in ordered)
    return ValidationReport(file, valid, tuple(ordered), unchecked(catalogue)), context
