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
from dataclasses import dataclass, field
from typing import Any, Literal

from astra.model import to_json
from astra.model.diagnostic import Diagnostic


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
class Resources:
    """What a recipe asks for."""

    cpus: float | None = None
    memory: str | None = None
    time_limit: str | None = None
    disk: str | None = None
    gpus: int | None = None


@dataclass(frozen=True)
class AuthoredReference:
    """An authored dependency, before switches are evaluated; pins name canonical universes."""

    entry: str
    target: str
    universe: str | None = None


@dataclass(frozen=True)
class Switch:
    """An authored switch, including cases that no planned result reaches."""

    ref: str
    decision: str
    cases: Mapping[str, AuthoredReference]


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
    inputs: tuple[AuthoredReference, ...] | None = None  # absent in older reports


@dataclass(frozen=True)
class TextQuoteSelector:
    """A passage quoted exactly."""

    exact: str
    prefix: str | None = None
    suffix: str | None = None


@dataclass(frozen=True)
class FragmentSelector:
    """A place in a work or an output, as a fragment identifier."""

    value: str
    conforms_to: str | None = None


@dataclass(frozen=True)
class EvidenceBinding:
    """One evaluation of artifact evidence. No output means a switch took no case.

    `universe` is the evaluation context (or the authored pin); absent means independent
    of the selected universe. `target_universe` is the effective output's universe after
    following switches and pins; absent for an output built once. A target need not be planned.
    """

    universe: str | None = None
    output: str | None = None
    target_universe: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class Evidence:
    """What a claim rests on: a work by DOI, or an artifact address and its cited results."""

    doi: str | None = None
    version: int | None = None
    cites: tuple[str, ...] | None = None  # for evidence that cites an output, the id of each
    # result it cites (Results *Evidence*): empty where no result is planned; None for a DOI
    quote: TextQuoteSelector | None = None
    location: FragmentSelector | None = None
    artifact: str | None = None  # the authored address, scoped to the insight's analysis;
    # retained even where no result is planned, including a switch or a universe pin
    bindings: tuple[EvidenceBinding, ...] | None = None  # artifact evaluations; absent for DOI


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
    switches: tuple[Switch, ...] | None = None  # authored graph; absent in older reports


@dataclass(frozen=True)
class Source:
    """What one entry of an output's `inputs` reads for a result: an input, or another result,
    through any pin and the case each switch on the way takes."""

    entry: str  # as the output's `inputs` writes it
    input: str | None = None  # the input it reads, by ref
    result: str | None = None  # or the result it reads, by id


@dataclass(frozen=True)
class Place:
    """Where one name of a result is kept (Results *place*)."""

    address: str  # the name, then `#` and the universe's id for a result built in one
    record_path: str
    file_path: str  # the result's file, where the specification puts its bytes by default: a
    # stand-in may be there in their place, as `Status.bytes` says


@dataclass(frozen=True)
class Result:
    """A result: one output, in one universe or once. The results are those the driving analysis
    builds and those they read, which the specification says it plans (Results *plans*)."""

    id: str
    output: str  # by ref
    places: tuple[Place, ...]  # one, unless its analysis is driven through two chains
    universe: str | None = None  # by ref; None for an output built once
    inputs: tuple[Source, ...] = ()  # one for each entry of its output's `inputs`, in order
    command: str | None = None  # its recipe's command as it runs, in the folder of its output's
    # analysis, with each path relative to that folder. None for a result that isn't built from
    # the working tree alone: a result from a commit, one whose recipe runs on a commit's files,
    # or one that reads a file at a commit, which has no place in the working tree
    commit: Commit | None = None  # the commit whose tree its places are in, where the analysis
    # it belongs to is read at one: a result from a commit, which is never built, and whose
    # record is the one at that commit. None for a result whose places are in the working tree


@dataclass(frozen=True)
class ResolvedAnalysis:
    """An analysis, a valid one, resolved."""

    spec_version: str
    head: str | None  # the commit its repository is on, as HEAD names it: None where it has no
    # commit yet. It names the commit and not the files, which are read in the working tree
    analyses: tuple[Analysis, ...]  # the driving analysis, then each it declares, directly or
    # not, by key
    results: tuple[Result, ...]  # each after every result it reads
    notes: tuple[Diagnostic, ...] = ()  # what an author may want to tidy, which breaks no rule
    schema_version: Literal["astra-tools.resolved-analysis.v1"] = field(
        default="astra-tools.resolved-analysis.v1", init=False
    )

    def to_json(self) -> dict[str, Any]:
        """The model as JSON (`astra.model.to_json`)."""
        value: dict[str, Any] = to_json(self)
        return value
