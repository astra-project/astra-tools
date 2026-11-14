"""The resolved analysis: an analysis with every rule of the specification already applied.

Plain data, the same for every reader: a runner reads the results, a page reads everything. Two
rules decide what is in it.

It holds what the rules give, not what they start from. Where an `astra.yaml` writes something
only for a rule to act on, the model holds the outcome and drops the instruction: an effective
selection and no `derived_from`, the file each entry of an output's `inputs` reads and no
switch, a rendered command and no template, and no constraint between options, as only a valid
analysis resolves. What a file writes to be read by people stays as written: labels,
descriptions, rationales, claims, quotes.

It holds each fact once. A derived fact is here only if working it out takes a rule of the
specification: where a result's record and bytes go, what each entry reads, the command as it
runs. What a reader gets by following a reference isn't repeated: a result carries neither the
options it is made with (its output's `decisions`, in its universe's `selection`) nor the
folder its recipe runs in (its output's analysis's `folder`).

A reference is an id, never an object, so the model writes as JSON (`to_json`): the JSON holds
every field under its name, an optional one left out where it has no value, never null.

- A `ref` names an element among all the analyses of the stack: its analysis's `key`, the
  collection the file writes it in, and its id, joined by dots (`outputs.fit`,
  `stage.decisions.method`). An analysis's `key` is its canonical address: the shortest chain
  of declarations that reaches it from the driving analysis, among equals the first in
  alphabetical order, and "" for the driving analysis itself.
- A result's `id` is its address, as its record gives it (`fit#baseline`), after the key of the
  analysis it belongs to and a colon where that isn't the driving analysis (`stage:fit#v1`).

Every path is a path from the driving analysis's folder, with `/` between folders and `.` for
that folder itself. A file of an analysis read at a commit is no file of the working tree: its
path is in that commit's tree, from the top of the repository it is read in. A diagnostic's
`location` isn't such a path: it names its file from the top of the repository, as a
validator's does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Literal

from astra.diagnostics import Diagnostic
from astra.model import FragmentSelector, Resources, TextQuoteSelector

__all__ = [
    "Analysis",
    "Commit",
    "Decision",
    "Evidence",
    "Input",
    "Insight",
    "Option",
    "Output",
    "Place",
    "ResolvedAnalysis",
    "Result",
    "Source",
    "Universe",
    "to_json",
]


@dataclass(frozen=True)
class Commit:
    """The commit an analysis is read at."""

    id: str
    repository: str | None = None  # the URL of another repository; None for the one that holds
    # the driving analysis


@dataclass(frozen=True)
class Input:
    """A file an analysis reads."""

    ref: str
    path: str
    label: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Option:
    """One of a decision's options."""

    id: str
    label: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    excluded: str | None = None  # why it is excluded: such an option is never selected
    insights: tuple[str, ...] = ()  # the prior insights that support it, by ref


@dataclass(frozen=True)
class Decision:
    """A choice an analysis makes, between its options."""

    ref: str
    options: tuple[Option, ...]
    label: str | None = None
    rationale: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Output:
    """What an analysis declares it makes. A switch isn't one: where a file writes a switch, each
    result that reads it names what it reads there (`Result.inputs`)."""

    ref: str
    type: str
    format: str
    label: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    resources: Resources | None = None  # what its recipe asks for
    decisions: tuple[str, ...] = ()  # the decisions it is made with, by ref


@dataclass(frozen=True)
class Evidence:
    """What a claim rests on: a work, by its `doi`, or the results of an output, in `cites`."""

    doi: str | None = None
    version: int | None = None
    cites: tuple[str, ...] | None = None  # for evidence that cites an output, the id of each
    # planned result it cites (Results *Evidence*): none where no result of it is planned
    quote: TextQuoteSelector | None = None
    location: FragmentSelector | None = None


@dataclass(frozen=True)
class Insight:
    """A claim backed by evidence: what an analysis builds on, or what it concludes."""

    ref: str
    kind: Literal["prior_insight", "finding"]
    claim: str
    evidence: tuple[Evidence, ...]
    label: str | None = None
    description: str | None = None
    scope: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Universe:
    """A universe of an analysis, with the option it selects for each decision it uses."""

    ref: str
    selection: Mapping[str, str]  # a decision's ref, and the option selected: exactly the
    # decisions the universe uses, with its own analysis driving (Results *uses*)
    label: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Analysis:
    """One analysis of the stack, with what it declares."""

    key: str  # its canonical address; "" for the driving analysis
    folder: str
    commit: Commit | None = None  # the commit it is read at; None where it is read as the
    # driving analysis is
    label: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    declares: Mapping[str, str] = field(default_factory=dict)  # each declaration's id, and the
    # key of the analysis it reaches
    inputs: tuple[Input, ...] = ()
    decisions: tuple[Decision, ...] = ()
    outputs: tuple[Output, ...] = ()
    prior_insights: tuple[Insight, ...] = ()
    findings: tuple[Insight, ...] = ()
    universes: tuple[Universe, ...] = ()


@dataclass(frozen=True)
class Source:
    """What one entry of an output's `inputs` reads for a result: an input, or another result,
    through any pin and the case each switch on the way takes."""

    entry: str  # as the output's `inputs` writes it
    input: str | None = None  # the input it reads, by ref
    result: str | None = None  # or the planned result it reads, by id


@dataclass(frozen=True)
class Place:
    """Where one name of a result is kept (Results *place*)."""

    address: str  # the name, then `#` and the universe's id for a result built in one
    record_path: str
    bytes_path: str


@dataclass(frozen=True)
class Result:
    """A planned result (Results *plans*): one output, in one universe or once."""

    id: str
    output: str  # by ref
    places: tuple[Place, ...]  # one, unless its analysis is driven through two chains
    universe: str | None = None  # by ref; None for an output built once
    inputs: tuple[Source, ...] = ()  # one for each entry of its output's `inputs`, in order
    command: str | None = None  # its recipe's command as it runs, in the folder of its output's
    # analysis, with each path relative to that folder. None for a result that isn't built from
    # the working tree alone: a result from a commit, one whose recipe runs on a commit's files,
    # or one that reads a file at a commit, which has no place in the working tree


@dataclass(frozen=True)
class ResolvedAnalysis:
    """An analysis, a valid one, resolved."""

    spec_version: str
    analyses: tuple[Analysis, ...]  # the driving analysis, then each it declares, directly or
    # not, by key
    results: tuple[Result, ...]  # each after every result it reads
    notes: tuple[Diagnostic, ...] = ()  # what an author may want to tidy, which breaks no rule

    def to_json(self) -> dict[str, Any]:
        """The model as JSON (`to_json`)."""
        value: dict[str, Any] = to_json(self)
        return value


def to_json(value: Any) -> Any:
    """A value of the data model as JSON: each class as an object that holds every field under
    its name, one with no value left out."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            each.name: to_json(item)
            for each in fields(value)
            if (item := getattr(value, each.name)) is not None
        }
    if isinstance(value, Mapping):
        return {key: to_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_json(item) for item in value]
    return value
