"""resolve(): the root's planned results, each after every result it reads, with what its
files say of each.

A thin layer over `universes.building`, which gives the planned results, their names and the
universe each entry reads in: each result here adds its owner and places, what each entry of its
output's `inputs` reads, the option each entry of its `decisions` selects, its command, the
folder its recipe runs in and what the recipe asks for, and whether it is a result from a
commit or, driven, made on a commit's files. Through a switch, an entry reads what the case the
switch takes names (Elements *takes*), which its read records.

Resolving says what the analysis's files mean, and nothing of a run. Which results to build, in
what order, in which checkout and with which paths in their commands is a runner's to say:
`grammar.fill` fills a command with the paths the runner gives it.

The resolved analysis also notes what an author may want to tidy, though it breaks no rule: a
pin that names another analysis's universe only because its file has no entry of that id, an
output with no planned result, an output, or a switch that nothing reads, that a switch leaves
unbuilt in a universe, as it has no case there for the option its decision selects (Elements
*switch*), and a command that names a path outside its analysis's folder, or inside an analysis
below it (`CODE_OUTSIDE_ANALYSIS`).

`api.resolve` resolves only a valid stack: one that breaks a `MUST` has no results to give. On
such a stack, `resolve` gives the results whose planning is determined, for `check`. Every path
is a path from the top of the tree its analysis is read in: the root's working tree
(`Resolved.top`), or the repository a commit is read in.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

from astra.diagnostics import Catalogue, Location
from astra.grammar import TEMPLATE
from astra.model import Analysis, Resources
from astra.rules.context import Context
from astra.sources import paths
from astra.sources.reader import WorktreeReader
from astra.stack import Element, Identity, Member, Resolution, Stack
from astra.universes import (
    Building,
    Place,
    Planned,
    Run,
    Selection,
    Through,
    along,
    built,
    own_universes,
    places,
)
from astra.view import UniverseView, view

Key = tuple[Element, Element | None]
"""What names a planned result in a resolved analysis: its output, and the universe it is built
in, None for an output built once."""


@dataclass(frozen=True)
class Read:
    """One entry of an output's `inputs`, as written, and what it reads: an input's file, or a
    planned result's bytes, through the case each switch on the way takes (Elements *takes*)."""

    entry: str
    path: str  # the input's file, or the default place of the result's bytes
    commit: str | None  # the commit `path` is read at; None for the working tree
    result: Key | None  # the planned result it reads, by its key (`Resolved.result`); None for
    # an input
    place: Place | None  # the place of the result's name whose bytes it reads; None for an input
    via: tuple[str, ...] = ()  # each case taken on the way, as written, in order; () where the
    # entry names no switch


@dataclass(frozen=True)
class Result:
    """A planned result (Results *plans*), with what its files say of it. It is plain data: what
    it reads is named by key, so one result pickles, compares and prints by itself, without the
    results it reads."""

    names: tuple[str, ...]
    owner: Identity  # the analysis it belongs to
    output: Element
    universe: Element | None  # the universe it is built in; None for an output built once
    places: tuple[Place, ...]  # one for each name
    inputs: tuple[Read, ...]  # one for each entry of its output's `inputs`, in their order
    decisions: Mapping[str, str | None]  # each entry of its output's `decisions`, and its option
    command: str  # its recipe's `command`, a template (`grammar.fill`)
    workdir: str  # the folder its recipe runs in: its output's analysis's
    from_commit: bool  # a result from a commit (Results): it belongs to an analysis read at
    # another commit than the root's, one from a commit or reached from it, so it is never
    # rebuilt, and is read through its record
    run_at: str | None  # for a driven analysis from a commit, the commit whose files its recipe
    # runs on (`NOT_AT_COMMIT`); never the commit its record names, which is the driver's
    resources: Resources | None  # what its recipe asks for

    @property
    def key(self) -> Key:
        """What names it among the planned results: its output and its universe."""
        return (self.output, self.universe)


