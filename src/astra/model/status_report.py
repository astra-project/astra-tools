"""The status report: how each result of an analysis stands, and its evidence.

It holds a status for each result of the resolved analysis, by the result's id, and no more of
the analysis than that: `resolve` gives the analysis. `head` is on both, so a reader that asked
for each can tell the two were read at the same commit.

A result is `unchanged` where it has a record at each of its places and nothing it is made from
has changed since the commit the record names; `stale` where something has; and `missing` where
a place has no record that is the result's own. Separately, its bytes are `present` where those
at its place hash to its record's, and `absent` otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from astra.model import to_json
from astra.model.diagnostic import Diagnostic
from astra.model.provenance_record import ProvenanceRecord

State = Literal["unchanged", "stale", "missing"]
Bytes = Literal["present", "absent"]


@dataclass(frozen=True)
class Status:
    """A planned result's status: the worst of its places'."""

    state: State
    bytes: Bytes | None = None  # None for a result of an analysis from a commit that no recipe
    # reads
    record: ProvenanceRecord | None = None  # its record, where every place holds one that is
    # the result's: the first place's
    why: tuple[Diagnostic, ...] = ()  # each rule the result itself breaks
    stale_inputs: tuple[str, ...] = ()  # each entry of its output's `inputs` that reads a result
    # that isn't unchanged, or one made again since with other bytes than the record gives


@dataclass(frozen=True)
class EvidenceStatus:
    """An item of evidence that cites an output, and the status it gets: the worst of the
    results it cites, and `missing` where it cites none."""

    insight: str  # the insight it backs, by ref
    index: int  # which item of the insight's `evidence`, from zero
    state: State
    why: tuple[Diagnostic, ...] = ()  # STALE_EVIDENCE, where it isn't unchanged


@dataclass(frozen=True)
class StatusReport:
    """How an analysis's results stand: each result's status, by the result's id, and the status
    of each evidence that cites one."""

    head: str | None  # the commit the repository was on when it was read, as
    # `ResolvedAnalysis.head` gives it
    statuses: Mapping[str, Status]
    evidence: tuple[EvidenceStatus, ...]

    def to_json(self) -> dict[str, Any]:
        """The report as JSON (`astra.model.to_json`)."""
        value: dict[str, Any] = to_json(self)
        return value
