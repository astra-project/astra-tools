"""check(): each planned result's status, and the status of the evidence that cites one.

A checker reads records only through planned results, which the resolved analysis gives
(`resolve.resolve`), each after what it reads. At each place of a result:

- the record: none is there (`MISSING_RECORD`); it breaks a parse or schema rule, by the record
  schema its minor version picks (`INVALID_RECORD`); its `address` isn't the place's
  (`MISPLACED_RECORD`); its `inputs` aren't one item for each entry its output lists at the
  commit it names (`MISSING_RECORD_INPUTS`). Each leaves the result `missing`, and the last two
  are checked only on a record that breaks neither of the first two;
- the result is then `stale` where something `STALE_RESULT` compares has changed since the
  record's commit, the stack as it was there bound through a CommitReader, from the folder of
  the analysis the result belongs to, or where that commit can't be read or has no such output;
  for each switch an entry reads through, that is the decision it switches on, the option
  selected for it where it is read and the case it takes, whatever bytes result (Results *made
  from*); otherwise it is `unchanged`;
- its bytes are `present` where those at the default place hash to the record's, and `absent`
  otherwise: `ABSENT_RESULT` where it has a valid record.

A result has one status, the worst of its places'. What is wrong with the result itself is in
`Status.why`, a diagnostic for each rule it breaks; that it reads a result that isn't unchanged,
or one made again since with other bytes, is in `Status.stale_inputs`, by entry, and is no
diagnostic of its own, as the reason is the other result's. So a result that is `stale` with no
error in `why` is stale only through what it reads: it is unchanged again once each of those is
built with the bytes its record gives for the entry (Results *made from*), which a runner that
builds them can tell without a second check.

A result of an analysis from a commit is read through its record at the declared commit, in the
analysis it belongs to, and the hashes of the results it reads are taken from their records;
only one that a planned result reads gets a bytes status. Evidence gets the status of the
results it cites (`STALE_EVIDENCE`): the root's, and each item of a declared analysis's evidence
that cites a planned result.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from astra._internal.analysis.resolve import Resolved, input_path, reads, selected
from astra._internal.analysis.rules.context import Context
from astra._internal.analysis.stack import Element, Member, bind
from astra._internal.analysis.universes import Place, Planned, Selection, Step, Through, places
from astra._internal.documents.catalogue import Catalogue
from astra._internal.documents.contract import Contract
from astra._internal.results import hashing
from astra._internal.results.records import read_record
from astra._internal.sources import standins
from astra._internal.sources.git import Repository
from astra._internal.sources.reader import CommitReader
from astra._internal.sources.remote import Remotes
from astra.model.check_report import Bytes, CheckReport, EvidenceStatus, State, Status
from astra.model.diagnostic import Diagnostic, Location
from astra.model.provenance_record import ProvenanceRecord, RecordedInput
from astra.model.resolved_analysis import Result

CODES = frozenset(
    {
        "MISSING_RECORD",
        "INVALID_RECORD",
        "MISPLACED_RECORD",
        "MISSING_RECORD_INPUTS",
        "STALE_RESULT",
        "ABSENT_RESULT",
        "STALE_EVIDENCE",
    }
)
"""The check layer's codes, which this module reports."""

_WORST: tuple[State, ...] = ("missing", "stale", "unchanged")
"""The states, the worst first."""


def check(resolved: Resolved, remotes: Remotes | None = None) -> CheckReport:
    """The status of every planned result of `resolved`, and of the root's evidence and each
    item of a declared analysis's evidence that cites a planned result, its records and bytes
    read where its stack is: in the working tree, or at the commit its root is read at. Commits
    are got from remotes through `remotes`."""
    context, analysis = resolved.context, resolved.analysis
    checker = _Checker(context, Contract.load(context.catalogue), remotes or Remotes())
    # Of the results from a commit, only those a planned result reads get a bytes status, and
    # so ABSENT_RESULT.
    read = {source.result for result in analysis.results for source in result.inputs}
    statuses: dict[str, Status] = {}
    for result, planned in zip(analysis.results, resolved.planned.values(), strict=True):
        has_bytes = planned.owner.commit == context.stack.root.commit or result.id in read
        statuses[result.id] = _worst_of(
            [
                checker.place(result, planned, place, statuses, has_bytes)
                for place in places(context.stack, planned)
            ]
        )
    return CheckReport(analysis, statuses, tuple(_evidence(resolved, statuses)))


