"""The universes built, what is built in each, and the root's planned results, over which
`NOT_BUILT_IN_UNIVERSE` and `UNDRIVEN_DECLARATION` hold, each with its names.

The stacks are `test_validate`'s worked example; an `output5` reading `subanalysis` in the
root's `u1`, and `upstream`, a remote, in its own `u1` and `v1`, where `v1` drives `inner`, an
analysis in `upstream`'s folder; and `stage.lib.output1#v1`, read through two declarations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astra import api
from astra._internal.analysis.rules.context import Context
from astra._internal.analysis.stack import Element, Identity, bind
from astra._internal.analysis.universes import Building
from astra._internal.documents.catalogue import Catalogue
from astra._internal.sources.git import Repository
from astra._internal.sources.reader import WorktreeReader
from tests.conftest import by_url, repository
from tests.test_validate import WORKED_EXAMPLE

SUBANALYSIS = """\
spec_version: "0.1.0"
analyses:
  inner: {path: inner}
inputs:
  input1: {path: data/input1.csv}
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  output1:
    type: metric
    format: json
    inputs: [input1]
    decisions: [decision1]
    recipe:
      command: python src/output1.py '{inputs.input1}' '{decisions.decision1}' '{output}'
  unread:
    type: metric
    format: json
    decisions: [decision1, inner.decision2]
    recipe:
      command: >-
        python src/unread.py '{decisions.decision1}' '{decisions.inner.decision2}' '{output}'
"""
"""`subanalysis`, which declares `inner`, in its folder, and an output nothing reads, made with
`inner`'s decision, which the universes that drive it then use (Results *uses*)."""

INNER = """\
spec_version: "0.1.0"
inputs:
  input2: {path: data/input2.csv}
decisions:
  decision2:
    options: {a: {}, b: {}}
outputs:
  output2:
    type: metric
    format: json
    inputs: [input2]
    decisions: [decision2]
    recipe:
      command: python src/output2.py '{inputs.input2}' '{decisions.decision2}' '{output}'
"""
"""`subanalysis`'s `inner`, with no universes of its own."""

UPSTREAM = {
    "astra.yaml": SUBANALYSIS
    + """\
universes:
  u1:
    decisions: {decision1: a, inner.decision2: b}
  v1:
    decisions: {decision1: b, inner.decision2: a}
""",
    "data/input1.csv": "2\n",
    "inner/astra.yaml": INNER,
    "inner/data/input2.csv": "3\n",
}
"""The files of `upstream`, a repository of its own: `subanalysis` at its top, whose own
universes drive `inner`."""

ROOT = """\
spec_version: "0.1.0"
analyses:
  subanalysis: {path: subanalysis}
  upstream: %s
inputs:
  input1: {path: data/input1.csv}
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  output1:
    type: metric
    format: json
    inputs: [input1, subanalysis.output1]
    decisions: [decision1]
    recipe:
      command: >-
        python src/output1.py '{inputs.input1}' '{inputs.subanalysis.output1}'
        '{decisions.decision1}' '{output}'
  output5:
    type: table
    format: csv
    inputs:
      - subanalysis.output1#u1               # the root's u1
      - upstream.output1#upstream_u1         # upstream's own u1, imported
      - upstream.output1#v1                  # upstream's own v1
      - upstream.inner.output2#upstream_v1   # inner's output2, as upstream's v1 builds it
    recipe:
      command: python make.py '{output}'
universes:
  u1:
    decisions: {decision1: a, subanalysis.decision1: a}
  u2:
    decisions: {decision1: b, subanalysis.decision1: b}
  upstream_u1: {analysis: upstream, universe: u1}
  upstream_v1: {analysis: upstream, universe: v1}
findings:
  insight1:
    claim: The decision of subanalysis changes its output.
    evidence: [{artifact: subanalysis.output1}]
"""
"""The root, with `output5`, and a finding citing `subanalysis.output1` without a pin; `%s` is
`upstream`'s declaration (`by_url`)."""

