"""`astra view`: an analysis as it is in one of its universes, shown from its resolved model
(`api.resolve`): the option the universe selects for each decision it uses, then each result
planned in it, with where its bytes go, what each entry of its output's `inputs` reads there
and its command as it runs.

The stack is the worked example, with a `subanalysis` the root's universes drive, and an
`other` from another repository, read pinned to its own `v1`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from astra import api
from astra.cli import main
from tests.conftest import MINIMAL, by_url, git, git_init, repository
from tests.test_resolve import TABLES

ROOT = """\
spec_version: "0.1.0"
analyses:
  subanalysis: {path: subanalysis}
  other: %s
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
  output2:
    type: table
    format: csv
    inputs: [output1#u1, output1#u2, other.out#v1]
    recipe:
      command: python src/output2.py {inputs} '{output}'
universes:
  u1:
    decisions: {decision1: a, subanalysis.decision1: a}
  u2:
    decisions: {decision1: b, subanalysis.decision1: b}
"""

SUBANALYSIS = """\
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
  unread:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
"""

OTHER = """\
spec_version: "0.1.0"
decisions:
  d:
    options: {a: {}, b: {}}
  e:
    options: {a: {}, b: {}}
outputs:
  out:
    type: metric
    format: json
    decisions: [d]
    recipe:
      command: python make.py '{decisions.d}' '{output}'
  out2:
    type: metric
    format: json
    decisions: [e]
    recipe:
      command: python make.py '{decisions.e}' '{output}'
universes:
  v1:
    decisions: {d: b, e: a}
"""

SWITCHED = """\
spec_version: "0.1.0"
inputs:
  input1: {path: data/input1.csv}
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  made:
    type: table
    format: csv
    recipe:
      command: python make.py '{output}'
  chosen:
    switch: decision1
    cases: {a: input1, b: made}
  result:
    type: metric
    format: json
    inputs: [chosen]
    recipe:
      command: python use.py '{inputs.chosen}' '{output}'
universes:
  u1:
    decisions: {decision1: a}
  u2:
    decisions: {decision1: b}
"""
"""`result` reads the switch `chosen`, which takes the input `input1` for `a` and the output
`made`, built once, for `b`."""

FROM_COMMIT = """\
spec_version: "0.1.0"
analyses:
  lib: {path: lib, commit: "%s"}
decisions:
  method:
    options: {a: {}, b: {}}
outputs:
  result:
    type: table
    format: csv
    inputs: [lib.once]
    decisions: [method]
    recipe:
      command: python make.py {inputs} '{decisions.method}' '{output}'
universes:
  u1:
    decisions: {method: a}
"""
"""A root that reads `lib`, at a commit, only as `lib` builds it: its `once`, built once."""


def astra(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


@pytest.fixture(scope="module")
def top(tmp_path_factory: pytest.TempPathFactory) -> Path:
    files = {
        "astra.yaml": ROOT % by_url(tmp_path_factory.mktemp("other"), {"astra.yaml": OTHER}),
        "data/input1.csv": "1\n",
        "subanalysis/astra.yaml": SUBANALYSIS,
    }
    return repository(tmp_path_factory.mktemp("view"), files)


def test_astra_view_shows_the_analysis_in_one_universe(top: Path) -> None:
    """The option `u1` selects for each decision it uses, by the decision's ref, the root's and
    `subanalysis`'s; none of `other`'s `d` and `e`, which no universe of the root uses, as the
    root reads `other` only pinned to its own `v1`. Then each result planned in `u1`, each after
    what it reads: the root's result of `subanalysis`'s `output1`, whose recipe runs in
    `subanalysis`'s folder, and the root's `output1`, with what each entry of its `inputs` reads
    there, an input by its ref and a result by its id. `output2`, built once, and `other`'s
    results in `v1` are planned in no universe of the root's."""
    result = astra("view", "u1", str(top))
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "universe u1",
        "  decisions.decision1 = a",
        "  subanalysis.decisions.decision1 = a",
        "subanalysis.output1#u1  results/u1/subanalysis.output1.json",
        "  $ python make.py 'a' '../results/u1/subanalysis.output1.json'",
        "output1#u1  results/u1/output1.json",
        "  input1 reads inputs.input1",
        "  subanalysis.output1 reads subanalysis.output1#u1",
        "  $ python src/output1.py 'data/input1.csv' 'results/u1/subanalysis.output1.json' 'a' "
        "'results/u1/output1.json'",
    ]