def _worst_of(each: list[Status]) -> Status:
    """A result's status, from its status at each of its places."""
    absent = any(status.bytes == "absent" for status in each)
    return Status(
        _worst(status.state for status in each),
        None if each[0].bytes is None else "absent" if absent else "present",
        each[0].record if all(status.record is not None for status in each) else None,
        tuple(diagnostic for status in each for diagnostic in status.why),
        tuple(dict.fromkeys(entry for status in each for entry in status.stale_inputs)),
    )


def _evidence(resolved: Resolved, statuses: Mapping[str, Status]) -> Iterator[EvidenceStatus]:
    """The status of each evidence that cites an output: the root's, and each item of a declared
    analysis's that cites a planned result, as a check covers no other."""
    context = resolved.context
    identities = {key: identity for identity, key in resolved.keys.items()}
    for analysis in resolved.analysis.analyses:
        for insight in (*analysis.prior_insights, *analysis.findings):
            for index, evidence in enumerate(insight.evidence):
                cites = evidence.cites
                if cites is None or (analysis.key and not cites):
                    continue
                state = _worst(statuses[id_].state for id_ in cites)
                if state == "unchanged":
                    yield EvidenceStatus(insight.ref, index, state)
                    continue
                collection, id_ = insight.ref.split(".")[-2:]
                at = context.at(
                    identities[analysis.key], (collection, id_, "evidence", index, "artifact")
                )
                what = (
                    f"cites {', '.join(f'`{cited}`' for cited in cites)}: "
                    f"{'it is' if len(cites) == 1 else 'one of them is'} {state}"
                    if cites
                    else "cites no result: none is planned for it in a universe of the root"
                )
                broken = context.diagnostic("STALE_EVIDENCE", f"the evidence {what}", at)
                yield EvidenceStatus(insight.ref, index, state, (broken,))


@dataclass(frozen=True)
class _Then:
    """A result as the commit its record names has it."""

    context: Context  # the stack bound there, from the folder of the analysis it belongs to
    output: Element  # the output its name names there
    universe: Element | None  # its universe there; None for a result built once
    selection: Selection | None  # its universe's effective selection there; None for a result
    # built once, and where that universe has none


