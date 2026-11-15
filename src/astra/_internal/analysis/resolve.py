"""resolve(): a valid stack as its resolved analysis (`astra.model.resolved_analysis`).

Everything the model holds is worked out here, from what `universes.py` derives of the stack
(`rules.context.Context`): each analysis under its canonical address, each element under its
ref, each universe's selection, what each evidence cites, and the planned results, each after
every result it reads, with its places, what each entry of its output's `inputs` reads and its
command as it runs.

The model also notes what an author may want to tidy, though it breaks no rule a validator
checks: a pin that names another analysis's universe only because its file has no entry of that
id; an output with no planned result; an output, or a switch that nothing reads, that a switch
leaves unbuilt in a universe, as it has no case there for the option its decision selects
(Elements *switch*); and a command that names a path outside its analysis's folder, or inside an
analysis below it, which is the runner layer's `CODE_OUTSIDE_ANALYSIS`, found here as only the
command's template tells a path it names from one a placeholder gives.

Only a valid stack resolves: one that breaks a `MUST` has no results to give (`read`). The
checker and the history read files the model only names, so `Resolved` keeps, behind the model,
what it was worked out of.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from astra._internal.analysis.rules.context import Context
from astra._internal.analysis.stack import Element, Identity, Member, Resolution, Stack
from astra._internal.analysis.universes import (
    At,
    Planned,
    Selection,
    Through,
    own_universes,
    places,
)
from astra._internal.analysis.validate import validated
from astra._internal.documents import document
from astra._internal.documents.grammar import TEMPLATE, fill
from astra._internal.sources import paths
from astra._internal.sources.reader import worktree
from astra._internal.sources.remote import Remotes
from astra.errors import InvalidAnalysisError
from astra.model.diagnostic import Diagnostic
from astra.model.resolved_analysis import (
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


@dataclass(frozen=True)
class Resolved:
    """A valid stack, resolved: the model, and what it was worked out of."""

    context: Context
    analysis: ResolvedAnalysis
    keys: Mapping[Identity, str]  # each analysis's key in the model
    planned: Mapping[str, Planned]  # behind each result, by id, in the results' order


def read(path: str | os.PathLike[str] | None, remotes: Remotes) -> Resolved:
    """The analysis whose folder is `path`, the current folder by default, resolved: read in the
    working tree of the git repository that holds it. Raises NoAnalysisError where there is no
    analysis, InvalidAnalysisError where the analysis breaks a `MUST`, GitError where git can't
    be run, CacheError where the cache can't be used, and OSError where a file can't be read."""
    report, context = validated(*worktree(path), remotes)
    if not report.valid:
        raise InvalidAnalysisError(report)
    assert context is not None  # a valid analysis has a stack
    return resolve(context)


def resolve(context: Context) -> Resolved:
    """The stack of `context`, a valid one, resolved."""
    stack = context.stack
    keys = _keys(stack)
    ordered = _ordered(context)
    ids = {at: _id(stack, keys, planned) for at, planned in ordered.items()}
    builder = _Builder(context, keys, ids)
    repo = stack.analyses[stack.root].reader.repo
    assert repo is not None  # NOT_IN_REPOSITORY
    analysis = ResolvedAnalysis(
        stack.analysis(stack.root).spec_version,
        repo.head(),
        tuple(builder.analysis(identity) for identity in sorted(keys, key=keys.__getitem__)),
        tuple(builder.result(planned) for planned in ordered.values()),
        tuple(_notes(context)),
    )
    return Resolved(context, analysis, keys, {ids[at]: planned for at, planned in ordered.items()})


def reads(context: Context, result: Planned) -> Iterator[tuple[Resolution, Through]]:
    """Each entry of `result`'s output's `inputs`, in order, with what it reads through the case
    each switch on the way takes (`Meaning.through`): an input, or an output in the universe its
    result is read in."""
    for entry in context.written[result.output]:
        if entry.field == "inputs":
            through = context.meaning.through(entry, result.universe)
            assert through is not None  # what a planned result of a valid stack reads is determined
            yield entry, through


def input_path(stack: Stack, input_: Element) -> str:
    """The file of `input_`, as a path from the top of the tree its analysis is read in."""
    written = stack.analysis(input_.analysis).inputs[input_.id].path
    path = paths.join(input_.analysis.folder, written)
    assert path is not None  # INPUT_OUTSIDE_REPOSITORY
    return path


def selected(entries: tuple[Resolution, ...], selection: Selection | None) -> dict[str, str | None]:
    """Each entry of an output's `decisions`, among the addresses it writes (`entries`), as
    written, and the option `selection`, the effective selection of the universe its result is
    built in, selects for it; None where there is no selection, the entry names nothing or no
    option is selected, as only at a commit a record names, whose stack needn't be valid."""
    return {
        entry.written: None
        if selection is None or entry.element is None
        else min(selection.options(entry.element), default=None)
        for entry in entries
        if entry.field == "decisions"
    }


