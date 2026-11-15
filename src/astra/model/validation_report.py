"""The validation report: what a validator found of an analysis.

It holds a diagnostic for each rule broken in the analysis and in every analysis it declares,
directly or not: a `MUST` broken is an error, and a `SHOULD` a warning. An analysis is valid
when it breaks no `MUST`, and only a valid one resolves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from astra.model import to_json
from astra.model.diagnostic import Diagnostic


@dataclass(frozen=True)
class ValidationReport:
    """What validating an analysis found."""

    root: str  # the analysis's `astra.yaml`, as a diagnostic's location names a file
    valid: bool  # whether no `MUST` is broken: warnings and `unchecked` notwithstanding
    diagnostics: tuple[Diagnostic, ...]  # the working tree's files first, then each commit's,
    # each file in order of place
    unchecked: tuple[str, ...] = ()  # the validator's codes this astra-tools doesn't check yet
    schema_version: Literal["astra-tools.validation-report.v1"] = field(
        default="astra-tools.validation-report.v1", init=False
    )

    def to_json(self) -> dict[str, Any]:
        """The report as JSON (`astra.model.to_json`)."""
        value: dict[str, Any] = to_json(self)
        return value
