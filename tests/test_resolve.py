"""The resolved analysis (`api.resolve`): its analyses under their keys, each element under its
ref, each universe's selection and what each evidence cites; the planned results, each after
what it reads, with their ids, places, what each entry reads and their commands as they run; the
results that aren't built from the working tree alone, which have no command; what the model
notes; and the model as JSON.

The stacks are a worked example; astra-spec's `examples/iris_pipeline`; `output5` reading
`subanalysis` and `upstream`, a remote, in three universes, where `upstream`'s own `v1` drives
its `inner`, with an output of every placeholder; a sub-analysis, driving, whose paths climb out
of its folder; an analysis with a declaration no key drives, whose outputs nothing reads; `inner`
reached through `inner` and `stage.inner`; analyses reached by chains of one length; an analysis
from a commit, read pinned and built once; an analysis with every optional field and one with
none; and one with each note a stack read as the root is can have.
"""

from __future__ import annotations

import json
import pickle
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from astra import api
from tests.conftest import MINIMAL, analysis, by_url, git, git_init, owner, repository
from tests.spec import SPEC
from tests.test_planned import PINNING, ROOT, UPSTREAM
from tests.test_validate import WORKED_EXAMPLE


def results(analysis: api.ResolvedAnalysis) -> list[tuple[str, str]]:
    """Each result, in the order resolved: the key of the analysis it belongs to, and its
    addresses."""
    return [
        (owner(analysis, r).key, ", ".join(p.address for p in r.places)) for r in analysis.results
    ]


def each_after_what_it_reads(analysis: api.ResolvedAnalysis) -> bool:
    built: set[str] = set()
    for result in analysis.results:
        if any(read.result is not None and read.result not in built for read in result.inputs):
            return False
        built.add(result.id)
    return True


def by_id(analysis: api.ResolvedAnalysis) -> dict[str, api.Result]:
    return {result.id: result for result in analysis.results}


def by_key(analysis: api.ResolvedAnalysis) -> dict[str, api.Analysis]:
    return {each.key: each for each in analysis.analyses}


def runs_in(analysis: api.ResolvedAnalysis, result: api.Result) -> str:
    """The folder `result`'s recipe runs in: its output's analysis's."""
    (folder,) = [
        each.folder
        for each in analysis.analyses
        if result.output in [output.ref for output in each.outputs]
    ]
    return folder


def made_with(analysis: api.ResolvedAnalysis, result: api.Result) -> dict[str, str]:
    """The option `result` is made with for each decision its output lists: the model holds it
    once, as its output's `decisions`, looked up in its universe's `selection`."""
    outputs = {output.ref: output for each in analysis.analyses for output in each.outputs}
    universes = {
        universe.ref: universe for each in analysis.analyses for universe in each.universes
    }
    decisions = outputs[result.output].decisions
    if result.universe is None:
        assert decisions == ()  # an output built once lists no decisions
        return {}
    selection = universes[result.universe].selection
    return {decision: selection[decision] for decision in decisions}


def noted(analysis: api.ResolvedAnalysis, code: str) -> list[api.Diagnostic]:
    return [note for note in analysis.notes if note.code == code]


# --- The worked example ---