def _keys(stack: Stack) -> dict[Identity, str]:
    """Each analysis's canonical address: the shortest chain of declarations that reaches it
    from the root, among equals the first in alphabetical order, its ids joined by dots; "" for
    the root."""
    chains: dict[Identity, tuple[str, ...]] = {stack.root: ()}
    reached = [stack.root]
    while reached:
        found: dict[Identity, tuple[str, ...]] = {}
        for owner in reached:
            for id_, declaration in stack.analyses[owner].declarations.items():
                target, chain = declaration.reached, (*chains[owner], id_)
                assert target is not None  # every declaration of a valid stack reaches one
                if target not in chains and (target not in found or chain < found[target]):
                    found[target] = chain
        chains |= found
        reached = list(found)
    return {identity: ".".join(chain) for identity, chain in chains.items()}


def _ordered(context: Context) -> dict[At, Planned]:
    """The planned results, each after every result it reads: no result of a valid stack reads
    itself (`OUTPUT_CYCLE`)."""
    planned = context.building.planned
    found: dict[At, Planned] = {}

    def visit(at: At) -> None:
        if at in found:
            return
        for _, through in reads(context, planned[at]):
            if through.target.kind == "output":
                visit((through.target, through.universe))
        found[at] = planned[at]

    for at in planned:
        visit(at)
    return found


def _id(stack: Stack, keys: Mapping[Identity, str], result: Planned) -> str:
    """A result's id: its first address, after the key of the analysis it belongs to and a colon
    where that isn't the root."""
    address, key = places(stack, result)[0].address, keys[result.owner]
    return f"{key}:{address}" if key else address


def _from_root(stack: Stack, identity: Identity, path: str) -> str:
    """`path`, from the top of the tree `identity` is read in, as the model gives a path: from
    the root's folder, for a file read as the root is; and as it is, in its commit's tree, for
    a file of an analysis read at another commit."""
    if identity.commit != stack.root.commit:
        return path or "."
    return posixpath.relpath(path or ".", stack.root.folder or ".")