NoteKind = Literal["fallback_pin", "unplanned", "not_built", "outside_folder"]


@dataclass(frozen=True)
class Note:
    """Something an author may want to tidy, which breaks no rule."""

    kind: NoteKind
    message: str
    location: Location  # the pin, the output or the command
    built: bool = True  # it concerns what the root builds: False only for a `fallback_pin` that no
    # planned result reads through, as the root builds every analysis of a stack it can resolve
    universes: tuple[Element, ...] = ()  # for `not_built`, the universes the output isn't built in
    switch: Element | None = None  # for `not_built`, the switch with no case there
    option: str | None = None  # for `not_built`, the option its decision selects there


@dataclass(frozen=True)
class Resolved:
    """An analysis resolved: its planned results, each after every result it reads, and the notes
    on them."""

    top: Path | None  # the top of the working tree every path is measured from; None where the
    # root is read at a commit, whose paths are in that commit's tree
    root: str  # the root's astra.yaml, as a Location's `file` names it
    results: tuple[Result, ...]
    notes: tuple[Note, ...]
    context: Context = field(repr=False, compare=False)  # the stack, and what is worked out of it

    @property
    def analysis(self) -> Analysis:
        """The root's `astra.yaml`, as it is written: its label, its description, its elements."""
        return self.context.stack.analysis(self.context.stack.root)

    @cached_property
    def _by_key(self) -> Mapping[Key, Result]:
        return {result.key: result for result in self.results}

    def result(self, key: Key) -> Result:
        """The planned result `key` names, as a `Read.result` does."""
        return self._by_key[key]

    def view(self, universe: str) -> UniverseView:
        """The analysis, a valid one, as it is in the root's universe `universe` (`view.view`).
        Raises RequestError where the root has no such universe."""
        return view(self.context, universe)


def resolve(stack: Stack) -> Resolved:
    """`stack` resolved: its planned results, each after every result it reads. Where `stack`
    breaks a `MUST`, those whose planning is determined: a result is left out where an entry of
    its output's `inputs` names nothing, gives an input's path above the top, names an output
    with no result planned there (`NOT_BUILT_IN_UNIVERSE`), or reads a result that is left out
    or that reads it back (`OUTPUT_CYCLE`), as `check` reads them."""
    context = Context(stack, Catalogue.load())
    found = context.building
    made: dict[Key, Result] = {}
    left: set[Key] = set()  # left out, or being made: a result that reads it back is left out

    def visit(result: Planned) -> bool:
        """Make `result` after every result it reads, unless its planning isn't determined."""
        key = (result.output, result.universe)
        if key in made or key in left:
            return key in made
        left.add(key)
        reads = _reads(context, found.planned, result)
        if reads is None or not all(isinstance(read, str) or visit(read) for _, _, read in reads):
            return False
        left.remove(key)
        made[key] = _result(context, result, reads, made)
        return True

    for result in found.planned.values():
        visit(result)
    root = stack.analyses[stack.root]
    top = root.reader.top if isinstance(root.reader, WorktreeReader) else None
    return Resolved(top, root.file, tuple(made.values()), _notes(context, found), context)


Reads = tuple[tuple[Resolution, Through, Planned | str], ...]
"""Each entry of an output's `inputs`, what it reads through the case each switch on the way
takes, and that: a planned result, or an input's file, as a path from the top."""