@pytest.fixture(scope="module")
def worked(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {"astra.yaml": WORKED_EXAMPLE, "data/input1.csv": "1\n"}
    return repository(tmp_path_factory.mktemp("worked"), files)


def test_the_worked_example_plans_its_three_results_at_their_places(worked: Path) -> None:
    """`output1` in `u1` and in `u2`, then `output2`, which reads both, each named by its address,
    with its output and universe by ref, its record at its place and its bytes at its default
    place, what each entry of its output's `inputs` reads, an input by ref or a result by id, and
    its command as it runs."""
    analysis = api.resolve(worked)
    assert [
        (r.id, r.output, r.universe, [(p.address, p.record_path, p.file_path) for p in r.places])
        for r in analysis.results
    ] == [
        (
            "output1#u1",
            "outputs.output1",
            "universes.u1",
            [("output1#u1", ".astra/records/u1/output1.json", "results/u1/output1.json")],
        ),
        (
            "output1#u2",
            "outputs.output1",
            "universes.u2",
            [("output1#u2", ".astra/records/u2/output1.json", "results/u2/output1.json")],
        ),
        (
            "output2",
            "outputs.output2",
            None,
            [("output2", ".astra/records/output2.json", "results/output2.csv")],
        ),
    ]
    assert each_after_what_it_reads(analysis)
    one, two, compared = analysis.results
    (root,) = analysis.analyses
    assert (analysis.spec_version, root.key, root.folder, root.commit) == ("0.1.0", "", ".", None)
    assert [(owner(analysis, r).key, runs_in(analysis, r)) for r in analysis.results] == [
        ("", ".")
    ] * 3
    assert root.inputs == (api.Input("inputs.input1", "data/input1.csv"),)
    assert one.inputs == (api.Source("input1", input="inputs.input1"),)
    assert (
        made_with(analysis, one),
        made_with(analysis, two),
        made_with(analysis, compared),
    ) == ({"decisions.decision1": "a"}, {"decisions.decision1": "b"}, {})
    assert compared.inputs == (
        api.Source("output1#u1", result="output1#u1"),
        api.Source("output1#u2", result="output1#u2"),
    )
    assert compared.command == (
        "python src/output2.py 'results/u1/output1.json' 'results/u2/output1.json' "
        "'results/output2.csv'"
    )
    assert analysis.notes == ()


def test_the_head_is_the_commit_the_repository_is_on(tmp_path: Path) -> None:
    """HEAD's commit, on the analysis and on its status report alike, and none in a repository
    with no commit yet. It names the commit, not the files: an edit that isn't committed leaves
    it as it was."""
    folder = analysis(git_init(tmp_path))
    assert api.resolve(folder).head is None and api.status(folder).head is None
    git(folder, "add", "--all")
    git(folder, "commit", "--quiet", "--message", "first")
    first = git(folder, "rev-parse", "HEAD").strip()
    assert api.resolve(folder).head == api.status(folder).head == first
    (folder / "astra.yaml").write_text(MINIMAL + "label: Edited\n")
    edited = api.resolve(folder)
    assert (edited.head, edited.analyses[0].label) == (first, "Edited")
    git(folder, "commit", "--quiet", "--all", "--message", "second")
    assert api.resolve(folder).head == api.status(folder).head != first


def test_a_planned_result_pickles_by_itself(worked: Path) -> None:
    """A planned result is plain data, which a runner can hand to another process. It names
    what it reads by id, which the model's results are looked up by, so its pickle holds nothing
    of the results it reads. The whole model pickles too."""
    analysis = api.resolve(worked)
    one, two, compared = analysis.results
    for result in analysis.results:
        assert pickle.loads(pickle.dumps(result)) == result
    found = by_id(analysis)
    assert [found[read.result] for read in compared.inputs if read.result] == [one, two]
    assert one.command is not None
    assert one.command.encode() not in pickle.dumps(compared)
    assert pickle.loads(pickle.dumps(analysis)) == analysis


def test_the_worked_examples_commands_fill_in_with_what_each_result_reads(worked: Path) -> None:
    """`{decisions.decision1}` is `a` in `u1` and `b` in `u2`, `output2` reads
    the paths of both results, and `{output}` is where each result is written."""
    assert [result.command for result in api.resolve(worked).results] == [
        "python src/output1.py 'data/input1.csv' 'a' 'results/u1/output1.json'",
        "python src/output1.py 'data/input1.csv' 'b' 'results/u2/output1.json'",
        "python src/output2.py 'results/u1/output1.json' 'results/u2/output1.json' "
        "'results/output2.csv'",
    ]


def test_each_result_has_its_places_and_its_command_filled_in(worked: Path) -> None:
    shown = [
        (r.places[0].address, r.places[0].record_path, r.places[0].file_path, r.command)
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


# --- examples/iris_pipeline ---


IRIS = {
    ("", "iris_data"),
    ("", "comparison"),
    ("", "split#baseline"),
    ("", "split#mlp_svm"),
    ("", "summary#baseline"),
    ("", "summary#mlp_svm"),
    ("", "classification.accuracy#baseline"),
    ("", "classification.accuracy#mlp_svm"),
    ("", "classification.predictions#baseline"),
    ("", "classification.predictions#mlp_svm"),
    ("", "feature_extraction.features#baseline"),
    ("", "feature_extraction.features#mlp_svm"),
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
    analysis = api.resolve(repository(tmp_path / "pipeline", {}))
    assert len(analysis.results) == len(IRIS)
    assert set(results(analysis)) == IRIS
    assert each_after_what_it_reads(analysis)
    found = by_id(analysis)
    features = found["feature_extraction.features#mlp_svm"]
    assert (features.output, runs_in(analysis, features), features.places[0].file_path) == (
        "feature_extraction.outputs.features",
        "feature_extraction",
        "results/mlp_svm/feature_extraction.features.npy",
    )
    assert made_with(analysis, features) == {
        "feature_extraction.decisions.method": "mlp_encoder",
        "feature_extraction.decisions.n_components": "two",
        "decisions.random_seed": "seed_42",
    }
    predictions = found["classification.predictions#mlp_svm"]
    assert predictions.inputs == (
        api.Source("feature_extraction.features", result="feature_extraction.features#mlp_svm"),
        api.Source("iris.split", result="split#mlp_svm"),
    )
    assert predictions.command == (
        "python src/classify.py --features ../results/mlp_svm/feature_extraction.features.npy "
        "--split ../results/mlp_svm/split.json --classifier svm "
        "--out ../results/mlp_svm/classification.predictions.csv"
    )


def test_iris_pipelines_analyses_have_their_shortest_addresses(tmp_path: Path) -> None:
    """`feature_extraction` is declared by the root and by `classification`: its key is the
    shorter chain, and each declaration that reaches an analysis gives that analysis's key, the
    stages' `iris: {path: ..}` the root's, which is ""."""
    shutil.copytree(SPEC / "examples" / "iris_pipeline", tmp_path / "pipeline")
    analysis = api.resolve(repository(tmp_path / "pipeline", {}))
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        (
            "",
            ".",
            {"feature_extraction": "feature_extraction", "classification": "classification"},
        ),
        (
            "classification",
            "classification",
            {"iris": "", "feature_extraction": "feature_extraction"},
        ),
        ("feature_extraction", "feature_extraction", {"iris": ""}),
    ]


# --- output5, inner.output2, and the placeholders ---


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
    upstream = by_url(tmp_path_factory.mktemp("upstream"), UPSTREAM)
    files = {
        **PINNING,
        "astra.yaml": ROOT.replace("universes:\n", PLACEHOLDERS + "universes:\n", 1) % upstream,
    }
    return repository(tmp_path_factory.mktemp("pinning"), files)


def test_output5s_three_pins_read_three_results_each_in_its_owners_folder(pinning: Path) -> None:
    """`subanalysis.output1#u1` reads the root's result, named `subanalysis.output1`;
    `upstream.output1#upstream_u1` and `#v1` read `upstream`'s own, in its tree at its commit,
    under its universes' own ids; `upstream.inner.output2#upstream_v1` reads `inner`'s `output2`
    as `upstream`'s `v1` builds it, through `inner: {path: inner}`, named `inner.output2` there,
    in `inner`'s folder. Each is a result from a commit, with no command. A result that belongs
    to another analysis than the driving one has that analysis's key before its address, in its
    id."""
    analysis = api.resolve(pinning)
    assert set(results(analysis)) == {
        ("", "output1#u1"),
        ("", "output1#u2"),
        ("", "output3#u1"),
        ("", "output3#u2"),
        ("", "output5"),
        ("", "subanalysis.output1#u1"),
        ("", "subanalysis.output1#u2"),
        ("upstream", "output1#u1"),
        ("upstream", "output1#v1"),
        ("upstream", "inner.output2#v1"),
    }
    assert each_after_what_it_reads(analysis)
    found = by_id(analysis)
    assert set(found) == {
        "output1#u1",
        "output1#u2",
        "output3#u1",
        "output3#u2",
        "output5",
        "subanalysis.output1#u1",
        "subanalysis.output1#u2",
        "upstream:output1#u1",
        "upstream:output1#v1",
        "upstream:inner.output2#v1",
    }
    output5 = found["output5"]
    assert output5.inputs == (
        api.Source("subanalysis.output1#u1", result="subanalysis.output1#u1"),
        api.Source("upstream.output1#upstream_u1", result="upstream:output1#u1"),
        api.Source("upstream.output1#v1", result="upstream:output1#v1"),
        api.Source("upstream.inner.output2#upstream_v1", result="upstream:inner.output2#v1"),
    )
    reads = [found[read.result] for read in output5.inputs if read.result is not None]
    assert [owner(analysis, result).key for result in reads] == [
        "",
        "upstream",
        "upstream",
        "upstream",
    ]
    assert [result.places[0].file_path for result in reads] == [
        "results/u1/subanalysis.output1.json",
        "results/u1/output1.json",
        "results/v1/output1.json",
        "results/v1/inner.output2.json",
    ]
    assert [result.places[0].record_path for result in reads] == [
        ".astra/records/u1/subanalysis.output1.json",
        ".astra/records/u1/output1.json",
        ".astra/records/v1/output1.json",
        ".astra/records/v1/inner.output2.json",
    ]
    inner = reads[3]
    assert (inner.output, inner.universe) == (
        "upstream.inner.outputs.output2",
        "upstream.universes.v1",
    )
    assert (runs_in(analysis, inner), made_with(analysis, inner)) == (
        "inner",
        {"upstream.inner.decisions.decision2": "a"},
    )
    assert inner.command is None


def test_each_placeholder_is_filled_with_what_its_result_gives(pinning: Path) -> None:
    """`{{` and `}}` are literal braces; `{inputs.<entry>}`, for entries with dots and `#`, the path
    of what the entry reads; `{decisions.<entry>}` the option selected; `{inputs}` every entry's
    path in order; `{output}` where the result is written; each verbatim."""
    found = by_id(api.resolve(pinning))
    template = (
        "python make.py {x} '%(input1)s' '%(sub)s' '%(pinned)s' '%(option)s' "
        "%(input1)s %(sub)s %(pinned)s '%(output)s' }"
    )
    relative = {"input1": "data/input1.csv", "pinned": "results/u1/output1.json"}
    assert found["output3#u1"].command == template % {
        **relative,
        "sub": "results/u1/subanalysis.output1.json",
        "option": "a",
        "output": "results/u1/output3.csv",
    }
    assert found["output3#u2"].command == template % {
        **relative,
        "sub": "results/u2/subanalysis.output1.json",
        "option": "b",
        "output": "results/u2/output3.csv",
    }


def test_a_driven_analysiss_recipe_runs_in_its_own_folder(pinning: Path) -> None:
    """`subanalysis`'s recipe, built in the root's `u1`, runs in `subanalysis`'s folder and reads
    its own input there, and writes into the root's results: its command gives each path from
    that folder."""
    analysis = api.resolve(pinning)
    built = by_id(analysis)["subanalysis.output1#u1"]
    assert (built.output, runs_in(analysis, built)) == (
        "subanalysis.outputs.output1",
        "subanalysis",
    )
    assert built.inputs == (api.Source("input1", input="subanalysis.inputs.input1"),)
    assert by_key(analysis)["subanalysis"].inputs == (
        api.Input("subanalysis.inputs.input1", "subanalysis/data/input1.csv"),
    )
    assert built.command == (
        "python src/output1.py 'data/input1.csv' 'a' '../results/u1/subanalysis.output1.json'"
    )


def test_each_element_has_a_ref_under_its_analysiss_key(pinning: Path) -> None:
    """A ref is the key of the element's analysis, the collection its file writes it in, and
    its id, and names the element whichever address a file spells it by: `unread`'s
    `inner.decision2` is `subanalysis.inner.decisions.decision2`. An analysis's universes are
    its own: an import, which selects nothing, isn't one."""
    analysis = api.resolve(pinning)
    root, sub, inner, up, _ = analysis.analyses
    assert (root.key, sub.key, inner.key, up.key) == (
        "",
        "subanalysis",
        "subanalysis.inner",
        "upstream",
    )
    assert (dict(root.declares), dict(sub.declares), dict(inner.declares)) == (
        {"subanalysis": "subanalysis", "upstream": "upstream"},
        {"inner": "subanalysis.inner"},
        {},
    )
    assert [
        [element.ref for element in collection]
        for collection in (root.inputs, root.decisions, root.outputs, root.universes, root.findings)
    ] == [
        ["inputs.input1"],
        ["decisions.decision1"],
        ["outputs.output1", "outputs.output5", "outputs.output3"],
        ["universes.u1", "universes.u2"],
        ["findings.insight1"],
    ]
    assert [
        [element.ref for element in collection]
        for collection in (sub.inputs, sub.decisions, sub.outputs, sub.universes, sub.findings)
    ] == [
        ["subanalysis.inputs.input1"],
        ["subanalysis.decisions.decision1"],
        ["subanalysis.outputs.output1", "subanalysis.outputs.unread"],
        [],
        [],
    ]
    assert [universe.ref for universe in up.universes] == [
        "upstream.universes.u1",
        "upstream.universes.v1",
    ]
    assert {output.ref: output.decisions for output in (*root.outputs, *sub.outputs)} == {
        "outputs.output1": ("decisions.decision1",),
        "outputs.output5": (),
        "outputs.output3": ("subanalysis.decisions.decision1",),
        "subanalysis.outputs.output1": ("subanalysis.decisions.decision1",),
        "subanalysis.outputs.unread": (
            "subanalysis.decisions.decision1",
            "subanalysis.inner.decisions.decision2",
        ),
    }


def test_a_universes_selection_is_by_ref_with_its_own_analysis_driving(pinning: Path) -> None:
    """Each universe gives the option it selects for each decision it uses, by the decision's
    ref: the root's set `subanalysis`'s decision, and `upstream`'s own set its `inner`'s, which
    its `unread` lists. Every result is made with an option for each decision its output lists,
    found in its universe's selection."""
    analysis = api.resolve(pinning)
    root, up = analysis.analyses[0], by_key(analysis)["upstream"]
    assert {universe.ref: dict(universe.selection) for universe in root.universes} == {
        "universes.u1": {"decisions.decision1": "a", "subanalysis.decisions.decision1": "a"},
        "universes.u2": {"decisions.decision1": "b", "subanalysis.decisions.decision1": "b"},
    }
    assert {universe.ref: dict(universe.selection) for universe in up.universes} == {
        "upstream.universes.u1": {
            "upstream.decisions.decision1": "a",
            "upstream.inner.decisions.decision2": "b",
        },
        "upstream.universes.v1": {
            "upstream.decisions.decision1": "b",
            "upstream.inner.decisions.decision2": "a",
        },
    }
    assert {result.id: made_with(analysis, result) for result in analysis.results} == {
        "output1#u1": {"decisions.decision1": "a"},
        "output1#u2": {"decisions.decision1": "b"},
        "output3#u1": {"subanalysis.decisions.decision1": "a"},
        "output3#u2": {"subanalysis.decisions.decision1": "b"},
        "output5": {},
        "subanalysis.output1#u1": {"subanalysis.decisions.decision1": "a"},
        "subanalysis.output1#u2": {"subanalysis.decisions.decision1": "b"},
        "upstream:output1#u1": {"upstream.decisions.decision1": "a"},
        "upstream:output1#v1": {"upstream.decisions.decision1": "b"},
        "upstream:inner.output2#v1": {"upstream.inner.decisions.decision2": "a"},
    }


PARENT = """\
spec_version: "0.1.0"
analyses:
  stage: {path: stage}
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
universes:
  u1: {decisions: {decision1: a}}
findings:
  insight1:
    claim: The stage reads the parent's input and result.
    evidence: [{artifact: stage.output3}]
"""
"""The top of a repository, whose `stage` is a sub-analysis."""

READS_PARENT = """\
spec_version: "0.1.0"
analyses:
  parent: {path: ..}
inputs:
  input3: {path: data/input3.csv}
outputs:
  output3:
    type: table
    format: csv
    inputs: [input3, parent.input1, parent.output1#u1]
    recipe:
      command: >-
        python src/output3.py '{inputs.input3}' '{inputs.parent.input1}'
        '{inputs.parent.output1#u1}' '{output}'
"""
"""`stage`, which declares its parent and reads its input and its result in its `u1`."""


@pytest.fixture(scope="module")
def reads_parent(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {
        "astra.yaml": PARENT,
        "data/input1.csv": "1\n",
        "stage/astra.yaml": READS_PARENT,
        "stage/data/input3.csv": "3\n",
    }
    return repository(tmp_path_factory.mktemp("reads_parent"), files)


def test_the_models_paths_are_from_the_driving_analysiss_folder(reads_parent: Path) -> None:
    """Every path of the model is from the folder of the driving analysis, wherever that is in
    its repository: with `stage` driving, its own files are named from its folder,
    which is `.`, and its parent's, the analysis above it, climb out of it, as does the folder
    its parent's result runs in. A note's location isn't such a path: the note on `#u1`, which
    names the parent's `u1` as `stage` has none, names `stage`'s file from the top of the
    repository, as a validator's does. The parent declares the driving analysis back, whose key
    is "", and its finding cites `stage.output3`'s one result."""
    analysis = api.resolve(reads_parent / "stage")
    driving, parent = analysis.analyses
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        ("", ".", {"parent": "parent"}),
        ("parent", "..", {"stage": ""}),
    ]
    assert driving.inputs == (api.Input("inputs.input3", "data/input3.csv"),)
    assert parent.inputs == (api.Input("parent.inputs.input1", "../data/input1.csv"),)
    (finding,) = parent.findings
    assert (finding.ref, [evidence.cites for evidence in finding.evidence]) == (
        "parent.findings.insight1",
        [("output3",)],
    )
    assert [
        (r.id, r.places[0].record_path, r.places[0].file_path, runs_in(analysis, r), r.command)
        for r in analysis.results
    ] == [
        (
            "parent:output1#u1",
            "../.astra/records/u1/output1.json",
            "../results/u1/output1.json",
            "..",
            "python src/output1.py 'data/input1.csv' 'a' 'results/u1/output1.json'",
        ),
        (
            "output3",
            ".astra/records/output3.json",
            "results/output3.csv",
            ".",
            "python src/output3.py 'data/input3.csv' '../data/input1.csv' "
            "'../results/u1/output1.json' 'results/output3.csv'",
        ),
    ]
    assert [(note.code, note.location.file, note.location.pointer) for note in analysis.notes] == [
        ("FALLBACK_PIN", "stage/astra.yaml", "/outputs/output3/inputs/2")
    ]


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
    rule: only the root's own `output1` is planned, and each of the two is noted. `lone`, which
    only `stage` declares, is known by the chain through it, and its folder isn't `stage`'s."""
    files = {"astra.yaml": UNDRIVEN, "stage/astra.yaml": READS_LONE, "lone/astra.yaml": LONE}
    top = repository(tmp_path, files)
    assert api.validate(top).diagnostics == ()
    analysis = api.resolve(top)
    assert results(analysis) == [("", "output1#u1"), ("", "output1#u2")]
    assert [
        (note.code, note.level, note.location.file, note.location.pointer)
        for note in analysis.notes
    ] == [
        ("UNPLANNED_OUTPUT", "note", "stage/astra.yaml", "/outputs/reader"),
        ("UNPLANNED_OUTPUT", "note", "lone/astra.yaml", "/outputs/out"),
    ]
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        ("", ".", {"stage": "stage"}),
        ("stage", "stage", {"lone": "stage.lone"}),
        ("stage.lone", "lone", {}),
    ]
    assert [output.ref for output in by_key(analysis)["stage.lone"].outputs] == [
        "stage.lone.outputs.out"
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
    `inner.output1` and `stage.inner.output1`: one result, named by its first address, with a
    place for each name. Whichever chain an entry names it by, it reads that one result, and
    the command is filled with the bytes at its first place, where a recipe writes it too."""
    files = {"astra.yaml": PAIR, "stage/astra.yaml": STAGE, "stage/inner/astra.yaml": INNER}
    top = repository(tmp_path, files)
    analysis = api.resolve(top)
    found = by_id(analysis)
    inner = found["inner.output1#u1"]
    assert [(place.address, place.record_path, place.file_path) for place in inner.places] == [
        (
            "inner.output1#u1",
            ".astra/records/u1/inner.output1.json",
            "results/u1/inner.output1.json",
        ),
        (
            "stage.inner.output1#u1",
            ".astra/records/u1/stage.inner.output1.json",
            "results/u1/stage.inner.output1.json",
        ),
    ]
    assert "stage.inner.output1#u1" not in found
    assert inner.command == "python make.py 'a' '../../results/u1/inner.output1.json'"
    assert {
        id_: (found[id_].inputs, found[id_].command)
        for id_ in ("through_inner#u1", "through_stage#u1", "stage.staged#u1")
    } == {
        "through_inner#u1": (
            (api.Source("inner.output1", result="inner.output1#u1"),),
            "python make.py 'results/u1/inner.output1.json' 'results/u1/through_inner.json'",
        ),
        "through_stage#u1": (
            (api.Source("stage.inner.output1", result="inner.output1#u1"),),
            "python make.py 'results/u1/inner.output1.json' 'results/u1/through_stage.json'",
        ),
        "stage.staged#u1": (
            (api.Source("inner.output1", result="inner.output1#u1"),),
            "python make.py '../results/u1/inner.output1.json' '../results/u1/stage.staged.json'",
        ),
    }
    # The validator says a result has two names (`RESULT_IN_TWO_PLACES`); no note repeats it.
    assert {d.code for d in api.validate(top).diagnostics} == {"RESULT_IN_TWO_PLACES"}
    assert analysis.notes == ()


def test_an_analysis_reached_through_two_chains_has_the_shorter_as_its_key(tmp_path: Path) -> None:
    """`stage/inner` is the root's `inner` and `stage`'s `inner`: its key is the shorter chain,
    which every ref into it begins with, however a file spells the address: `u2`'s key
    `stage.inner.decision1` selects for `inner.decisions.decision1`."""
    files = {"astra.yaml": PAIR, "stage/astra.yaml": STAGE, "stage/inner/astra.yaml": INNER}
    analysis = api.resolve(repository(tmp_path, files))
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        ("", ".", {"stage": "stage", "inner": "inner"}),
        ("inner", "stage/inner", {}),
        ("stage", "stage", {"inner": "inner"}),
    ]
    root = analysis.analyses[0]
    assert {universe.ref: dict(universe.selection) for universe in root.universes} == {
        "universes.u1": {"inner.decisions.decision1": "a"},
        "universes.u2": {"inner.decisions.decision1": "b"},
    }
    assert by_id(analysis)["inner.output1#u2"].output == "inner.outputs.output1"


def test_a_decision_an_output_lists_under_two_addresses_is_one_of_its_decisions(
    tmp_path: Path,
) -> None:
    """An output's `decisions` are by ref, each once: `through_inner` lists `inner`'s decision
    as `inner.decision1` and as `stage.inner.decision1`, two spellings of one decision. Its
    command still fills a placeholder for each entry as written."""
    listing = PAIR.replace(
        "    inputs: [inner.output1]\n    recipe:\n"
        "      command: python make.py '{inputs.inner.output1}' '{output}'\n",
        "    inputs: [inner.output1]\n"
        "    decisions: [inner.decision1, stage.inner.decision1]\n    recipe:\n"
        "      command: >-\n"
        "        python make.py '{inputs.inner.output1}' '{decisions.inner.decision1}'\n"
        "        '{decisions.stage.inner.decision1}' '{output}'\n",
    )
    assert listing != PAIR
    files = {"astra.yaml": listing, "stage/astra.yaml": STAGE, "stage/inner/astra.yaml": INNER}
    analysis = api.resolve(repository(tmp_path, files))
    assert analysis.analyses[0].outputs[0] == api.Output(
        "outputs.through_inner",
        "metric",
        "json",
        decisions=("inner.decisions.decision1",),
        inputs=(api.AuthoredReference("inner.output1", "inner.outputs.output1"),),
    )
    assert by_id(analysis)["through_inner#u2"].command == (
        "python make.py 'results/u2/inner.output1.json' 'b' 'b' 'results/u2/through_inner.json'"
    )


TIES = """\
spec_version: "0.1.0"
analyses:
  y: {path: y}
  x: {path: x}
  b: {path: shared}
  a: {path: shared}
outputs:
  result:
    type: metric
    format: json
    inputs: [b.result, y.z.result]
    recipe:
      command: python make.py {inputs} '{output}'
"""
"""A root that declares one folder as `b` then `a`, and `y` then `x`, each of which declares
`z`."""

DECLARES_Z = """\
spec_version: "0.1.0"
analyses:
  z: {path: ../z}
outputs:
  result:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
"""


def test_among_chains_of_one_length_a_key_is_the_first_in_alphabetical_order(
    tmp_path: Path,
) -> None:
    """`shared` is reached by `b` and by `a`, and `z` by `y.z` and by `x.z`: each is known by the
    first in alphabetical order, whatever order its file declares them in, and by that key
    wherever it is named: in `declares`, in a ref, and before the address of a result that
    belongs to it. The analyses come by key, the driving one first."""
    files = {
        "astra.yaml": TIES,
        "shared/astra.yaml": MINIMAL,
        "x/astra.yaml": DECLARES_Z,
        "y/astra.yaml": DECLARES_Z,
        "z/astra.yaml": MINIMAL,
    }
    top = repository(tmp_path, files)
    assert api.validate(top).diagnostics == ()
    analysis = api.resolve(top)
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        ("", ".", {"y": "y", "x": "x", "b": "a", "a": "a"}),
        ("a", "shared", {}),
        ("x", "x", {"z": "x.z"}),
        ("x.z", "z", {}),
        ("y", "y", {"z": "x.z"}),
    ]
    assert [(result.id, result.output) for result in analysis.results] == [
        ("a:result", "a.outputs.result"),
        ("x.z:result", "x.z.outputs.result"),
        ("result", "outputs.result"),
    ]
    assert analysis.results[2].inputs == (
        api.Source("b.result", result="a:result"),
        api.Source("y.z.result", result="x.z:result"),
    )
    assert analysis.results[2].command == (
        "python make.py shared/results/result.json z/results/result.json 'results/result.json'"
    )


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
  lib: {path: ., commit: "%s"}