class _Builder:
    """What builds the model's analyses and results: the stack, and the names the model gives
    its analyses and results."""

    def __init__(
        self, context: Context, keys: Mapping[Identity, str], ids: Mapping[At, str]
    ) -> None:
        self.context = context
        self.stack = context.stack
        self.keys = keys
        self.ids = ids
        self.artifacts = {
            (entry.file, entry.pointer): entry
            for entry in self.stack.resolutions
            if entry.field == "artifact"
        }

    def ref(self, element: Element) -> str:
        """An element's ref: its analysis's key, its collection and its id."""
        return _ref(self.keys[element.analysis], f"{element.kind}s", element.id)

    def commit(self, identity: Identity) -> Commit | None:
        """The commit `identity` is read at, where that isn't the tree the root is read in."""
        if identity.commit == self.stack.root.commit:
            return None
        assert identity.commit is not None  # only the root's own tree is a working tree
        return Commit(identity.commit, self.stack.analyses[identity].url)

    def analysis(self, identity: Identity) -> Analysis:
        stack, key = self.stack, self.keys[identity]
        member, written = stack.analyses[identity], stack.analysis(identity)
        return Analysis(
            key,
            _from_root(stack, identity, identity.folder),
            self.commit(identity),
            written.label,
            written.description,
            written.tags,
            {id_: self.keys[d.reached] for id_, d in member.declarations.items() if d.reached},
            tuple(
                Input(
                    _ref(key, "inputs", id_),
                    _from_root(stack, identity, input_path(stack, Element(identity, "input", id_))),
                    each.label,
                    each.description,
                    each.tags,
                )
                for id_, each in written.inputs.items()
            ),
            tuple(
                Decision(
                    _ref(key, "decisions", id_),
                    tuple(
                        Option(
                            option_id,
                            option.label,
                            option.description,
                            option.tags,
                            option.excluded,
                            tuple(_ref(key, "prior_insights", cited) for cited in option.insights),
                        )
                        for option_id, option in each.options.items()
                    ),
                    each.label,
                    each.rationale,
                    each.tags,
                )
                for id_, each in written.decisions.items()
            ),
            tuple(
                self.output(Element(identity, "output", id_), each)
                for id_, each in written.outputs.items()
                if not each.is_switch
            ),
            self.insights(identity, "prior_insights", written.prior_insights),
            self.insights(identity, "findings", written.findings),
            tuple(self.universe(universe) for universe in own_universes(stack, identity)),
        )

    def output(self, element: Element, written: document.Output) -> Output:
        assert written.type is not None and written.format is not None  # it isn't a switch
        assert written.recipe is not None
        decisions = dict.fromkeys(
            self.ref(entry.element)
            for entry in self.context.written[element]
            if entry.field == "decisions" and entry.element is not None
        )
        return Output(
            self.ref(element),
            written.type,
            written.format,
            written.label,
            written.description,
            written.tags,
            written.recipe.resources,
            tuple(decisions),
        )

    def universe(self, element: Element) -> Universe:
        """A universe, with the option it selects for each decision it uses, its own analysis
        driving: every one of them has one (`MISSING_DECISION`)."""
        written = self.stack.analysis(element.analysis).universes[element.id]
        selection = self.context.selections[element]
        assert selection is not None  # every universe of a valid stack has one
        chosen = {
            self.ref(decision): min(selection.options(decision))
            for decision in self.context.used(element)
        }
        return Universe(
            self.ref(element),
            dict(sorted(chosen.items())),
            written.label,
            written.description,
            written.tags,
        )

    def insights(
        self,
        identity: Identity,
        collection: str,
        written: Mapping[str, document.Insight],
    ) -> tuple[Insight, ...]:
        return tuple(
            Insight(
                _ref(self.keys[identity], collection, id_),
                "finding" if collection == "findings" else "prior_insight",
                each.claim,
                tuple(
                    Evidence(
                        evidence.doi,
                        evidence.version,
                        self.cited(identity, (collection, id_, "evidence", index, "artifact"))
                        if evidence.artifact is not None
                        else None,
                        evidence.quote,
                        evidence.location,
                    )
                    for index, evidence in enumerate(each.evidence)
                ),
                each.label,
                each.description,
                each.scope,
                each.tags,
            )
            for id_, each in written.items()
        )

    def cited(self, identity: Identity, pointer: tuple[str | int, ...]) -> tuple[str, ...]:
        """The id of each planned result the evidence whose `artifact` is at `pointer` of
        `identity`'s file cites (Results *Evidence*), each once: one where its `artifact` is
        pinned or names an output built once; and otherwise, where it names an output built per
        universe or a switch, in each of the root's universes, its output's result there, or the
        result of the case the switch takes there. None where a switch on the way takes no case,
        or what it reaches has no planned result."""
        entry = self.artifacts[identity, pointer]
        element = entry.element
        assert element is not None  # every address of a valid stack names something
        universes: tuple[Element | None, ...] = (None,)
        per_universe = element.kind == "switch" or element in self.context.per_universe
        if entry.pin is None and per_universe:
            universes = own_universes(self.stack, self.stack.root)
        found: dict[str, None] = {}
        for universe in universes:
            through = self.context.meaning.through(entry, universe)
            if through is not None and (at := (through.target, through.universe)) in self.ids:
                found[self.ids[at]] = None
        return tuple(found)

    def result(self, planned: Planned) -> Result:
        """A planned result, with what each entry of its output's `inputs` reads and, where it
        is built from files read as the root is and no other, its command as it runs."""
        stack, output = self.stack, planned.output
        folder = output.analysis.folder or "."  # where its recipe runs: its output's analysis's
        own = places(stack, planned)
        here = {planned.owner.commit, output.analysis.commit}
        sources: list[Source] = []
        given: dict[str, str] = {}
        for entry, through in reads(self.context, planned):
            target = through.target
            if target.kind == "input":
                sources.append(Source(entry.written, input=self.ref(target)))
                path, read_at = input_path(stack, target), target.analysis.commit
            else:
                at = (target, through.universe)
                sources.append(Source(entry.written, result=self.ids[at]))
                read = self.context.building.planned[at]
                path, read_at = places(stack, read)[0].bytes, read.owner.commit
            here.add(read_at)
            given[entry.written] = posixpath.relpath(path, folder)
        command = None
        if here == {stack.root.commit}:
            recipe = stack.analysis(output.analysis).outputs[output.id].recipe
            assert recipe is not None  # a result's output isn't a switch
            selection = (
                None if planned.universe is None else self.context.selections[planned.universe]
            )
            command = fill(
                recipe.command,
                inputs=given,
                decisions=selected(self.context.written[output], selection),
                output=posixpath.relpath(own[0].bytes, folder),
            )
        return Result(
            self.ids[output, planned.universe],
            self.ref(output),
            tuple(
                Place(
                    place.address,
                    _from_root(stack, planned.owner, place.record),
                    _from_root(stack, planned.owner, place.bytes),
                )
                for place in own
            ),
            None if planned.universe is None else self.ref(planned.universe),
            tuple(sources),
            command,
            self.commit(planned.owner),
        )