def test_astra_view_in_another_universe(top: Path) -> None:
    """`u2` selects `b` for both decisions, and its results are `u2`'s."""
    result = astra("view", "u2", str(top))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[:3] == [
        "universe u2",
        "  decisions.decision1 = b",
        "  subanalysis.decisions.decision1 = b",
    ]
    ids = [line.split("  ")[0] for line in lines[3:] if not line.startswith(" ")]
    assert ids == ["subanalysis.output1#u2", "output1#u2"]
    assert "  subanalysis.output1 reads subanalysis.output1#u2" in lines
    assert "  $ python make.py 'b' '../results/u2/subanalysis.output1.json'" in lines


def test_astra_view_shows_what_an_entry_reads_through_a_switch(tmp_path: Path) -> None:
    """An entry that names a switch reads what the case the switch takes in the universe names
    (Elements *takes*): the input `input1` in `u1`, and the result of `made` in `u2`, each
    filled into the command."""
    folder = repository(tmp_path, {"astra.yaml": SWITCHED, "data/input1.csv": "1\n"})
    shown = {universe: astra("view", universe, str(folder)) for universe in ("u1", "u2")}
    assert [result.exit_code for result in shown.values()] == [0, 0]
    assert shown["u1"].stdout.splitlines() == [
        "universe u1",
        "  decisions.decision1 = a",
        "result#u1  results/u1/result.json",
        "  chosen reads inputs.input1",
        "  $ python use.py 'data/input1.csv' 'results/u1/result.json'",
    ]
    assert shown["u2"].stdout.splitlines() == [
        "universe u2",
        "  decisions.decision1 = b",
        "result#u2  results/u2/result.json",
        "  chosen reads made",
        "  $ python use.py 'results/made.csv' 'results/u2/result.json'",
    ]


def test_astra_view_shows_no_command_for_what_isnt_built_from_the_working_tree_alone(
    tmp_path: Path,
) -> None:
    """`result#u1` reads `lib`'s own result, from the commit `lib` is read at, by the id
    `lib:once`, which a runner reads at that commit and doesn't build: it has no command to
    show."""
    files = {"astra.yaml": MINIMAL, "lib/astra.yaml": TABLES, "lib/data/table.csv": "1\n"}
    top = repository(tmp_path, files)
    commit = git(top, "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": FROM_COMMIT % commit})
    result = astra("view", "u1", str(top))
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "universe u1",
        "  decisions.method = a",
        "result#u1  results/u1/result.csv",
        "  lib.once reads lib:once",
    ]


@pytest.mark.parametrize("universe", ["u9", "v1"])
def test_astra_view_of_a_universe_the_root_hasnt_is_a_usage_error(top: Path, universe: str) -> None:
    """`v1` is `other`'s universe, not the root's."""
    result = astra("view", universe, str(top))
    assert result.exit_code == 2
    assert f"no universe `{universe}`: its universes are u1, u2" in result.stderr


def test_an_invalid_analysis_has_no_view(tmp_path: Path) -> None:
    """`astra view` prints the validation report, as `astra validate` does, and exits 1."""
    other = by_url(tmp_path / "other", {"astra.yaml": OTHER})
    files = {"astra.yaml": ROOT.replace("decision1: b, ", "") % other, "data/input1.csv": "1\n"}
    files |= {"subanalysis/astra.yaml": SUBANALYSIS}
    folder = repository(tmp_path / "root", files)
    with pytest.raises(api.InvalidAnalysisError):
        api.resolve(folder)
    result = astra("view", "u1", str(folder))
    assert result.exit_code == 1
    assert "MISSING_DECISION" in result.stdout
    assert "astra.yaml: invalid, 1 error(s), 0 warning(s)" in result.stdout


def test_astra_view_is_text_alone(top: Path) -> None:
    """The model as JSON is `api.resolve`'s to give: the command has no `--json`."""
    result = astra("view", "u1", str(top), "--json")
    assert result.exit_code == 2
    assert "No such option" in result.stderr


def test_astra_view_exits_2_where_there_is_no_analysis(tmp_path: Path) -> None:
    assert astra("view", "u1", str(git_init(tmp_path))).exit_code == 2