class _Checker:
    """What one check reads, each once: the stacks bound at the records' commits."""

    def __init__(self, context: Context, contract: Contract, remotes: Remotes) -> None:
        self.context = context
        self.stack = context.stack
        self.catalogue: Catalogue = context.catalogue
        self.contract = contract
        self.remotes = remotes
        self.standins = standins.registered()
        self._bound: dict[tuple[Repository, str, str], Context | str] = {}

    def place(
        self,
        result: Result,
        planned: Planned,
        place: Place,
        statuses: Mapping[str, Status],
        has_bytes: bool,
    ) -> Status:
        """The status of `result`, the planned result `planned`, at `place`, from those of the
        results it reads (`statuses`)."""
        member = self.stack.analyses[planned.owner]
        at = _location(member, place.record)
        found = read_record(member.reader, place.record, self.contract)
        why: list[Diagnostic] = []
        stale: list[str] = []
        state: State = "missing"
        record = None
        if found is None:
            message = (
                f"no record is at {place.record}: build `{place.address}`, and record it there"
            )
            why.append(self.catalogue.diagnostic("MISSING_RECORD", message, at))
        elif isinstance(found, tuple):
            for broken in found:
                # A record below 0.1 breaks INVALID_RECORD itself, and no other code says why.
                breaks = "" if broken.code == "INVALID_RECORD" else f" ({broken.code})"
                message = f"{broken.message}{breaks}"
                why.append(self.catalogue.diagnostic("INVALID_RECORD", message, broken.location))
        else:
            if found.address != place.address:
                message = (
                    f"the record's address is `{found.address}`, where this place is "
                    f"`{place.address}`'s: a record is the record only of the result it names"
                )
                why.append(self.catalogue.diagnostic("MISPLACED_RECORD", message, at))
            then = self._then(planned, place, found)
            changes: list[str] = []
            if isinstance(then, str):  # stale, since what it is compared with is gone
                changes = [then]
            else:
                why.extend(self._inputs(found, then, at))
                if not why:
                    changes, stale = self._changes(result, planned, found, then, statuses)
            if not why:
                why.extend(
                    self.catalogue.diagnostic("STALE_RESULT", message, at) for message in changes
                )
                state, record = ("stale" if changes or stale else "unchanged"), found
        bytes_: Bytes | None = None
        if has_bytes:
            bytes_, absent = self._bytes(member, place, record)
            why.extend(absent)
        return Status(state, bytes_, record, tuple(why), tuple(stale))

    def _then(self, planned: Planned, place: Place, record: ProvenanceRecord) -> _Then | str:
        """`planned` as the commit `record` names has it: the stack bound there, from the folder
        of the analysis it belongs to, the output its name at `place` names there, and its
        universe's effective selection there; or why that can't be read, which leaves it
        `stale`."""
        commit = record.generated_by.commit
        member = self.stack.analyses[planned.owner]
        repo, folder = member.reader.holding(member.identity.folder)
        key = (repo, commit, folder)
        if key not in self._bound:
            self._bound[key] = self._bind(repo, commit, folder, member.url)
        context = self._bound[key]
        if isinstance(context, str):
            return context
        output = context.stack.element(place.name, "output")
        if output is None:
            return (
                f"at {commit[:12]}, the commit the record names, `{place.name}` names no output, "
                "so what the result was made from can't be compared"
            )
        universe, selection = None, None
        if planned.universe is not None:
            universe = Element(context.stack.root, "universe", planned.universe.id)
            selection = context.selections.get(universe)
        return _Then(context, output, universe, selection)

    def _bind(self, repo: Repository, commit: str, folder: str, url: str | None) -> Context | str:
        """The stack as it is at `commit` of `repo`, got from `url` where it is a remote's, from
        the analysis in `folder`; or why it can't be read there."""
        got = repo.has_commit(commit) if url is None else self.remotes.get(url, commit) is not None
        if not got:
            where = "the repository that holds its analysis" if url is None else f"`{url}`"
            return (
                f"the record names the commit `{commit}`, which {where} hasn't, so what the "
                "result was made from can't be compared"
            )
        reader = CommitReader(repo, commit, url, self.remotes)
        file = posixpath.join(folder, "astra.yaml")
        entry = reader.stat(file)
        if entry is not None and entry.kind == "file":
            stack, _ = bind(reader, folder, self.catalogue, self.remotes)
            if stack is not None:
                return Context(stack, self.catalogue)
        return (
            f"at {commit[:12]}, the commit the record names, {file} isn't a valid astra.yaml, so "
            "what the result was made from can't be compared"
        )

    def _inputs(self, record: ProvenanceRecord, then: _Then, at: Location) -> Iterator[Diagnostic]:
        """`MISSING_RECORD_INPUTS`: one item of the record's `inputs` for each entry its output
        lists at the record's commit, matched by `entry`, and no other, in any order."""
        listed = then.context.stack.analysis(then.output.analysis).outputs[then.output.id].inputs
        items = [item.entry for item in record.generated_by.inputs]
        commit = record.generated_by.commit[:12]
        found = [
            f"the record has no item for `{entry}`, which its output lists at {commit}"
            for entry in listed
            if entry not in items
        ]
        for entry in dict.fromkeys(items):
            if entry not in listed:
                found.append(
                    f"the record has an item for `{entry}`, which its output doesn't list at "
                    f"{commit}"
                )
            elif items.count(entry) > 1:
                found.append(f"the record has {items.count(entry)} items for `{entry}`, not one")
        for message in found:
            yield self.catalogue.diagnostic("MISSING_RECORD_INPUTS", message, at)

    def _changes(
        self,
        result: Result,
        planned: Planned,
        record: ProvenanceRecord,
        then: _Then,
        statuses: Mapping[str, Status],
    ) -> tuple[list[str], list[str]]:
        """What has changed, since the commit `record` names, of what `STALE_RESULT` compares
        (Results *made from*). First, what has changed of the result itself, each as a message:
        its output's declaration, the options its decisions select in its universe, for each
        switch an entry reads through the decision it switches on, the option selected for it
        and the case it takes, and the content of its inputs. Then each entry that reads a
        result that isn't unchanged, or one made again since with other bytes than the record
        gives for the entry."""
        commit = record.generated_by.commit[:12]
        now = self.stack.analysis(planned.output.analysis).outputs[planned.output.id]
        was = then.context.stack.analysis(then.output.analysis).outputs[then.output.id]
        changes: list[str] = []
        stale: list[str] = []
        assert now.recipe is not None and was.recipe is not None  # a result's output's
        if now.recipe.command != was.recipe.command:
            changes.append(f"its recipe's command isn't the one it had at {commit}")
        if now.inputs != was.inputs:
            changes.append(
                f"its inputs are {_listed(now.inputs)}, in that order, where they were "
                f"{_listed(was.inputs)} at {commit}"
            )
        if set(now.decisions) != set(was.decisions):
            changes.append(
                f"its decisions are {_listed(now.decisions)}, where they were "
                f"{_listed(was.decisions)} at {commit}"
            )
        if now.format != was.format:
            changes.append(f"its format is `{now.format}`, where it was `{was.format}` at {commit}")
        selection = None if planned.universe is None else self.context.selections[planned.universe]
        before = selected(then.context.written[then.output], then.selection)
        for written, option in selected(self.context.written[planned.output], selection).items():
            if written in before and before[written] != option:
                assert planned.universe is not None  # an output built once lists no decisions
                changes.append(
                    f"`{written}` selects {_option(option)} in `{planned.universe.id}`, where it "
                    f"selected {_option(before[written])} at {commit}"
                )
        recorded = {item.entry: item for item in record.generated_by.inputs}
        listed = {  # the output's entries at that commit, by how each is written
            entry.written: entry
            for entry in then.context.written[then.output]
            if entry.field == "inputs"
        }
        for (entry, through), source in zip(
            reads(self.context, planned), result.inputs, strict=True
        ):
            item = recorded.get(source.entry)
            if item is None:  # an entry its output didn't list at that commit: a change above
                continue
            earlier = listed.get(entry.written)
            read_then = (
                None if earlier is None else then.context.meaning.through(earlier, then.universe)
            )
            changes.extend(
                _switched(source.entry, through, read_then, self.context, then.context, commit)
            )
            if source.result is None:
                path = input_path(self.stack, through.target)
                found = self._content(through.target, path)
                if found is None:  # stale, since it can't be compared
                    changes.append(
                        f"the content of `{source.entry}` can't be read at {path}: no file is "
                        "there, or only a stand-in that gives no SHA-256"
                    )
                elif found != _digest(item):
                    changes.append(
                        f"the content of `{source.entry}`, {path}, isn't what the recipe read"
                    )
                continue
            status = statuses[source.result]
            remade = status.record is not None and _digest(status.record) != _digest(item)
            if status.state != "unchanged" or remade:
                stale.append(source.entry)
        return changes, stale

    def _content(self, input_: Element, path: str) -> hashing.Digest | None:
        """The hash and size of `input_`, whose file is at `path`: of the file or, where a
        stand-in is at its path, what the stand-in gives of it, never the stand-in's own; None
        where neither is there, as where a stand-in beside its path gives no SHA-256."""
        reader = self.stack.analyses[input_.analysis].reader
        for standin in self.standins:
            if standin.place(path) == path and standin.recognises(reader, path):
                given = standin.gives(reader, path)
                return None if given is None else hashing.Digest(*given)
        return hashing.digest(reader, path)

    def _bytes(
        self, member: Member, place: Place, record: ProvenanceRecord | None
    ) -> tuple[Bytes, tuple[Diagnostic, ...]]:
        """The bytes' status at `place`, against `record`, the result's record there or None
        where it has none, and `ABSENT_RESULT` where they are absent and it has one."""
        if record is None:  # no recorded bytes, so absent, but no ABSENT_RESULT
            return "absent", ()
        found = hashing.digest(member.reader, place.bytes)
        if found is not None and found == _digest(record):
            return "present", ()
        if found is None:
            message = f"no file is at {place.bytes}, the result's default place"
        else:
            message = f"the bytes at {place.bytes} aren't the ones its record gives"
        at = _location(member, place.bytes)
        return "absent", (self.catalogue.diagnostic("ABSENT_RESULT", message, at),)