def _reads(context: Context, planned: Mapping[Key, Planned], result: Planned) -> Reads | None:
    """What each entry of `result`'s output's `inputs` reads, through the case each switch on
    the way takes (`Meaning.through`): an input's file, in the folder of the input's analysis,
    or a planned result. None where what one reads isn't determined, as only on a stack that
    breaks a `MUST`: it names nothing, gives a path above the top, reads through a switch that
    is undetermined or takes nothing, or names an output with no result planned there."""
    reads: list[tuple[Resolution, Through, Planned | str]] = []
    for entry in context.written[result.output]:
        if entry.field != "inputs":
            continue
        if entry.element is None:
            return None
        through = context.meaning.through(entry, result.universe)
        if through is None:
            return None
        read: Planned | str | None
        if through.target.kind == "input":
            target = through.target
            written = context.stack.analysis(target.analysis).inputs[target.id].path
            read = paths.join(target.analysis.folder, written)
        else:
            read = planned.get((through.target, through.universe))
        if read is None:
            return None
        reads.append((entry, through, read))
    return tuple(reads)


def _result(context: Context, result: Planned, reads: Reads, made: Mapping[Key, Result]) -> Result:
    """`result` with what its files say of it, from the results it reads, already `made`."""
    stack, identity = context.stack, result.output.analysis
    inputs: list[Read] = []
    for entry, through, read in reads:
        via = tuple(step.case.written for step in through.steps)
        if isinstance(read, str):
            commit = through.target.analysis.commit
            inputs.append(Read(entry.written, read, commit, None, None, via))
            continue
        done = made[read.output, read.universe]
        # The name along the entry's declarations, then each case's, from the analysis `read`
        # belongs to, after `result`'s first chain where `result` belongs there too, or else the
        # first.
        start = result.chains[0] if result.owner == read.owner else ()
        index = along(read, (*start, *through.chain))
        place = done.places[0 if index is None else index]
        inputs.append(Read(entry.written, place.bytes, done.owner.commit, done.key, place, via))
    selection = None if result.universe is None else context.selections[result.universe]
    from_commit = result.owner.commit != stack.root.commit
    analysis = stack.analysis(identity)
    recipe = analysis.outputs[result.output.id].recipe
    assert recipe is not None  # a result's output isn't a switch
    return Result(
        result.names,
        result.owner,
        result.output,
        result.universe,
        places(stack, result),
        tuple(inputs),
        selected(context.written[result.output], selection),
        recipe.command,
        identity.folder,
        from_commit,
        None if from_commit or identity.commit == stack.root.commit else identity.commit,
        recipe.resources,
    )


def _notes(context: Context, found: Building) -> tuple[Note, ...]:
    """What the resolved analysis notes, kind by kind, each about the files read where the root is,
    which an author can edit. `fallback_pin`, `unplanned` and `outside_folder` notes say whether
    they concern what the root builds (`Note.built`): the root, and every analysis its universes
    drive (`built`). In a stack that resolves, that is every analysis: one whose decisions a
    universe of the root uses is built there (`NOT_BUILT_IN_UNIVERSE`), and one with none it uses
    has nothing to set, so is driven without a key (Elements). Only a `fallback_pin` that no
    planned result reads through concerns something else."""
    stack = context.stack
    editable = [
        (member, analysis)
        for member, analysis in stack.determined()
        if member.identity.commit == stack.root.commit
    ]
    builds = frozenset(built(context.driven[stack.root], stack.root))
    return (
        *_fallback_pins(context, {entry for entry, _ in found.reads}),
        *_unplanned(context, found.planned, editable, builds),
        *_not_built(context, found.run),
        *_outside_folder(context, editable, builds),
    )


Editable = list[tuple[Member, Analysis]]
"""The analyses read where the root is, with their content."""


def _fallback_pins(context: Context, read: set[Resolution]) -> Iterator[Note]:
    """Each pin in a file read where the root is that names another analysis's universe only
    because the file's `universes` has no entry of its id, so that adding one would change what
    it names. It concerns what the root builds where a planned result reads through it (`read`): an
    entry of a planned result's `inputs`, or of the root's evidence."""
    stack = context.stack
    for entry, universe in context.pins.items():
        file = entry.file
        if universe is None or file.commit != stack.root.commit:
            continue
        assert entry.pin is not None  # `pins` holds only pinned references
        if entry.pin in stack.analysis(file).universes:
            continue
        message = (
            f"`{entry.written}` names `{entry.pin}` of `{universe.analysis}` only because this "
            f"file has no universe `{entry.pin}`: adding one, or an import of that id, would "
            "change what it names"
        )
        at = context.at(file, entry.pointer)
        yield Note("fallback_pin", message, at, built=entry in read)