outputs:
  result:
    type: table
    format: csv
    inputs: [lib.out#v1, lib.once]
    recipe:
      command: python make.py {inputs} '{output}'
  alone:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
"""
"""A root that reads `lib`, its own folder at a commit where it held `LIB`, only as `lib` builds
it: its `out` pinned to `lib`'s own `v1`, and its `once`, built once; and `alone`, which reads
nothing. Nothing at a commit is driven, so no universe of the root sets `lib`'s decisions."""


TABLES = """\
spec_version: "0.1.0"
inputs:
  table: {path: data/table.csv}
outputs:
  once:
    type: metric
    format: json
    inputs: [table]
    recipe:
      command: python make.py '{inputs.table}' '{output}'
"""
"""An analysis with an input, and an output built once that reads it."""

READS_TABLES = """\
spec_version: "0.1.0"
analyses:
  lib: {path: ../lib, commit: "%s"}
inputs:
  own: {path: data/own.csv}
outputs:
  reads_input:
    type: metric
    format: json
    inputs: [lib.table, own]
    recipe:
      command: python make.py {inputs} '{output}'
  reads_result:
    type: metric
    format: json
    inputs: [lib.once]
    recipe:
      command: python make.py {inputs} '{output}'
  alone:
    type: metric
    format: json
    inputs: [own]
    recipe:
      command: python make.py {inputs} '{output}'
"""
"""An analysis in a folder below its repository's top, which reads an input and a result of
`lib`, beside it, at a commit, and an input of its own."""


def test_a_result_that_reads_a_file_at_a_commit_has_no_command(tmp_path: Path) -> None:
    """A file of an analysis read at a commit is no file of the working tree: `lib`'s input and
    its result are in that commit's tree, their paths from the top of its repository, whichever
    folder the driving analysis is in, as is `lib`'s folder. A result that reads either isn't
    built from the working tree alone and has no command, beside one that reads the driving
    analysis's own input, from its folder."""
    files = {
        "astra.yaml": 'spec_version: "0.1.0"\n',
        "lib/astra.yaml": TABLES,
        "lib/data/table.csv": "1\n",
        "sub/astra.yaml": MINIMAL,
        "sub/data/own.csv": "2\n",
    }
    top = repository(tmp_path, files)
    commit = git(top, "rev-parse", "HEAD").strip()
    repository(top, {"sub/astra.yaml": READS_TABLES % commit})
    assert api.validate(top / "sub").diagnostics == ()
    analysis = api.resolve(top / "sub")
    driving, lib = analysis.analyses
    assert (driving.folder, driving.commit, driving.inputs) == (
        ".",
        None,
        (api.Input("inputs.own", "data/own.csv"),),
    )
    assert (lib.key, lib.folder, lib.commit, lib.inputs) == (
        "lib",
        "lib",
        api.Commit(commit),
        (api.Input("lib.inputs.table", "lib/data/table.csv"),),
    )
    assert {result.id: (result.inputs, result.command) for result in analysis.results} == {
        "reads_input": (
            (
                api.Source("lib.table", input="lib.inputs.table"),
                api.Source("own", input="inputs.own"),
            ),
            None,
        ),
        "lib:once": ((api.Source("table", input="lib.inputs.table"),), None),
        "reads_result": ((api.Source("lib.once", result="lib:once"),), None),
        "alone": (
            (api.Source("own", input="inputs.own"),),
            "python make.py data/own.csv 'results/alone.json'",
        ),
    }
    assert by_id(analysis)["lib:once"].places == (
        api.Place("once", "lib/.astra/records/once.json", "lib/results/once.json"),
    )
    assert by_id(analysis)["reads_result"].places == (
        api.Place("reads_result", ".astra/records/reads_result.json", "results/reads_result.json"),
    )


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


def test_each_output_carries_what_its_recipe_asks_for(tmp_path: Path) -> None:
    """An output carries its recipe's `resources`, as written, which a runner schedules each of
    its results with."""
    top = repository(tmp_path, {"astra.yaml": ASKING})
    analysis = api.resolve(top)
    default, own = analysis.analyses[0].outputs
    assert default.resources is None
    assert own.resources == api.Resources(cpus=0.5, memory="4GB", gpus=1)
    assert [result.output for result in analysis.results] == ["outputs.default", "outputs.own"]


def test_a_pin_that_names_another_analysiss_universe_by_the_fallback_is_noted(
    pinning: Path,
) -> None:
    """The root's `upstream.output1#v1` names `upstream`'s `v1` only because the root's file has
    no universe `v1`, so adding one would change what it names. That is noted, though it breaks
    no rule; the pins naming the root's own `u1` and its imports aren't."""
    analysis = api.resolve(pinning)
    up = by_key(analysis)["upstream"].commit
    assert up is not None
    (note,) = noted(analysis, "FALLBACK_PIN")
    assert (note.level, note.location.file, note.location.pointer) == (
        "note",
        "astra.yaml",
        "/outputs/output5/inputs/2",
    )
    assert note.message == (
        f"`upstream.output1#v1` names `v1` of `. at {up.id}` only because this file has no "
        "universe `v1`: adding one, or an import of that id, would change what it names"
    )


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
    noted at the output, in the files read as the root is: not `upstream`'s, read at a commit."""
    found = noted(api.resolve(pinning), "UNPLANNED_OUTPUT")
    assert [(n.level, n.location.file, n.location.pointer) for n in found] == [
        ("note", "subanalysis/astra.yaml", "/outputs/unread"),
        ("note", "subanalysis/inner/astra.yaml", "/outputs/output2"),
    ]
    assert found[0].message == (
        "`unread` has no planned result: no planned result reads it and the root's evidence "
        "doesn't cite it, so a check of the root never covers it"
    )
    top = repository(tmp_path, {"astra.yaml": NO_UNIVERSES})
    analysis = api.resolve(top)
    (never,) = noted(analysis, "UNPLANNED_OUTPUT")
    assert never.location.pointer == "/outputs/never"
    assert never.message == (
        "`never` has no planned result: it is built per universe and the root has no universes, "
        "so a check of the root never covers it"
    )
    assert (analysis.results, analysis.analyses[0].universes) == ((), ())


RULE = (
    "a recipe should run only code tracked in its analysis's folder, outside every folder "
    "below it that holds an analysis of its own, or that its output's inputs give it"
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


def test_given_where_a_runner_puts_a_commits_files_a_result_that_reads_one_has_a_command(
    tmp_path: Path,
) -> None:
    """The analysis is in `sub`, below its repository's top, and reads `lib`, beside it, at a
    commit. Given `commits`, a folder from the analysis's own, a result that reads `lib`'s input
    or its result has a command, naming each file at `<commits>/<commit id>/` and its path in
    that commit's tree, from the top of its repository, as the recipe runs in `sub`. `lib`'s
    result is still a result from a commit, which is never built, and has none."""
    files = {
        "astra.yaml": 'spec_version: "0.1.0"\n',
        "lib/astra.yaml": TABLES,
        "lib/data/table.csv": "1\n",
        "sub/astra.yaml": MINIMAL,
        "sub/data/own.csv": "2\n",
    }
    top = repository(tmp_path, files)
    commit = git(top, "rev-parse", "HEAD").strip()
    repository(top, {"sub/astra.yaml": READS_TABLES % commit})
    analysis = api.resolve(top / "sub", commits=".lightcone/commits")
    at = f".lightcone/commits/{commit}"
    assert {result.id: result.command for result in analysis.results} == {
        "reads_input": f"python make.py {at}/lib/data/table.csv data/own.csv "
        "'results/reads_input.json'",
        "lib:once": None,
        "reads_result": f"python make.py {at}/lib/results/once.json 'results/reads_result.json'",
        "alone": "python make.py data/own.csv 'results/alone.json'",
    }
    assert api.resolve(top / "sub").results == tuple(
        replace(result, command=None) if result.id.startswith("reads_") else result
        for result in analysis.results
    )


@pytest.mark.parametrize("commits", ["", ".", "..", "../commits", "a/../..", "/abs/commits"])
def test_where_a_commits_files_go_is_a_folder_inside_the_analysiss(
    tmp_path: Path, commits: str
) -> None:
    top = repository(tmp_path, {"astra.yaml": MINIMAL})
    with pytest.raises(ValueError, match="folder inside the analysis's"):
        api.resolve(top, commits=commits)


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
    found = noted(api.resolve(top), "CODE_OUTSIDE_ANALYSIS")
    named = "; ".join(f"`{path}`, outside its analysis's folder" for path in climbing)
    assert [note.message for note in found] == (
        [f"the command names {named}: {RULE}"] if climbing else []
    )


def test_each_command_that_names_a_path_outside_its_folder_is_noted(tmp_path: Path) -> None:
    """`first`'s command names `../lib`, outside the root's folder, and `second`'s names
    `sub/second.py`, inside `sub`, which holds an `astra.yaml` of its own, declared or not. Each
    is noted at the command, under `CODE_OUTSIDE_ANALYSIS`, a `SHOULD` a runner holds a recipe
    to, so a warning; `third`'s `src/third.py` is the root's own."""
    files = {
        "astra.yaml": NOTED.replace("python src/second.py", "python ./sub/second.py"),
        "data/input1.csv": "1\n",
        "sub/astra.yaml": MINIMAL,
    }
    top = repository(tmp_path, files)
    analysis = api.resolve(top)
    found = noted(analysis, "CODE_OUTSIDE_ANALYSIS")
    assert found == list(analysis.notes)
    assert [(note.level, note.location.pointer) for note in found] == [
        ("warning", "/outputs/first/recipe/command"),
        ("warning", "/outputs/second/recipe/command"),
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


def test_the_notes_are_those_that_concern_what_the_root_builds(tmp_path: Path) -> None:
    """A fallback pin is noted where a planned result reads through it, as `sub`'s does and
    `inner`'s doesn't; an output with no planned result, and a command naming a path outside its
    analysis, in every analysis read as the root is, each of which the root builds. Each names
    its file from the top of the repository, whichever folder the driving analysis is in."""
    sub = repository(tmp_path, BUILDS) / "sub"
    analysis = api.resolve(sub)
    assert [(note.code, note.location.file) for note in analysis.notes] == [
        ("FALLBACK_PIN", "sub/astra.yaml"),
        ("UNPLANNED_OUTPUT", "astra.yaml"),
        ("UNPLANNED_OUTPUT", "sub/inner/astra.yaml"),
        ("CODE_OUTSIDE_ANALYSIS", "astra.yaml"),
        ("CODE_OUTSIDE_ANALYSIS", "sub/inner/astra.yaml"),
    ]


def test_a_command_gives_each_path_from_the_folder_its_recipe_runs_in(tmp_path: Path) -> None:
    """With `sub` driving, the analysis above it is `paper`, in `..`. `read` reads `paper`'s
    input and its `result` in `paper`'s own `u1`, a result that belongs to `paper`: the model
    gives the place of each from `sub`'s folder, and each command gives its paths from the
    folder its recipe runs in, `read`'s from `sub`'s and `result`'s from `paper`'s."""
    sub = repository(tmp_path, BUILDS) / "sub"
    analysis = api.resolve(sub)
    assert [(each.key, each.folder, dict(each.declares)) for each in analysis.analyses] == [
        ("", ".", {"paper": "paper", "inner": "inner"}),
        ("inner", "inner", {"paper": "paper"}),
        ("paper", "..", {}),
    ]
    assert by_key(analysis)["paper"].inputs == (
        api.Input("paper.inputs.input1", "../data/input1.csv"),
    )
    made, read = analysis.results
    assert (made.id, made.output, made.universe, owner(analysis, made).key) == (
        "paper:result#u1",
        "paper.outputs.result",
        "paper.universes.u1",
        "paper",
    )
    assert made.places == (
        api.Place("result#u1", "../.astra/records/u1/result.json", "../results/u1/result.json"),
    )
    assert (runs_in(analysis, made), made.command) == (
        "..",
        "python make.py 'a' 'results/u1/result.json'",
    )
    assert read.inputs == (
        api.Source("paper.input1", input="paper.inputs.input1"),
        api.Source("paper.result#u1", result="paper:result#u1"),
    )
    assert read.places == (api.Place("read", ".astra/records/read.json", "results/read.json"),)
    assert (runs_in(analysis, read), read.command) == (
        ".",
        "python read.py '../data/input1.csv' '../results/u1/result.json' 'results/read.json'",
    )


# --- insights, evidence and the model as JSON ---


CITED = """\
spec_version: "0.1.0"
label: Cited
description: An analysis whose options cite prior insights.
tags: [example]
inputs:
  input1:
    path: data/input1.csv
    label: The input
decisions:
  decision1:
    label: The decision
    rationale: Both are reasonable.
    tags: [choice]
    options:
      a:
        label: Option a
        insights: [prior1]
      b: {}
      c:
        excluded: It needs data this analysis doesn't have.
outputs:
  output1:
    type: metric
    format: json
    label: The output
    inputs: [input1]
    decisions: [decision1]
    recipe:
      command: python make.py '{inputs.input1}' '{decisions.decision1}' '{output}'
      resources: {cpus: 2, memory: 4GB}
  output2:
    type: table
    format: tar.gz
    recipe:
      command: python make.py '{output}'
universes:
  u1:
    label: The first
    decisions: {decision1: a}
prior_insights:
  prior1:
    claim: Option a is the usual choice.
    scope: The field.
    evidence:
      - doi: 10.1234/example
        version: 2
        quote: {exact: the usual choice, prefix: "is "}
        location: {value: page=3}
findings:
  finding1:
    claim: The output is what it is.
    evidence:
      - artifact: output1
        location: {value: "/value", conforms_to: "https://www.rfc-editor.org/rfc/rfc6901"}
      - artifact: output2
"""
"""An analysis with a prior insight an option cites, backed by a work, and a finding backed by
its two outputs; some elements with every optional field, and some with none."""


@pytest.fixture(scope="module")
def cited(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {"astra.yaml": CITED, "data/input1.csv": "1\n"}
    return repository(tmp_path_factory.mktemp("cited"), files)


def test_evidence_that_cites_an_output_cites_its_planned_results(
    cited: Path, worked: Path, pinning: Path
) -> None:
    """Evidence that cites an output gives the id of each planned result it cites: the one
    result of an output built once, and of an output built per universe, cited without a pin,
    its result in each of the root's universes. Evidence that cites a work cites no result. An
    option names the prior insights that support it by ref, and an insight says which kind it
    is."""
    (root,) = api.resolve(cited).analyses
    (prior,) = root.prior_insights
    (finding,) = root.findings
    assert (prior.ref, prior.kind, finding.ref, finding.kind) == (
        "prior_insights.prior1",
        "prior_insight",
        "findings.finding1",
        "finding",
    )
    assert prior.evidence == (
        api.Evidence(
            doi="10.1234/example",
            version=2,
            quote=api.TextQuoteSelector("the usual choice", prefix="is "),
            location=api.FragmentSelector("page=3"),
        ),
    )
    assert prior.evidence[0].cites is None
    assert prior.evidence[0].artifact is None
    assert [evidence.cites for evidence in finding.evidence] == [("output1#u1",), ("output2",)]
    assert [evidence.artifact for evidence in finding.evidence] == ["output1", "output2"]
    assert [
        (option.id, option.insights, option.excluded) for option in root.decisions[0].options
    ] == [
        ("a", ("prior_insights.prior1",), None),
        ("b", (), None),
        ("c", (), "It needs data this analysis doesn't have."),
    ]
    (insight,) = api.resolve(worked).analyses[0].findings
    assert [evidence.cites for evidence in insight.evidence] == [("output2",)]
    (insight,) = api.resolve(pinning).analyses[0].findings
    assert [evidence.cites for evidence in insight.evidence] == [
        ("subanalysis.output1#u1", "subanalysis.output1#u2")
    ]
    assert [evidence.artifact for evidence in insight.evidence] == ["subanalysis.output1"]


def test_evidence_preserves_an_authored_universe_pin(tmp_path: Path) -> None:
    folder = repository(
        tmp_path,
        {
            "astra.yaml": CITED.replace("artifact: output1", "artifact: output1#u1"),
            "data/input1.csv": "1\n",
        },
    )
    evidence = api.resolve(folder).analyses[0].findings[0].evidence[0]
    assert (evidence.artifact, evidence.cites) == ("output1#u1", ("output1#u1",))
    assert evidence.bindings == (
        api.EvidenceBinding("universes.u1", "outputs.output1", "universes.u1", "output1#u1"),
    )


def nulls(value: Any) -> bool:
    """Whether a JSON value holds a null anywhere."""
    if isinstance(value, dict):
        return any(nulls(item) for item in value.values())
    if isinstance(value, list):
        return any(nulls(item) for item in value)
    return value is None


def test_the_model_writes_as_json_with_no_optional_field_left_null(cited: Path) -> None:
    """The model's JSON holds every field under its name, an optional one left out where it has
    no value, never null, and a list or a map that holds nothing as an empty one. A reference is
    an id, so the JSON is the whole model."""
    written = api.resolve(cited).to_json()
    assert json.loads(json.dumps(written)) == written
    assert not nulls(written)
    assert list(written) == [
        "spec_version",
        "head",
        "analyses",
        "results",
        "notes",
        "schema_version",
    ]
    (root,) = written["analyses"]
    assert root == {
        "key": "",
        "folder": ".",
        "label": "Cited",
        "description": "An analysis whose options cite prior insights.",
        "tags": ["example"],
        "declares": {},
        "switches": [],
        "inputs": [
            {"ref": "inputs.input1", "path": "data/input1.csv", "label": "The input", "tags": []}
        ],
        "decisions": [
            {
                "ref": "decisions.decision1",
                "options": [
                    {
                        "id": "a",
                        "label": "Option a",
                        "tags": [],
                        "insights": ["prior_insights.prior1"],
                    },
                    {"id": "b", "tags": [], "insights": []},
                    {
                        "id": "c",
                        "tags": [],
                        "excluded": "It needs data this analysis doesn't have.",
                        "insights": [],
                    },
                ],
                "label": "The decision",
                "rationale": "Both are reasonable.",
                "tags": ["choice"],
            }
        ],
        "outputs": [
            {
                "ref": "outputs.output1",
                "type": "metric",
                "format": "json",
                "label": "The output",
                "tags": [],
                "resources": {"cpus": 2, "memory": "4GB"},
                "inputs": [{"entry": "input1", "target": "inputs.input1"}],
                "decisions": ["decisions.decision1"],
            },
            {
                "ref": "outputs.output2",
                "type": "table",
                "format": "tar.gz",
                "inputs": [],
                "tags": [],
                "decisions": [],
            },
        ],
        "prior_insights": [
            {
                "ref": "prior_insights.prior1",
                "kind": "prior_insight",
                "claim": "Option a is the usual choice.",
                "evidence": [
                    {
                        "doi": "10.1234/example",
                        "version": 2,
                        "quote": {"exact": "the usual choice", "prefix": "is "},
                        "location": {"value": "page=3"},
                    }
                ],
                "scope": "The field.",
                "tags": [],
            }
        ],
        "findings": [
            {
                "ref": "findings.finding1",
                "kind": "finding",
                "claim": "The output is what it is.",
                "evidence": [
                    {
                        "cites": ["output1#u1"],
                        "artifact": "output1",
                        "bindings": [
                            {
                                "universe": "universes.u1",
                                "output": "outputs.output1",
                                "target_universe": "universes.u1",
                                "result": "output1#u1",
                            }
                        ],
                        "location": {
                            "value": "/value",
                            "conforms_to": "https://www.rfc-editor.org/rfc/rfc6901",
                        },
                    },
                    {
                        "cites": ["output2"],
                        "artifact": "output2",
                        "bindings": [{"output": "outputs.output2", "result": "output2"}],
                    },
                ],
                "tags": [],
            }
        ],
        "universes": [
            {
                "ref": "universes.u1",
                "selection": {"decisions.decision1": "a"},
                "label": "The first",
                "tags": [],
            }
        ],
    }
    assert written["results"] == [
        {
            "id": "output1#u1",
            "output": "outputs.output1",
            "places": [
                {
                    "address": "output1#u1",
                    "record_path": ".astra/records/u1/output1.json",
                    "file_path": "results/u1/output1.json",
                }
            ],
            "universe": "universes.u1",
            "inputs": [{"entry": "input1", "input": "inputs.input1"}],
            "command": "python make.py 'data/input1.csv' 'a' 'results/u1/output1.json'",
        },
        {
            "id": "output2",
            "output": "outputs.output2",
            "places": [
                {
                    "address": "output2",
                    "record_path": ".astra/records/output2.json",
                    "file_path": "results/output2.tar.gz",
                }
            ],
            "inputs": [],
            "command": "python make.py 'results/output2.tar.gz'",
        },
    ]
    assert written["notes"] == []


def test_a_note_and_a_commit_write_as_json_too(tmp_path: Path) -> None:
    """A note is a diagnostic, whose location holds only what it has: no key, commit or URL for
    one in a file of the working tree. An analysis read at a commit gives the commit, and no
    repository where that is the driving analysis's; a result with no command has none in its
    JSON."""
    top = repository(tmp_path, {"astra.yaml": LIB})
    commit = git(top, "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": FROM_COMMIT % commit})
    written = api.resolve(top).to_json()
    assert json.loads(json.dumps(written)) == written
    assert not nulls(written)
    assert [(each["key"], each.get("commit")) for each in written["analyses"]] == [
        ("", None),
        ("lib", {"id": commit}),
    ]
    assert {result["id"]: "command" in result for result in written["results"]} == {
        "lib:out#v1": False,
        "lib:once": False,
        "result": False,
        "alone": True,
    }
    (note,) = written["notes"]
    assert (note["code"], note["level"], note["related"]) == ("FALLBACK_PIN", "note", [])
    assert set(note) == {"code", "level", "message", "location", "related"}
    assert set(note["location"]) == {"file", "pointer", "line", "column"}
    assert (note["location"]["file"], note["location"]["pointer"]) == (
        "astra.yaml",
        "/outputs/result/inputs/0",
    )


def test_an_invalid_analysis_resolves_to_nothing(tmp_path: Path) -> None:
    """`api.resolve` raises InvalidAnalysisError with the report."""
    broken = WORKED_EXAMPLE.replace("{decision1: b}", "{decision1: c}")
    top = repository(tmp_path, {"astra.yaml": broken, "data/input1.csv": "1\n"})
    with pytest.raises(api.InvalidAnalysisError) as raised:
        api.resolve(top)
    assert [d.code for d in raised.value.report.diagnostics] == ["UNKNOWN_OPTION"]