def _ref(key: str, collection: str, id_: str) -> str:
    return ".".join(filter(None, (key, collection, id_)))


def _notes(context: Context) -> Iterator[Diagnostic]:
    """What the model notes, each about a file read as the root is, which an author can edit."""
    stack = context.stack
    editable = [
        (member, analysis)
        for member, analysis in stack.determined()
        if member.identity.commit == stack.root.commit
    ]
    found = context.building
    yield from _fallback_pins(context, {entry for entry, _ in found.reads})
    yield from _unplanned(context, {at[0] for at in found.planned}, editable)
    yield from _not_built(context)
    yield from _outside_folder(context, editable)


Editable = list[tuple[Member, document.Analysis]]
"""The analyses read as the root is, with their content."""


def _note(
    context: Context, code: str, message: str, file: Identity, *pointer: str | int
) -> Diagnostic:
    """One of astra-tools' own notes, which no rule of the specification stands behind."""
    return Diagnostic(code, "note", message, context.at(file, pointer))


def _fallback_pins(context: Context, read: set[Resolution]) -> Iterator[Diagnostic]:
    """`FALLBACK_PIN`: each pin a planned result or the root's evidence reads through (`read`),
    in a file read as the root is, that names another analysis's universe only because the
    file's `universes` has no entry of its id, so that adding one would change what it names."""
    stack = context.stack
    for entry, universe in context.pins.items():
        file = entry.file
        if universe is None or file.commit != stack.root.commit or entry not in read:
            continue
        assert entry.pin is not None  # `pins` holds only pinned references
        if entry.pin in stack.analysis(file).universes:
            continue
        message = (
            f"`{entry.written}` names `{entry.pin}` of `{universe.analysis}` only because this "
            f"file has no universe `{entry.pin}`: adding one, or an import of that id, would "
            "change what it names"
        )
        yield _note(context, "FALLBACK_PIN", message, file, *entry.pointer)


def _unplanned(context: Context, planned: set[Element], editable: Editable) -> Iterator[Diagnostic]:
    """`UNPLANNED_OUTPUT`: each output other than a switch of an analysis read as the root is
    with no planned result: an output of a declared analysis that no planned result reads and
    the root's evidence doesn't cite; one of the root's that only a case of its own switches
    names, so that it is planned only where something planned reads it (Results *plans*); or
    another of the root's, built in none of its universes, as where it is built per universe and
    the root has none. A check of the root never covers it."""
    stack = context.stack
    cased: dict[Element, Element] = {}  # each of the root's outputs a case of its own names
    for entry in stack.resolutions:
        if entry.field == "case" and entry.file == stack.root and entry.element is not None:
            assert entry.owner is not None  # the switch whose case it is
            cased.setdefault(entry.element, entry.owner)
    for member, analysis in editable:
        for id_, output in analysis.outputs.items():
            element = Element(member.identity, "output", id_)
            if output.is_switch or element in planned:
                continue
            switch = cased.get(element)
            if member.identity != stack.root:
                why = "no planned result reads it and the root's evidence doesn't cite it"
            elif switch is not None:
                why = (
                    f"only a case of `{switch.id}` names it, so it is planned only where "
                    "something planned reads it, and nothing does"
                )
            elif not own_universes(stack, stack.root):
                why = "it is built per universe and the root has no universes"
            else:
                why = "it is built in none of the root's universes"
            message = (
                f"`{id_}` has no planned result: {why}, so a check of the root never covers it"
            )
            yield _note(context, "UNPLANNED_OUTPUT", message, member.identity, "outputs", id_)