def _switched(
    entry: str, now: Through, then: Through | None, here: Context, was: Context, commit: str
) -> list[str]:
    """What has changed, since `commit`, of the switches `entry` reads through, `now` and `then`
    as the stacks `here` and `was` have them: which switches it reads through, each one's
    decision, the option selected for it where it is read, and the case it takes (Results *made
    from*), whatever bytes result. Compared step by step, up to the first whose switch, decision
    or case differs, after which the steps follow other cases."""
    if then is None:
        if not now.steps:
            return []
        return [
            f"`{entry}` reads through {_switches(now.steps)}, where what it read at {commit} isn't "
            "determined there"
        ]
    other = (
        f"`{entry}` reads through {_switches(now.steps)}, where it read through "
        f"{_switches(then.steps)} at {commit}"
    )
    changes: list[str] = []
    for step, before in zip(now.steps, then.steps, strict=False):
        if _which(step) != _which(before):
            return [*changes, other]
        decision = here.stack.switches[step.switch].decision.written
        earlier = was.stack.switches[before.switch].decision.written
        if decision != earlier:
            return [
                *changes,
                f"`{step.switch.id}` switches on `{decision}`, where it switched on `{earlier}` at "
                f"{commit}",
            ]
        if step.option != before.option:
            changes.append(
                f"`{step.switch.id}` switches on `{decision}`, which selects `{step.option}` in "
                f"`{step.universe.id}`, where it selected `{before.option}` at {commit}"
            )
        elif step.case.written != before.case.written:
            changes.append(
                f"`{step.switch.id}`'s case for `{step.option}` is `{step.case.written}`, where it "
                f"was `{before.case.written}` at {commit}"
            )
        if step.case.written != before.case.written:
            return changes  # the steps after follow other cases
    if len(now.steps) != len(then.steps):
        changes.append(other)
    return changes