def _unplanned(
    context: Context,
    planned: Mapping[Key, Planned],
    editable: Editable,
    builds: frozenset[Identity],
) -> Iterator[Note]:
    """Each output other than a switch of an analysis read where the root is with no planned
    result: an output of a declared analysis that no planned result reads and the root's
    evidence doesn't cite; one of the root's that only a case of its own switches names, so that
    it is planned only where something planned reads it (Results *plans*); or another of the
    root's, built in none of its universes, as where it is built per universe and the root has
    none. A check of the root never covers it. It concerns what the root builds where its
    analysis is one of `builds`; an analysis the root only reads from isn't its business."""
    stack = context.stack
    outputs = {key[0] for key in planned}
    cased: dict[Element, Element] = {}  # each of the root's outputs a case of its own names
    for entry in stack.resolutions:
        if entry.field == "case" and entry.file == stack.root and entry.element is not None:
            assert entry.owner is not None  # the switch whose case it is
            cased.setdefault(entry.element, entry.owner)
    for member, analysis in editable:
        for id_, output in analysis.outputs.items():
            element = Element(member.identity, "output", id_)
            if output.is_switch or element in outputs:
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
            at = context.at(member.identity, ("outputs", id_))
            yield Note("unplanned", message, at, built=member.identity in builds)


def _not_built(context: Context, reached: Run) -> Iterator[Note]:
    """Each output other than a switch that the root's run reaches in a universe where it isn't
    built, and each switch it reaches there that nothing it reaches reads there, as one it plans
    from does (Results *plans*), as a switch on the way, maybe that one, has no case there for
    the option its decision selects (Elements *switch*; Results *built*): one note for each
    output or switch, switch and option, at the entry of `outputs`, with the universes. A switch
    that something reached reads there is left to the note on its reader. A missing case breaks
    no rule: this is the resolved analysis's own report of it."""
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
        at = context.at(output.analysis, ("outputs", output.id))
        yield Note(
            "not_built", message, at, universes=tuple(universes), switch=switch, option=option
        )


def _outside_folder(
    context: Context, editable: Editable, builds: frozenset[Identity]
) -> Iterator[Note]:
    """Each command of an analysis read where the root is that names a path climbing out of the
    analysis's folder, where the recipe runs, or one inside a folder below it that holds an
    `astra.yaml` of its own: the code a recipe runs is tracked in its analysis's folder, outside
    every analysis below it, or its output's inputs give it (`CODE_OUTSIDE_ANALYSIS`). Whether
    a folder holds an `astra.yaml` is read through the analysis's Reader, once for each folder:
    every analysis read where the root is is read in one tree. It concerns what the root builds
    where its analysis is one of `builds`."""
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
                "its own, or that its output's inputs give it (`CODE_OUTSIDE_ANALYSIS`)"
            )
            pointer = ("outputs", id_, "recipe", "command")
            at = context.at(member.identity, pointer)
            yield Note("outside_folder", message, at, built=member.identity in builds)


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


def selected(entries: Iterable[Resolution], selection: Selection | None) -> dict[str, str | None]:
    """Each entry of an output's `decisions`, among the addresses it writes (`entries`), as
    written, and the option `selection`, the effective selection of the universe its result is
    built in, selects for it; None where there is no selection, the entry names nothing or no
    option is selected (never, on a valid stack: `MISSING_DECISION`)."""
    return {
        entry.written: None
        if selection is None or entry.element is None
        else min(selection.options(entry.element), default=None)
        for entry in entries
        if entry.field == "decisions"
    }
