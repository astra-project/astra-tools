"""What the functions of `astra.api` raise, beside OSError where a file can't be read."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.model.validation_report import ValidationReport


class NoAnalysisError(Exception):
    """No `astra.yaml` where an analysis is asked for: a usage error, not a broken rule."""


class InvalidAnalysisError(Exception):
    """The analysis breaks a `MUST`, so it resolves to nothing and has no statuses: `report`
    says where."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"{report.root} breaks a MUST: `astra validate` says where")
        self.report = report


class GitError(Exception):
    """git can't be run: a broken environment, not a broken analysis."""


class CacheError(Exception):
    """The cache can't be used where the environment puts it."""


class PaperError(Exception):
    """A paper can't be put in the cache, or its PDF can't be read."""
