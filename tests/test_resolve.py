"""The resolved analysis: the planned results, each after what it reads, with their names,
owners, places, inputs, decisions and commands; the results of an analysis from a commit, read
through their records or run at its commit; what the resolved analysis notes; and `api.resolve`.

The stacks are a worked example; astra-spec's `examples/iris_pipeline`; `output5` reading
`subanalysis` in three universes, where `subanalysis`'s own `v1` drives its parent, with an
output of every placeholder; an analysis with a declaration no key drives, whose outputs
nothing reads; `inner` reached through `inner` and `stage.inner`; an analysis from a commit,
driven and pinned; an analysis whose recipes ask for resources; and one with each note a stack
read where the root is can have.
"""

from __future__ import annotations

import pickle
import shutil
from pathlib import Path

import pytest

from astra import api
from astra.model import Resources
from astra.resolve import Resolved
from astra.stack import Identity
from tests.conftest import MINIMAL, git, rendered, repository
from tests.spec import SPEC
from tests.test_planned import ROOT, SUBANALYSIS
from tests.test_validate import WORKED_EXAMPLE


def results(resolved: Resolved) -> list[tuple[str, str]]:
    """Each result, in the order resolved: the analysis it belongs to, and its addresses."""
    return [(str(r.owner), ", ".join(p.address for p in r.places)) for r in resolved.results]


def each_after_what_it_reads(resolved: Resolved) -> bool:
    built: set[object] = set()
    for result in resolved.results:
        for read in result.inputs:
            if read.result is not None and read.result not in built:
                return False
        built.add(result.key)
    return True


# --- The worked example ---