ROOT_ID, SUB_ID, INNER_ID = Identity(""), Identity("subanalysis"), Identity("subanalysis/inner")

PINNING = {
    "data/input1.csv": "1\n",
    "subanalysis/astra.yaml": SUBANALYSIS,
    "subanalysis/data/input1.csv": "2\n",
    "subanalysis/inner/astra.yaml": INNER,
    "subanalysis/inner/data/input2.csv": "3\n",
}
"""The files of the stack whose root is `ROOT`, but the root's own."""


def building(top: Path) -> Building:
    stack = bind(WorktreeReader(top, Repository(top)), "")[0]
    assert stack is not None
    return Context(stack, Catalogue.load()).building


def planned(top: Path) -> set[tuple[str, str]]:
    """Each planned result, for each of its names: the analysis it is named from, the universe's
    for a result built in a universe and else its output's, and the name, followed by `#` and
    the universe's own id for a result built in a universe."""
    return {
        (str(result.output.analysis), name)
        if result.universe is None
        else (str(result.universe.analysis), f"{name}#{result.universe.id}")
        for result in building(top).planned.values()
        for name in result.names
    }


def from_commit(top: Path) -> Identity:
    """The analysis read at a commit whose universes are built in the stack whose root is `top`,
    `upstream` or `lib`."""
    (found,) = {u.analysis for u in building(top).universes if u.analysis.commit is not None}
    return found