def _not_built(context: Context) -> Iterator[Diagnostic]:
    """`NOT_BUILT`: each output other than a switch that the root's run reaches in a universe
    where it isn't built, and each switch it reaches there that nothing it reaches reads there,
    as one it plans from does (Results *plans*), as a switch on the way, maybe that one, has no
    case there for the option its decision selects (Elements *switch*; Results *built*): one
    note for each output or switch, switch and option, at the entry of `outputs`, with the
    universes. A switch that something reached reads there is left to the note on its reader."""
    reached = context.building.run
    read = {(entry.element, at) for entry, at in reached.reads if entry.field in ("inputs", "case")}
    found: dict[tuple[Element, Element, str], list[Element]] = {}
    for element, universe in reached.reached:
        if universe is None or (element.kind == "switch" and (element, universe) in read):
            continue
        cause = context.meaning.cause(element, universe)
        if cause is not None:
            found.setdefault((element, cause.switch, cause.option), []).append(universe)
    for (output, switch, option), universes in found.items():
        whose = "" if switch.analysis == output.analysis else f" of `{switch.analysis}`"
        which = "it" if switch == output else f"`{switch.id}`{whose}"
        message = (
            f"`{output.id}` isn't built in {context.named(universes, output.analysis)}: "
            f"{which} has no case there for `{option}`, the option its decision selects"
        )
        yield _note(context, "NOT_BUILT", message, output.analysis, "outputs", output.id)


def _outside_folder(context: Context, editable: Editable) -> Iterator[Diagnostic]:
    """`CODE_OUTSIDE_ANALYSIS`: each command of an analysis read as the root is that names a
    path climbing out of the analysis's folder, where the recipe runs, or one inside a folder
    below it that holds an `astra.yaml` of its own: the code a recipe runs is tracked in its
    analysis's folder, outside every analysis below it, or its output's inputs give it. Whether
    a folder holds an `astra.yaml` is read through the analysis's Reader, once for each folder:
    every analysis read as the root is is read in one tree."""
    holds: dict[str, bool] = {}

    def below(member: Member, path: str) -> str | None:
        """The folder below `member`'s, on the way to `path` there, that holds an `astra.yaml`
        of its own, the outermost; None where there is none."""
        folder = member.identity.folder
        inside = paths.join(folder, path)
        assert inside is not None  # a path that climbs out of `folder` isn't read here
        parts = (inside[len(folder) + 1 :] if folder else inside).split("/")[:-1]
        for count in range(1, len(parts) + 1):
            inner = posixpath.join(folder, *parts[:count])
            if inner not in holds:
                entry = member.reader.stat(posixpath.join(inner, "astra.yaml"))
                holds[inner] = entry is not None and entry.kind == "file"
            if holds[inner]:
                return inner
        return None

    for member, analysis in editable:
        for id_, output in analysis.outputs.items():
            if output.recipe is None:  # a switch runs nothing
                continue
            named: list[str] = []
            for path in _paths(output.recipe.command):
                if _climbs(path):
                    named.append(f"`{path}`, outside its analysis's folder")
                elif (inner := below(member, path)) is not None:
                    named.append(f"`{path}`, inside `{inner}`, which holds an analysis of its own")
            if not named:
                continue
            message = (
                f"the command names {'; '.join(named)}: a recipe should run only code tracked in "
                "its analysis's folder, outside every folder below it that holds an analysis of "
                "its own, or that its output's inputs give it"
            )
            at = context.at(member.identity, ("outputs", id_, "recipe", "command"))
            yield context.diagnostic("CODE_OUTSIDE_ANALYSIS", message, at)


_WORD = re.compile(r"[^\s=:;&|<>()'\"`,]+")
"""A run of characters that can make up a path in a shell command: what lies between blanks,
quotes, `=` and `:` (as in `--flag=path` and `PYTHONPATH=a:b`), and the shell's operators."""


def _paths(command: str) -> list[str]:
    """Each path `command` names outside its placeholders, once, read from the left. A path
    from a placeholder starts elsewhere, and an absolute path names no folder of the analysis,
    so neither is read."""
    marked = TEMPLATE.sub(lambda match: "\0" if match[1] is not None else match[0][0], command)
    found: list[str] = []
    for word in _WORD.findall(marked):
        if "\0" not in word and not word.startswith("/") and word not in found:
            found.append(word)
    return found


def _climbs(path: str) -> bool:
    """Whether `path` climbs out of the folder it is read from: its `..` outnumber the folders
    before them, read from the left."""
    depth = 0
    for part in path.split("/"):
        depth += -1 if part == ".." else int(part not in ("", "."))
        if depth < 0:
            return True
    return False
