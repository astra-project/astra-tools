"""The provenance record: a runner's account of how it made a result, kept at the result's place.

What a record says is the runner's to find out, and true of its run: the bytes its recipe made
and read, the commit it ran from, the environment it ran in.

These classes have the fields of the record schema's, which astra-spec also ships as classes
LinkML generates (`astra.datamodel.provenance`). They are defined here because importing those
loads LinkML and RDF, several times the cost of all of astra-tools, and gives mutable classes.
"""

from __future__ import annotations

from dataclasses import dataclass

SPEC_VERSION = "0.1.0"
"""The version of the records this astra-tools writes."""


@dataclass(frozen=True)
class RecordedInput:
    """What a recipe read through one entry of its output's `inputs`."""

    entry: str  # the entry, exactly as written
    content_hash: str
    size: int


@dataclass(frozen=True)
class Environment:
    """The environment a recipe ran in, named by an IRI its runner can recreate it from."""

    iri: str


@dataclass(frozen=True)
class Runner:
    """The runner that ran a recipe, and its version."""

    id: str
    version: str


@dataclass(frozen=True)
class Generation:
    """A run of an output's recipe: the commit it ran from, what it read, the environment it ran
    in, the runner, and when it started and finished."""

    commit: str
    environment: Environment
    runner: Runner
    inputs: tuple[RecordedInput, ...] = ()  # one for each entry the output's `inputs` lists
    started: str | None = None  # a time, in UTC to the millisecond: `2026-10-26T14:00:00.000Z`
    finished: str | None = None


@dataclass(frozen=True)
class ProvenanceRecord:
    """A record: a result's address, the hash and size of its bytes, and the run that made it."""

    address: str
    content_hash: str
    size: int
    generated_by: Generation
    spec_version: str = SPEC_VERSION