@pytest.fixture(scope="module")
def worked(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {"astra.yaml": WORKED_EXAMPLE, "data/input1.csv": "1\n"}
    return repository(tmp_path_factory.mktemp("worked"), files)


@pytest.fixture(scope="module")
def pinning(tmp_path_factory: pytest.TempPathFactory) -> Path:
    upstream = by_url(tmp_path_factory.mktemp("upstream"), UPSTREAM)
    files = {**PINNING, "astra.yaml": ROOT % upstream}
    return repository(tmp_path_factory.mktemp("pinning"), files)


def test_the_worked_example_plans_its_three_results(worked: Path) -> None:
    """`output1`'s results in `u1` and in `u2`, and `output2`'s, built once, each
    named by its output's id; `output2` and the finding citing it add none."""
    found = building(worked)
    assert [
        (r.output.id, r.universe and r.universe.id, r.names) for r in found.planned.values()
    ] == [
        ("output1", "u1", ("output1",)),
        ("output1", "u2", ("output1",)),
        ("output2", None, ("output2",)),
    ]
    assert planned(worked) == {(".", "output1#u1"), (".", "output1#u2"), (".", "output2")}
    assert list(found.universes) == [
        Element(ROOT_ID, "universe", "u1"),
        Element(ROOT_ID, "universe", "u2"),
    ]


def test_the_universes_built_are_the_roots_and_those_pins_name(pinning: Path) -> None:
    """The root's universes, and those a pin on an output built per universe names in a planned
    result's `inputs`: `upstream`'s own `u1`, through the import, and `v1`, with no entry `v1`
    in the root's file. In each, its own analysis is the driver, and is built with what its
    universes drive: the root's drive `subanalysis`, and `inner` through it, whose decision they
    don't use; `upstream`'s drive its own `inner`, at its commit."""
    universes = building(pinning).universes
    up = from_commit(pinning)
    up_inner = Identity("inner", up.commit)
    assert {(str(u.analysis), u.id): list(built) for u, built in universes.items()} == {
        (".", "u1"): [ROOT_ID, SUB_ID, INNER_ID],
        (".", "u2"): [ROOT_ID, SUB_ID, INNER_ID],
        (str(up), "u1"): [up, up_inner],
        (str(up), "v1"): [up, up_inner],
    }


def test_each_planned_result_is_named_from_the_analysis_whose_universe_it_is_built_in(
    pinning: Path,
) -> None:
    """The root's outputs, `output5` once; what the root builds of `subanalysis` in its
    universes is named `subanalysis.output1`; `output1` in `upstream`'s own `u1` and `v1` is
    named from `upstream`; its `inner`'s `output2`, built in `v1` through the driven
    `inner: {path: inner}`, is named `inner.output2` there, though the root's own file reads it
    as `upstream.inner.output2#upstream_v1`. The finding cites `subanalysis.output1` in each of
    the root's universes; `unread`, which nothing reads or cites, isn't planned."""
    at = str(from_commit(pinning))
    assert planned(pinning) == {
        (".", "output1#u1"),
        (".", "output1#u2"),
        (".", "output5"),
        (".", "subanalysis.output1#u1"),
        (".", "subanalysis.output1#u2"),
        (at, "output1#u1"),
        (at, "output1#v1"),
        (at, "inner.output2#v1"),
    }


def test_a_stack_read_in_its_own_universes_and_anothers_validates(pinning: Path) -> None:
    """Every pin of `output5` reads a universe where the analysis it reads is built, and
    `inner`, which the root's universes drive by extension, adds no name in them."""
    assert api.validate(pinning).diagnostics == ()


STAGE = """\
spec_version: "0.1.0"
analyses:
  lib: %s
decisions:
  d:
    options: {a: {}, b: {}}
outputs:
  stage_out:
    type: metric
    format: json
    decisions: [d]
    recipe:
      command: python make.py '{decisions.d}' '{output}'
"""
"""`stage`, with no universes, which declares `lib`, `UPSTREAM` at the top of a repository of
its own, by `url` and `commit` (`by_url`)."""

READING_LIB = """\
spec_version: "0.1.0"
analyses:
  stage: {path: stage}
outputs:
  compared:
    type: table
    format: csv
    inputs:
      - stage.lib.output1#v1          # lib's own v1
      - stage.stage_out#lib_v1        # NOT_BUILT_IN_UNIVERSE
    recipe:
      command: python make.py '{output}'
universes:
  lib_v1: {analysis: stage.lib, universe: v1}
"""
"""A root with no universes of its own, reading `stage.lib.output1` and `stage.stage_out` in
`lib`'s `v1`."""


@pytest.fixture(scope="module")
def reading_lib(tmp_path_factory: pytest.TempPathFactory) -> Path:
    lib = by_url(tmp_path_factory.mktemp("lib"), UPSTREAM)
    files = {"astra.yaml": READING_LIB, "stage/astra.yaml": STAGE % lib}
    return repository(tmp_path_factory.mktemp("reading_lib"), files)


def test_a_pin_names_a_universe_of_the_analysis_whose_element_it_reads(
    reading_lib: Path,
) -> None:
    """In a file with no `v1`, `stage.lib.output1#v1` names `lib`'s `v1`, since `output1` is
    `lib`'s output, though it is read through `stage`: it is named `output1` there."""
    lib = from_commit(reading_lib)
    output1 = Element(lib, "output", "output1")
    assert [(key, result.names) for key, result in building(reading_lib).planned.items()] == [
        ((Element(ROOT_ID, "output", "compared"), None), ("compared",)),
        ((output1, Element(lib, "universe", "v1")), ("output1",)),
    ]


def test_a_pin_to_another_analysiss_universe_is_held_by_not_built_in_universe_alone(
    reading_lib: Path,
) -> None:
    """A pin that names another analysis's universe is not in the driver's file, so only
    NOT_BUILT_IN_UNIVERSE holds it. The root's universes drive nothing, yet its pin through
    `stage.lib` breaks no rule; `stage.stage_out#lib_v1` breaks NOT_BUILT_IN_UNIVERSE alone,
    since `lib`'s `v1` doesn't build `stage`."""
    report = api.validate(reading_lib)
    assert [(d.code, d.location.file, d.location.pointer) for d in report.diagnostics] == [
        ("NOT_BUILT_IN_UNIVERSE", "astra.yaml", "/outputs/compared/inputs/1"),
    ]