def _switches(steps: tuple[Step, ...]) -> str:
    """The switches of `steps`, in order, or that there are none."""
    return " then ".join(f"`{step.switch.id}`" for step in steps) or "no switch"


def _which(step: Step) -> tuple[str, str]:
    """A switch, by its analysis's folder and its id, as one stack and another bound at an
    earlier commit both know it."""
    return step.switch.analysis.folder, step.switch.id


def _worst(states: Iterable[State]) -> State:
    """The worst of `states`, `missing` then `stale`; `missing` where there are none."""
    found = set(states)
    return next((state for state in _WORST if state in found), "missing")


def _digest(recorded: ProvenanceRecord | RecordedInput) -> hashing.Digest:
    """The hash and size a record gives, of its result's bytes or of what an entry read."""
    return hashing.Digest(recorded.content_hash, recorded.size)


def _location(member: Member, path: str) -> Location:
    """The file at `path` in `member`'s tree, and the commit and remote it is read at."""
    return Location(path, "", None, None, None, member.identity.commit, member.url)


def _listed(items: Iterable[str]) -> str:
    """`[a, b]`, each in backticks; `none` for no item."""
    found = [f"`{item}`" for item in items]
    return f"[{', '.join(found)}]" if found else "none"


def _option(option: str | None) -> str:
    return "nothing" if option is None else f"`{option}`"