@pytest.fixture(scope="module")
def worked(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {"astra.yaml": WORKED_EXAMPLE, "data/input1.csv": "1\n"}
    return repository(tmp_path_factory.mktemp("worked"), files)


def test_the_worked_example_plans_its_three_results_at_their_places(worked: Path) -> None:
    """`output1` in `u1` and in `u2`, then `output2`, which reads both, each with its record at
    its place and its bytes at its default place, and its command as its file writes it, a
    template."""
    resolved = api.resolve(worked)
    assert [
        (r.names, r.universe and r.universe.id, [(p.record, p.bytes) for p in r.places])
        for r in resolved.results
    ] == [
        (("output1",), "u1", [(".astra/records/u1/output1.json", "results/u1/output1.json")]),
        (("output1",), "u2", [(".astra/records/u2/output1.json", "results/u2/output1.json")]),
        (("output2",), None, [(".astra/records/output2.json", "results/output2.csv")]),
    ]
    assert each_after_what_it_reads(resolved)
    one, two, compared = resolved.results
    assert [(r.owner, r.workdir, r.from_commit, r.run_at) for r in resolved.results] == [
        (Identity(""), "", False, None)
    ] * 3
    assert [(read.entry, read.path, read.commit, read.result) for read in one.inputs] == [
        ("input1", "data/input1.csv", None, None)
    ]
    assert (dict(one.decisions), dict(two.decisions), dict(compared.decisions)) == (
        {"decision1": "a"},
        {"decision1": "b"},
        {},
    )
    assert [(read.entry, read.path, read.result) for read in compared.inputs] == [
        ("output1#u1", "results/u1/output1.json", one.key),
        ("output1#u2", "results/u2/output1.json", two.key),
    ]
    assert compared.command == (
        "python src/output2.py '{inputs.output1#u1}' '{inputs.output1#u2}' '{output}'"
    )


def test_the_resolved_analysis_gives_the_top_its_paths_are_from(
    worked: Path, pinning: Path
) -> None:
    """Every path is from the top of the working tree the root is read in, which `top` gives:
    the repository's, also for an analysis in a folder below it, whose file `root` names from
    there."""
    resolved = api.resolve(worked)
    assert (resolved.top, resolved.root) == (worked.resolve(), "astra.yaml")
    below = api.resolve(pinning / "subanalysis")
    assert (below.top, below.root) == (pinning.resolve(), "subanalysis/astra.yaml")


def test_a_planned_result_pickles_by_itself(worked: Path) -> None:
    """A planned result is plain data, which a runner can hand to another process. It names
    what it reads by key (`Result.key`), which the resolved analysis looks up
    (`Resolved.result`), so its pickle holds nothing of the results it reads."""
    resolved = api.resolve(worked)
    one, two, compared = resolved.results
    for result in resolved.results:
        assert pickle.loads(pickle.dumps(result)) == result
        assert resolved.result(result.key) is result
    assert [resolved.result(read.result) for read in compared.inputs if read.result] == [one, two]
    assert one.command.encode() not in pickle.dumps(compared)


def test_the_worked_examples_commands_fill_in_with_what_each_result_reads(worked: Path) -> None:
    """`{decisions.decision1}` is `a` in `u1` and `b` in `u2`, `output2` reads
    the paths of both results, and `{output}` is where each result is written."""
    assert [rendered(result) for result in api.resolve(worked).results] == [
        "python src/output1.py 'data/input1.csv' 'a' 'results/u1/output1.json'",
        "python src/output1.py 'data/input1.csv' 'b' 'results/u2/output1.json'",
        "python src/output2.py 'results/u1/output1.json' 'results/u2/output1.json' "
        "'results/output2.csv'",
    ]


# --- examples/iris_pipeline ---


IRIS = {
    (".", "iris_data"),
    (".", "comparison"),
    (".", "split#baseline"),
    (".", "split#mlp_svm"),
    (".", "summary#baseline"),
    (".", "summary#mlp_svm"),
    (".", "classification.accuracy#baseline"),
    (".", "classification.accuracy#mlp_svm"),
    (".", "classification.predictions#baseline"),
    (".", "classification.predictions#mlp_svm"),
    (".", "feature_extraction.features#baseline"),
    (".", "feature_extraction.features#mlp_svm"),
}
"""The planned results of `examples/iris_pipeline`: the root's outputs, `iris_data` and
`comparison` built once and the others in each of its universes; what `summary` and
`comparison` read, `classification`'s `accuracy` and, through it, `predictions`, in each
universe; and what `predictions` reads, `feature_extraction`'s `features` and the root's own
`split`. The root's universes drive both stages, so each result built in them is the root's,
named through the one driven declaration to its analysis: `classification.feature_extraction`
and the stages' `iris: {path: ..}` aren't driven and add no name. `iris_data` is read by `split`
and, as `iris.iris_data`, by `features`; `feature_plot`, which nothing reads, isn't planned."""


def test_iris_pipeline_plans_with_its_results_names_and_owners(tmp_path: Path) -> None:
    shutil.copytree(SPEC / "examples" / "iris_pipeline", tmp_path / "pipeline")
    resolved = api.resolve(repository(tmp_path / "pipeline", {}))
    assert len(resolved.results) == len(IRIS)
    assert set(results(resolved)) == IRIS
    assert each_after_what_it_reads(resolved)
    by_address = {result.places[0].address: result for result in resolved.results}
    features = by_address["feature_extraction.features#mlp_svm"]
    assert (features.workdir, features.places[0].bytes) == (
        "feature_extraction",
        "results/mlp_svm/feature_extraction.features.npy",
    )
    assert dict(features.decisions) == {
        "method": "mlp_encoder",
        "n_components": "two",
        "iris.random_seed": "seed_42",
    }
    predictions = by_address["classification.predictions#mlp_svm"]
    assert [(read.entry, read.path) for read in predictions.inputs] == [
        ("feature_extraction.features", "results/mlp_svm/feature_extraction.features.npy"),
        ("iris.split", "results/mlp_svm/split.json"),
    ]
    assert predictions.inputs[1].result == by_address["split#mlp_svm"].key


# --- output5, parent.output1, and the placeholders ---


PLACEHOLDERS = """\
  output3:
    type: table
    format: csv
    inputs: [input1, subanalysis.output1, output1#u1]
    decisions: [subanalysis.decision1]
    recipe:
      command: >-
        python make.py {{x}} '{inputs.input1}' '{inputs.subanalysis.output1}'
        '{inputs.output1#u1}' '{decisions.subanalysis.decision1}' {inputs} '{output}' }}
"""
"""An output of every placeholder, the entries with dots and `#`, `{{` and `}}`."""


@pytest.fixture(scope="module")
def pinning(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {
        "astra.yaml": ROOT.replace("universes:\n", PLACEHOLDERS + "universes:\n", 1),
        "data/input1.csv": "1\n",
        "subanalysis/astra.yaml": SUBANALYSIS,
        "subanalysis/data/input1.csv": "2\n",
    }
    return repository(tmp_path_factory.mktemp("pinning"), files)


def test_output5s_three_pins_read_three_results_each_in_its_owners_folder(pinning: Path) -> None:
    """`subanalysis.output1#u1` reads the root's result, named `subanalysis.output1`;
    `#subanalysis_u1` and `#v1` read `subanalysis`'s own, in its folder under its universes' own
    ids; `output1#subanalysis_v1` reads the root's `output1` as `subanalysis`'s `v1` builds it,
    through `parent: {path: ..}`, named `parent.output1` there, which runs in the root's folder."""
    resolved = api.resolve(pinning)
    assert set(results(resolved)) == {
        (".", "output1#u1"),
        (".", "output1#u2"),
        (".", "output3#u1"),
        (".", "output3#u2"),
        (".", "output5"),
        (".", "subanalysis.output1#u1"),
        (".", "subanalysis.output1#u2"),
        ("subanalysis", "output1#u1"),
        ("subanalysis", "output1#v1"),
        ("subanalysis", "parent.output1#v1"),
    }
    assert each_after_what_it_reads(resolved)
    (output5,) = [result for result in resolved.results if result.names == ("output5",)]
    assert [(read.entry, read.path) for read in output5.inputs] == [
        ("subanalysis.output1#u1", "results/u1/subanalysis.output1.json"),
        ("subanalysis.output1#subanalysis_u1", "subanalysis/results/u1/output1.json"),
        ("subanalysis.output1#v1", "subanalysis/results/v1/output1.json"),
        ("output1#subanalysis_v1", "subanalysis/results/v1/parent.output1.json"),
    ]
    reads = [resolved.result(read.result) for read in output5.inputs if read.result is not None]
    assert [str(result.owner) for result in reads] == [
        ".",
        "subanalysis",
        "subanalysis",
        "subanalysis",
    ]
    records = [result.places[0].record for result in reads]
    assert records == [
        ".astra/records/u1/subanalysis.output1.json",
        "subanalysis/.astra/records/u1/output1.json",
        "subanalysis/.astra/records/v1/output1.json",
        "subanalysis/.astra/records/v1/parent.output1.json",
    ]
    parent = reads[3]
    assert (parent.workdir, dict(parent.decisions)) == ("", {"decision1": "a"})
    assert rendered(parent) == (
        "python src/output1.py 'data/input1.csv' 'subanalysis/results/v1/output1.json' 'a' "
        "'subanalysis/results/v1/parent.output1.json'"
    )


def test_each_placeholder_is_filled_with_what_its_result_gives(pinning: Path) -> None:
    """`{{` and `}}` are literal braces; `{inputs.<entry>}`, for entries with dots and `#`, the path
    of what the entry reads; `{decisions.<entry>}` the option selected; `{inputs}` every entry's
    path in order; `{output}` where the result is written; each verbatim."""
    resolved = api.resolve(pinning)
    (one, two) = [result for result in resolved.results if result.output.id == "output3"]
    template = (
        "python make.py {x} '%(input1)s' '%(sub)s' '%(pinned)s' '%(option)s' "
        "%(input1)s %(sub)s %(pinned)s '%(output)s' }"
    )
    relative = {"input1": "data/input1.csv", "pinned": "results/u1/output1.json"}
    assert rendered(one) == template % {
        **relative,
        "sub": "results/u1/subanalysis.output1.json",
        "option": "a",
        "output": "results/u1/output3.csv",
    }
    assert rendered(two) == template % {
        **relative,
        "sub": "results/u2/subanalysis.output1.json",
        "option": "b",
        "output": "results/u2/output3.csv",
    }


def test_a_driven_analysiss_recipe_runs_in_its_own_folder(pinning: Path) -> None:
    """`subanalysis`'s recipe, built in the root's `u1`, runs in `subanalysis`'s folder and reads
    its own input there, and writes into the root's results."""
    resolved = api.resolve(pinning)
    (built,) = [r for r in resolved.results if r.places[0].address == "subanalysis.output1#u1"]
    assert built.workdir == "subanalysis"
    assert [read.path for read in built.inputs] == ["subanalysis/data/input1.csv"]
    assert rendered(built) == (
        "python src/output1.py 'data/input1.csv' 'a' '../results/u1/subanalysis.output1.json'"
    )


@pytest.mark.parametrize(
    "universe, message",
    [
        ("u9", "no universe `u9`: its universes are u1, u2"),
        ("subanalysis_u1", "^`subanalysis_u1` is an import, which selects nothing: its"),
    ],
)
def test_a_view_of_what_isnt_a_universe_of_the_root_is_a_request_error(
    pinning: Path, universe: str, message: str
) -> None:
    """A universe the root doesn't have, or an import."""
    with pytest.raises(api.RequestError, match=message):
        api.resolve(pinning).view(universe)


# --- A declaration no key drives ---


UNDRIVEN = """\
spec_version: "0.1.0"
analyses:
  stage: {path: stage}
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  output1:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
universes:
  u1: {decisions: {decision1: a}}
  u2: {decisions: {decision1: b}}
"""
"""A root whose universes drive `stage`, which has no decisions to set, and set no key
through `stage.lone`; nothing they plan uses `lone`'s decision, so they drive `lone` too, with
nothing to set (Elements)."""

READS_LONE = """\
spec_version: "0.1.0"
analyses:
  lone: {path: ../lone}
outputs:
  reader:
    type: metric
    format: json
    inputs: [lone.out]
    recipe:
      command: python make.py '{inputs.lone.out}' '{output}'
"""
"""`stage`, with no decisions, whose `reader` reads `lone`'s `out` without a pin."""

LONE = """\
spec_version: "0.1.0"
decisions:
  d:
    options: {a: {}, b: {}}
outputs:
  out:
    type: metric
    format: json
    decisions: [d]
    recipe:
      command: python make.py '{decisions.d}' '{output}'
"""
"""An analysis whose `out`, listing its decision `d`, is built per universe."""


def test_outputs_nothing_planned_reads_break_no_rule_and_have_no_result(tmp_path: Path) -> None:
    """The root's universes drive `stage` and, through it, `lone`, as nothing they plan uses
    `lone`'s `d` (Elements), so they set it nowhere. `stage.lone.out` lists `d`, and
    `stage.reader` reads `lone.out`, but nothing planned reads either, so the stack breaks no
    rule: only the root's own `output1` is planned, and each of the two is noted."""
    files = {"astra.yaml": UNDRIVEN, "stage/astra.yaml": READS_LONE, "lone/astra.yaml": LONE}
    top = repository(tmp_path, files)
    assert api.validate(top).diagnostics == ()
    resolved = api.resolve(top)
    assert results(resolved) == [(".", "output1#u1"), (".", "output1#u2")]
    assert [(note.kind, note.location.file, note.location.pointer) for note in resolved.notes] == [
        ("unplanned", "stage/astra.yaml", "/outputs/reader"),
        ("unplanned", "lone/astra.yaml", "/outputs/out"),
    ]


# --- A result with two names ---


INNER = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  output1:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
"""

PAIR = """\
spec_version: "0.1.0"
analyses:
  stage: {path: stage}
  inner: {path: stage/inner}
outputs:
  through_inner:
    type: metric
    format: json
    inputs: [inner.output1]
    recipe:
      command: python make.py '{inputs.inner.output1}' '{output}'
  through_stage:
    type: metric
    format: json
    inputs: [stage.inner.output1]
    recipe:
      command: python make.py '{inputs.stage.inner.output1}' '{output}'
  through_staged:
    type: metric
    format: json
    inputs: [stage.staged]
    recipe:
      command: python make.py '{inputs.stage.staged}' '{output}'
universes:
  u1: {decisions: {inner.decision1: a}}
  u2: {decisions: {stage.inner.decision1: b}}
"""
"""The root declares `inner` and `stage`, and `stage` declares the same folder as
`inner`; keys go through both. The root reads `inner`'s `output1` through each, and `stage`'s
`staged` reads it through `stage`'s `inner`."""

STAGE = """\
spec_version: "0.1.0"
analyses:
  inner: {path: inner}
outputs:
  staged:
    type: metric
    format: json
    inputs: [inner.output1]
    recipe:
      command: python make.py '{inputs.inner.output1}' '{output}'
"""


def test_a_result_reached_through_two_chains_has_a_place_for_each_name(tmp_path: Path) -> None:
    """`inner`'s `output1` is made once in each universe, and placed and recorded under
    `stage.inner.output1` and `inner.output1`. A recipe writes it at the first name's place, and
    reads it at the place of the name along the entry's declarations from the analysis the result
    belongs to, the root: for `staged`'s `inner.output1`, along the root's `stage`, then `stage`'s
    `inner`."""
    files = {"astra.yaml": PAIR, "stage/astra.yaml": STAGE, "stage/inner/astra.yaml": INNER}
    top = repository(tmp_path, files)
    resolved = api.resolve(top)
    by_address = {result.places[0].address: result for result in resolved.results}
    inner = by_address["inner.output1#u1"]
    assert inner.names == ("inner.output1", "stage.inner.output1")
    assert [(place.record, place.bytes) for place in inner.places] == [
        (".astra/records/u1/inner.output1.json", "results/u1/inner.output1.json"),
        (".astra/records/u1/stage.inner.output1.json", "results/u1/stage.inner.output1.json"),
    ]
    assert rendered(inner) == "python make.py 'a' '../../results/u1/inner.output1.json'"
    assert rendered(by_address["through_inner#u1"]) == (
        "python make.py 'results/u1/inner.output1.json' 'results/u1/through_inner.json'"
    )
    assert rendered(by_address["through_stage#u1"]) == (
        "python make.py 'results/u1/stage.inner.output1.json' 'results/u1/through_stage.json'"
    )
    assert rendered(by_address["stage.staged#u1"]) == (
        "python make.py '../results/u1/stage.inner.output1.json' '../results/u1/stage.staged.json'"
    )
    # The validator says a result has two names (`RESULT_IN_TWO_PLACES`); no note repeats it.
    assert {d.code for d in api.validate(top).diagnostics} == {"RESULT_IN_TWO_PLACES"}
    assert resolved.notes == ()


# --- An analysis from a commit ---


LIB = """\
spec_version: "0.1.0"
decisions:
  d:
    options: {a: {}, b: {}}
outputs:
  out:
    type: metric
    format: json
    decisions: [d]
    recipe:
      command: python make.py '{decisions.d}' '{output}'
  once:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
universes:
  v1:
    decisions: {d: b}
"""

FROM_COMMIT = """\
spec_version: "0.1.0"
analyses:
  lib: {path: lib, commit: "%s"}
outputs:
  result:
    type: table
    format: csv
    inputs: [lib.out, lib.out#v1, lib.once]
    recipe:
      command: python make.py {inputs} '{output}'
universes:
  u1:
    decisions: {lib.d: a}
"""
"""A root whose universes drive `lib` at a commit, and which reads `lib`'s `out` as it builds
it, pinned to `lib`'s own `v1`, and `lib`'s `once`, built once."""


def test_an_analysis_from_a_commit_is_read_through_its_records_unless_driven(
    tmp_path: Path,
) -> None:
    """What the root's universes build of `lib` is the root's, run on `lib`'s files at its commit
    (`run_at`); `lib`'s results in its own `v1`, and its output built once, though driven, are
    `lib`'s at that commit, results from a commit (`from_commit`), read through their records,
    and no recipe of theirs runs. What `result` reads of them is in that commit's tree, not the
    working tree's (`Read.commit`)."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL, "lib/astra.yaml": LIB})
    commit = git(top, "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": FROM_COMMIT % commit})
    resolved = api.resolve(top)
    lib = Identity("lib", commit)
    assert {
        (str(r.owner), r.places[0].address): (r.from_commit, r.run_at, r.workdir)
        for r in resolved.results
    } == {
        (".", "lib.out#u1"): (False, commit, "lib"),
        (str(lib), "out#v1"): (True, None, "lib"),
        (str(lib), "once"): (True, None, "lib"),
        (".", "result#u1"): (False, None, ""),
    }
    (result,) = [r for r in resolved.results if r.names == ("result",)]
    assert [(read.entry, read.path, read.commit) for read in result.inputs] == [
        ("lib.out", "results/u1/lib.out.json", None),
        ("lib.out#v1", "lib/results/v1/out.json", commit),
        ("lib.once", "lib/results/once.json", commit),
    ]
    assert rendered(result) == (
        f"python make.py results/u1/lib.out.json {commit}:lib/results/v1/out.json "
        f"{commit}:lib/results/once.json 'results/u1/result.csv'"
    )


def test_each_result_has_its_places_and_its_command_filled_in(worked: Path) -> None:
    shown = [
        (r.places[0].address, r.places[0].record, r.places[0].bytes, rendered(r))
        for r in api.resolve(worked).results
    ]
    assert shown == [
        (
            "output1#u1",
            ".astra/records/u1/output1.json",
            "results/u1/output1.json",
            "python src/output1.py 'data/input1.csv' 'a' 'results/u1/output1.json'",
        ),
        (
            "output1#u2",
            ".astra/records/u2/output1.json",
            "results/u2/output1.json",
            "python src/output1.py 'data/input1.csv' 'b' 'results/u2/output1.json'",
        ),
        (
            "output2",
            ".astra/records/output2.json",
            "results/output2.csv",
            "python src/output2.py 'results/u1/output1.json' 'results/u2/output1.json' "
            "'results/output2.csv'",
        ),
    ]


# --- what a recipe asks for, and the notes ---


ASKING = """\
spec_version: "0.1.0"
outputs:
  default:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
  own:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
      resources: {cpus: 0.5, memory: 4GB, gpus: 1}
"""
"""An analysis with a recipe that asks for resources, and one that asks for none."""


def test_each_result_carries_what_its_recipe_asks_for(tmp_path: Path) -> None:
    """A result carries its recipe's `resources`, as written, which a runner
    schedules with."""
    top = repository(tmp_path, {"astra.yaml": ASKING})
    default, own = api.resolve(top).results
    assert default.resources is None
    assert own.resources == Resources(cpus=0.5, memory="4GB", gpus=1)


def test_a_pin_that_names_another_analysiss_universe_by_the_fallback_is_noted(
    pinning: Path,
) -> None:
    """The root's `subanalysis.output1#v1` names `subanalysis`'s `v1` only because the root's file
    has no universe `v1`, so adding one would change what it names. That is noted, though it breaks
    no rule; the pins naming the root's own `u1` and its imports aren't."""
    resolved = api.resolve(pinning)
    (note,) = [note for note in resolved.notes if note.kind == "fallback_pin"]
    assert (note.location.file, note.location.pointer) == (
        "astra.yaml",
        "/outputs/output5/inputs/2",
    )
    assert note.message == (
        "`subanalysis.output1#v1` names `v1` of `subanalysis` only because this file has no "
        "universe `v1`: adding one, or an import of that id, would change what it names"
    )
    assert (note.built, note.universes, note.switch, note.option) == (True, (), None, None)


NOTED = """\
spec_version: "0.1.0"
inputs:
  input1: {path: data/input1.csv}
decisions:
  decision1:
    options: {a: {}, b: {}, c: {}}
  decision2:
    options: {x: {}, y: {}}
outputs:
  first:
    type: metric
    format: json
    inputs: [input1]
    decisions: [decision1]
    recipe:
      command: PYTHONPATH=../lib python -m first '{inputs.input1}' '{decisions.decision1}' {output}
  second:
    type: metric
    format: json
    inputs: [first]
    recipe:
      command: python src/second.py '{inputs.first}' '{output}'
  third:
    type: metric
    format: json
    inputs: [first]
    decisions: [decision2]
    recipe:
      command: python src/third.py '{inputs.first}' '{decisions.decision2}' '{output}'
universes:
  u1: {decisions: {decision1: a, decision2: x}}
  u2: {decisions: {decision1: a, decision2: y}}
  u3: {decisions: {decision1: b, decision2: x}}
"""
"""Three outputs, of which `first`'s command names `../lib`."""

NO_UNIVERSES = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  never:
    type: figure
    format: png
    decisions: [decision1]
    recipe:
      command: python src/never.py '{decisions.decision1}' '{output}'
"""
"""A root with no universes, whose `never` is built per universe."""


def test_each_output_with_no_planned_result_is_noted(pinning: Path, tmp_path: Path) -> None:
    """An output of a declared analysis that no planned result reads and the
    root's evidence doesn't cite, and an output of the root built per universe where the root
    has no universes, have no planned result, so a check of the root never covers them. Each is
    noted at the output, in the files read where the root is."""
    found = [note for note in api.resolve(pinning).notes if note.kind == "unplanned"]
    assert [(n.location.file, n.location.pointer) for n in found] == [
        ("subanalysis/astra.yaml", "/outputs/unread")
    ]
    assert found[0].message == (
        "`unread` has no planned result: no planned result reads it and the root's evidence "
        "doesn't cite it, so a check of the root never covers it"
    )
    top = repository(tmp_path, {"astra.yaml": NO_UNIVERSES})
    (never,) = [note for note in api.resolve(top).notes if note.kind == "unplanned"]
    assert never.location.pointer == "/outputs/never"
    assert never.message == (
        "`never` has no planned result: it is built per universe and the root has no universes, "
        "so a check of the root never covers it"
    )


RULE = (
    "a recipe should run only code tracked in its analysis's folder, outside every folder "
    "below it that holds an analysis of its own, or that its output's inputs give it "
    "(`CODE_OUTSIDE_ANALYSIS`)"
)
"""What a note on a command that names a path outside its analysis's folder ends with."""

CLIMBING = """\
spec_version: "0.1.0"
inputs:
  code: {path: data/code.txt}
  data: {path: data/data.txt}
outputs:
  result:
    type: metric
    format: json
    inputs: [code, data]
    recipe:
      command: >-
        %s
"""
"""An analysis with one output, whose command is the one a test gives it."""


@pytest.mark.parametrize(
    ("command", "climbing"),
    [
        ("python ../../src/x.py '{output}'", ("../../src/x.py",)),
        ("PYTHONPATH=../lib:{inputs.code}/src python -m x", ("../lib",)),
        ("python x.py --config=../c.yaml 2>../log", ("../c.yaml", "../log")),
        ("cd .. && make", ("..",)),
        ('bash -c "python ../x.py" && cat ../x.py', ("../x.py",)),
        ("python src/../x.py a/b/../../c", ()),
        ("python src/../../x.py", ("src/../../x.py",)),
        ("python {inputs.data}/../x.py {output}", ()),
        ("/usr/bin/env python /opt/../x.py", ()),
        ("awk '{{print $1}}' x | seq 1..3 > ...", ()),
    ],
)
def test_a_command_names_a_path_outside_its_folder_where_it_climbs_out(
    tmp_path: Path, command: str, climbing: tuple[str, ...]
) -> None:
    """A path climbs out of the folder the recipe runs in where its `..` outnumber the folders
    before them. A path from a placeholder starts elsewhere, and an absolute path names no folder of
    the analysis. Each one that climbs out is named in the note on its command, once."""
    files = {"astra.yaml": CLIMBING % command, "data/code.txt": "1\n", "data/data.txt": "2\n"}
    top = repository(tmp_path, files)
    assert api.validate(top).diagnostics == ()
    found = [note for note in api.resolve(top).notes if note.kind == "outside_folder"]
    named = "; ".join(f"`{path}`, outside its analysis's folder" for path in climbing)
    assert [note.message for note in found] == (
        [f"the command names {named}: {RULE}"] if climbing else []
    )


def test_each_command_that_names_a_path_outside_its_folder_is_noted(tmp_path: Path) -> None:
    """`first`'s command names `../lib`, outside the root's folder, and `second`'s names
    `sub/second.py`, inside `sub`, which holds an `astra.yaml` of its own, declared or not. Each
    is noted at the command, citing `CODE_OUTSIDE_ANALYSIS`, which a runner holds a recipe to;
    `third`'s `src/third.py` is the root's own."""
    files = {
        "astra.yaml": NOTED.replace("python src/second.py", "python ./sub/second.py"),
        "data/input1.csv": "1\n",
        "sub/astra.yaml": MINIMAL,
    }
    top = repository(tmp_path, files)
    found = [note for note in api.resolve(top).notes if note.kind == "outside_folder"]
    assert [note.location.pointer for note in found] == [
        "/outputs/first/recipe/command",
        "/outputs/second/recipe/command",
    ]
    assert [note.message for note in found] == [
        f"the command names `../lib`, outside its analysis's folder: {RULE}",
        f"the command names `./sub/second.py`, inside `sub`, which holds an analysis of its own: "
        f"{RULE}",
    ]


BUILDS = {
    "astra.yaml": """\
spec_version: "0.1.0"
inputs:
  input1: {path: data/input1.csv}
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  result:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
  other:
    type: metric
    format: json
    recipe:
      command: python ../tools/other.py '{output}'
universes:
  u1: {decisions: {decision1: a}}
""",
    "data/input1.csv": "1\n",
    "sub/astra.yaml": """\
spec_version: "0.1.0"
analyses:
  paper: {path: ..}
  inner: {path: inner}
outputs:
  read:
    type: metric
    format: json
    inputs: [paper.input1, paper.result#u1]
    recipe:
      command: python read.py '{inputs.paper.input1}' '{inputs.paper.result#u1}' '{output}'
""",
    "sub/inner/astra.yaml": """\
spec_version: "0.1.0"
analyses:
  paper: {path: ../..}
outputs:
  pinned:
    type: metric
    format: json
    inputs: [paper.result#u1]
    recipe:
      command: python ../pinned.py '{inputs.paper.result#u1}' '{output}'
""",
}
"""`sub` reads from the analysis above it, none of whose decisions a universe of `sub` uses (it
has none), so it has nothing to set and `sub` builds it without a key (Elements). It also builds
`inner`, which has no decisions, and plans none of `inner`'s outputs. Both pin `paper.result#u1`
by the fallback, and only `sub`'s pin is read through. A command of each climbs out of its
folder."""


def test_the_notes_say_whether_they_concern_what_the_root_builds(tmp_path: Path) -> None:
    """A fallback pin concerns what the root builds where a planned result reads
    through it, and an output with no planned result, or a command naming a path outside its
    analysis, where its analysis is the root or one the root drives."""
    sub = repository(tmp_path, BUILDS) / "sub"
    resolved = api.resolve(sub)
    found = [(note.kind, note.location.file, note.built) for note in resolved.notes]
    assert found == [
        ("fallback_pin", "sub/astra.yaml", True),
        ("fallback_pin", "sub/inner/astra.yaml", False),
        ("unplanned", "astra.yaml", True),
        ("unplanned", "sub/inner/astra.yaml", True),
        ("outside_folder", "astra.yaml", True),
        ("outside_folder", "sub/inner/astra.yaml", True),
    ]


def test_an_invalid_analysis_resolves_to_nothing(tmp_path: Path) -> None:
    """`api.resolve` raises InvalidAnalysisError with the report."""
    broken = WORKED_EXAMPLE.replace("{decision1: b}", "{decision1: c}")
    top = repository(tmp_path, {"astra.yaml": broken, "data/input1.csv": "1\n"})
    with pytest.raises(api.InvalidAnalysisError) as raised:
        api.resolve(top)
    assert [d.code for d in raised.value.report.diagnostics] == ["UNKNOWN_OPTION"]
