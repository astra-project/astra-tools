"""Switches in the resolved analysis, the view and the check: a result read
through a switch (Elements *takes*; Results *plans*, *made from*, *Evidence*), the note on an
output a switch leaves unbuilt, what a universe uses and what is planned there, and what a
switch makes stale.

The model holds what a switch gives, never the switch: what an entry that names one reads, in
the result's `inputs` and in its command, and no output or result for the switch itself.

The stacks are `tests.test_switches`' running example, its nested switches and its switch
between declared analyses; a switch whose cases are each taken in one universe, or none; and
one two of whose options share a case, built as a runner builds it (`conftest.build`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from astra import api
from astra.cli import main
from tests.conftest import build, owner, repository
from tests.test_switches import CHOOSING_FILES, NESTED_FILES, RUNNING_FILES, variant


def astra(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


def results(analysis: api.ResolvedAnalysis) -> set[tuple[str, str]]:
    """Each result: the key of the analysis it belongs to, and its addresses (Results)."""
    return {
        (owner(analysis, r).key, ", ".join(p.address for p in r.places)) for r in analysis.results
    }


def result(analysis: api.ResolvedAnalysis, id_: str) -> api.Result:
    """The result whose id is `id_`."""
    (found,) = [r for r in analysis.results if r.id == id_]
    return found


def noted(analysis: api.ResolvedAnalysis, code: str) -> list[api.Diagnostic]:
    return [note for note in analysis.notes if note.code == code]


def selections(analysis: api.ResolvedAnalysis) -> dict[str, dict[str, str]]:
    """The selection of each of the driving analysis's universes, by the universe's ref."""
    return {universe.ref: dict(universe.selection) for universe in analysis.analyses[0].universes}


@pytest.fixture(scope="module")
def running(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repository(tmp_path_factory.mktemp("running"), RUNNING_FILES)


# --- C. the resolved analysis ---


def test_the_running_example_plans_what_results_lists(running: Path) -> None:
    """Results: the planned results are `output2`, `output1` in `u1` and `u2`, `output6` in
    `u1`, `stage.output3` in `u1`, `u2` and `v1`, and `upstream.output4`; `output6` isn't built
    in `u2`, where `switch1` has no case for `a`."""
    analysis = api.resolve(running)
    assert results(analysis) == {
        ("", "output2"),
        ("", "output1#u1"),
        ("", "output1#u2"),
        ("", "output6#u1"),
        ("", "stage.output3#u1"),
        ("", "stage.output3#u2"),
        ("stage", "output3#v1"),
        ("upstream", "output4"),
    }
    assert {r.id for r in analysis.results} == {
        "output2",
        "output1#u1",
        "output1#u2",
        "output6#u1",
        "stage.output3#u1",
        "stage.output3#u2",
        "stage:output3#v1",
        "upstream:output4",
    }


def test_a_switch_is_no_output_of_the_model(running: Path) -> None:
    """Elements: a switch has no result of its own, and the model holds what it gives, not the
    switch: `switch1` is none of its analysis's outputs, and no result is its."""
    analysis = api.resolve(running)
    assert [output.ref for output in analysis.analyses[0].outputs] == [
        "outputs.output1",
        "outputs.output2",
        "outputs.output6",
    ]
    assert "outputs.switch1" not in {r.output for r in analysis.results}


def test_an_entry_naming_a_switch_reads_the_case_it_takes(running: Path) -> None:
    """Elements: where `decision1` selects `b`, `switch1` takes `stage.output3`, and
    `{inputs.switch1}` is the path of its result there. The entry is kept as written, and what
    it reads is the result of the case taken, as an entry that names an output reads that
    output's."""
    analysis = api.resolve(running)
    six = result(analysis, "output6#u1")
    assert six.inputs == (api.Source("switch1", result="stage.output3#u1"),)
    assert six.command == (
        "python src/output6.py 'results/u1/stage.output3.csv' 'a' 'results/u1/output6.png'"
    )
    assert result(analysis, "output1#u1").inputs == (
        api.Source("input1", input="inputs.input1"),
        api.Source("stage.output3", result="stage.output3#u1"),
        api.Source("upstream.output4", result="upstream:output4"),
    )


def test_an_output_a_switch_leaves_unbuilt_is_noted(running: Path) -> None:
    """The resolved analysis says which outputs aren't built in which universe, and why: the
    switch with no case there, and the option its decision selects. A missing case breaks no
    rule, so it is a note."""
    analysis = api.resolve(running)
    (note,) = noted(analysis, "NOT_BUILT")
    assert (note.level, note.location.file, note.location.pointer) == (
        "note",
        "astra.yaml",
        "/outputs/output6",
    )
    assert note.message == (
        "`output6` isn't built in `u2`: `switch1` has no case there for `a`, the option its "
        "decision selects"
    )
    assert [r.id for r in analysis.results if r.output == "outputs.output6"] == ["output6#u1"]


@pytest.fixture(scope="module")
def nested(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repository(tmp_path_factory.mktemp("nested"), NESTED_FILES)


def test_nested_switches_read_through_each_case_they_take(nested: Path) -> None:
    """Elements: a case that names a switch nests the two, and reading the outer reads what the
    inner takes, in the universe the case is read in; a pinned case reads its target as built in
    its pin's universe; a case on an input reads the input's file."""
    analysis = api.resolve(nested)
    assert results(analysis) == {
        ("", "reader#ua"),
        ("", "reader#ub"),
        ("", "reader#uc"),
        ("", "reader#w"),
        ("", "fit#ua"),
        ("", "fit#w"),
    }
    reads = {
        found.id: (found.inputs, found.command)
        for found in analysis.results
        if found.output == "outputs.reader"
    }
    assert reads == {
        "reader#ua": (
            (api.Source("outer", result="fit#ua"),),
            "python read.py 'results/ua/fit.json' 'results/ua/reader.csv'",
        ),
        "reader#ub": (
            (api.Source("outer", result="fit#w"),),
            "python read.py 'results/w/fit.json' 'results/ub/reader.csv'",
        ),
        "reader#uc": (
            (api.Source("outer", input="inputs.input1"),),
            "python read.py 'data/input1.csv' 'results/uc/reader.csv'",
        ),
        "reader#w": (
            (api.Source("outer", input="inputs.input1"),),
            "python read.py 'data/input1.csv' 'results/w/reader.csv'",
        ),
    }
    assert [output.ref for output in analysis.analyses[0].outputs] == [
        "outputs.fit",
        "outputs.reader",
    ]


def test_a_universe_selects_for_a_nested_switchs_decision_only_where_it_is_taken(
    nested: Path,
) -> None:
    """Results *uses*: `inner`'s decision matters only where `outer` takes it. `ua` and `w`,
    where `outer` takes `inner`, use `decision2`; `ub`, where `outer` takes `fit#w`, a result of
    `w`, and `uc`, where it takes an input, don't."""
    assert selections(api.resolve(nested)) == {
        "universes.ua": {"decisions.decision1": "a", "decisions.decision2": "x"},
        "universes.ub": {"decisions.decision1": "b"},
        "universes.uc": {"decisions.decision1": "c"},
        "universes.w": {"decisions.decision1": "a", "decisions.decision2": "y"},
    }


TAKEN = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}, c: {}}
outputs:
  out_a:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
  out_b:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
  out_c:
    type: metric
    format: json
    decisions: [decision1]
    recipe:
      command: python make.py '{decisions.decision1}' '{output}'
  sw:
    switch: decision1
    cases: {a: out_a, b: out_b, c: out_c}
universes:
  u1:
    decisions: {decision1: a}
  u2:
    decisions: {decision1: b}
"""
"""`sw`, which nothing reads, takes `out_a` in `u1` and `out_b` in `u2`; no universe selects
`c`."""


def test_an_output_a_case_names_is_planned_only_where_it_is_taken(tmp_path: Path) -> None:
    """Results *plans*: the driving analysis plans from its own switches that nothing of its own
    reads, and from its own outputs that no case of its own names, so `sw` plans the case it
    takes where it is built, and `out_a`, `out_b` and `out_c` only there. `out_c`, never taken,
    has no planned result, which is noted."""
    analysis = api.resolve(repository(tmp_path, {"astra.yaml": TAKEN}))
    assert results(analysis) == {("", "out_a#u1"), ("", "out_b#u2")}
    (note,) = noted(analysis, "UNPLANNED_OUTPUT")
    assert (note.level, note.location.pointer) == ("note", "/outputs/out_c")
    assert "only a case of `sw`" in note.message
    assert [output.ref for output in analysis.analyses[0].outputs] == [
        "outputs.out_a",
        "outputs.out_b",
        "outputs.out_c",
    ]


def test_an_output_a_case_names_is_built_everywhere_once_cited(tmp_path: Path) -> None:
    """Results *plans*: one that is also a deliverable must be read or cited elsewhere to be
    built where that case isn't taken. A finding citing `out_c` plans it in each universe, and
    its evidence cites both results."""
    text = TAKEN + (
        "findings:\n  finding1:\n    claim: c is reported.\n    evidence:\n"
        "      - artifact: out_c\n"
    )
    analysis = api.resolve(repository(tmp_path, {"astra.yaml": text}))
    assert results(analysis) == {
        ("", "out_a#u1"),
        ("", "out_b#u2"),
        ("", "out_c#u1"),
        ("", "out_c#u2"),
    }
    assert noted(analysis, "UNPLANNED_OUTPUT") == []
    (finding,) = analysis.analyses[0].findings
    assert [evidence.cites for evidence in finding.evidence] == [("out_c#u1", "out_c#u2")]


@pytest.fixture(scope="module")
def choosing(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repository(tmp_path_factory.mktemp("choosing"), CHOOSING_FILES)


def test_a_switch_between_analyses_plans_the_one_it_takes(choosing: Path) -> None:
    """Elements: a switch can choose between analyses. `refined` reads `fast.fit` in `q` and
    `slow.fit` in `c`; in `m`, `model` has no case for `manual`, so nothing is planned there,
    which is noted, and `m` uses `method` alone; `report` and `tools.helper` are built once."""
    analysis = api.resolve(choosing)
    assert results(analysis) == {
        ("", "refined#q"),
        ("", "fast.fit#q"),
        ("", "refined#c"),
        ("", "slow.fit#c"),
        ("", "report"),
        ("tools", "helper"),
    }
    assert [r for r in analysis.results if r.universe == "universes.m"] == []
    refined = result(analysis, "refined#q")
    assert refined.inputs == (
        api.Source("model", result="fast.fit#q"),
        api.Source("tools.helper", result="tools:helper"),
    )
    assert refined.command == (
        "python refine.py results/q/fast.fit.csv tools/results/helper.csv flat "
        "results/q/refined.csv"
    )
    assert result(analysis, "refined#c").inputs[0] == api.Source("model", result="slow.fit#c")
    (note,) = noted(analysis, "NOT_BUILT")
    assert note.location.pointer == "/outputs/refined"
    assert note.message == (
        "`refined` isn't built in `m`: `model` has no case there for `manual`, the option its "
        "decision selects"
    )
    assert selections(analysis) == {
        "universes.q": {
            "decisions.method": "quick",
            "decisions.prior": "flat",
            "fast.decisions.decision5": "x",
        },
        "universes.c": {
            "decisions.method": "careful",
            "decisions.prior": "flat",
            "slow.decisions.decision5": "y",
        },
        "universes.m": {"decisions.method": "manual"},
    }


GAP = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}}
outputs:
  base:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
  gap:
    switch: decision1
    cases: {b: base}
  reader:
    type: metric
    format: json
    inputs: [gap]
    recipe:
      command: python read.py '{inputs.gap}' '{output}'
universes:
  u1:
    decisions: {decision1: a}
"""
"""`gap` takes nothing in `u1`, the root's only universe, so `reader` is built in none."""


def test_an_output_built_in_none_of_the_roots_universes_has_no_result_to_give(
    tmp_path: Path,
) -> None:
    """Results *built*: `reader` reads `gap` without a pin, and `gap` has no case for `a`, so it
    has no planned result, which is noted twice, and a check has no status to give it; `base`,
    which only a case of `gap` names, is planned only where something planned reads it."""
    top = repository(tmp_path, {"astra.yaml": GAP})
    analysis = api.resolve(top)
    assert results(analysis) == set()
    unplanned = {n.location.pointer: n.message for n in noted(analysis, "UNPLANNED_OUTPUT")}
    assert unplanned == {
        "/outputs/base": "`base` has no planned result: only a case of `gap` names it, so it is "
        "planned only where something planned reads it, and nothing does, so a check of the root "
        "never covers it",
        "/outputs/reader": "`reader` has no planned result: it is built in none of the root's "
        "universes, so a check of the root never covers it",
    }
    (note,) = noted(analysis, "NOT_BUILT")
    assert note.message == (
        "`reader` isn't built in `u1`: `gap` has no case there for `a`, the option its decision "
        "selects"
    )
    report = api.status(top)
    assert (dict(report.statuses), report.evidence) == ({}, ())


ROOTED = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}, c: {}}
  decision2:
    options: {x: {}, y: {}}
outputs:
  base:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
  gap:
    switch: decision1
    cases: {b: base, c: inner}
  inner:
    switch: decision2
    cases: {x: base}
universes:
  u1:
    decisions: {decision1: a}
  u2:
    decisions: {decision1: b}
  u3:
    decisions: {decision1: c, decision2: y}
"""
"""`gap`, which nothing reads, takes nothing in `u1` and, through `inner`, nothing in `u3`."""


def test_a_switch_nothing_reads_is_noted_where_it_takes_nothing(tmp_path: Path) -> None:
    """A switch the root plans from, which nothing reads (Results *plans*), gets a
    `NOT_BUILT` note where it takes nothing, as an output does: `gap` has no case for `a` in
    `u1`, and in `u3` takes `inner`, which has no case for `y`. `inner`, which `gap`'s case
    reads, is left to `gap`'s note."""
    analysis = api.resolve(repository(tmp_path, {"astra.yaml": ROOTED}))
    assert results(analysis) == {("", "base")}
    assert [(n.location.pointer, n.message) for n in noted(analysis, "NOT_BUILT")] == [
        (
            "/outputs/gap",
            "`gap` isn't built in `u1`: it has no case there for `a`, the option its decision "
            "selects",
        ),
        (
            "/outputs/gap",
            "`gap` isn't built in `u3`: `inner` has no case there for `y`, the option its "
            "decision selects",
        ),
    ]


# --- D. the view ---


def test_a_universes_selection_holds_only_the_decisions_it_uses(running: Path) -> None:
    """Results *uses*: `u2` selects `a` for `decision3`, inherited, but doesn't use it, as
    `output6` isn't built there: `switch1` takes nothing. So its selection has no `decision3`,
    which `u1`'s has, and it has no result of `output6`. It keeps what it inherits and uses,
    `stage`'s `decision2`."""
    analysis = api.resolve(running)
    assert selections(analysis) == {
        "universes.u1": {
            "decisions.decision1": "b",
            "decisions.decision3": "a",
            "stage.decisions.decision2": "b",
        },
        "universes.u2": {"decisions.decision1": "a", "stage.decisions.decision2": "b"},
    }
    assert {r.id for r in analysis.results if r.universe == "universes.u2"} == {
        "output1#u2",
        "stage.output3#u2",
    }
    assert {r.id for r in analysis.results if r.universe == "universes.u1"} == {
        "output1#u1",
        "stage.output3#u1",
        "output6#u1",
    }


def test_astra_view_shows_what_each_entry_reads_through_a_switch(running: Path) -> None:
    """`astra view` shows a universe's selection and the results planned in it. In `u2`, where
    `switch1` takes nothing, there is no `decision3` and no `output6`; in `u1`, `output6`'s
    `switch1` reads `stage.output3`'s result there."""
    two = astra("view", "u2", str(running))
    assert two.exit_code == 0
    lines = two.stdout.splitlines()
    assert lines[:3] == [
        "universe u2",
        "  decisions.decision1 = a",
        "  stage.decisions.decision2 = b",
    ]
    assert not any("decision3" in line or "output6" in line for line in lines)
    one = astra("view", "u1", str(running))
    assert one.exit_code == 0
    lines = one.stdout.splitlines()
    assert "  decisions.decision3 = a" in lines
    at = lines.index("output6#u1  results/u1/output6.png")
    assert lines[at + 1] == "  switch1 reads stage.output3#u1"


# --- E. the check ---

CHECKED = """\
spec_version: "0.1.0"
decisions:
  decision1:
    options: {a: {}, b: {}, c: {}}
outputs:
  base:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
  other:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
  sw:
    switch: decision1
    cases: {a: base, b: base, c: other}
  reader:
    type: metric
    format: json
    inputs: [sw]
    recipe:
      command: python read.py '{inputs.sw}' '{output}'
universes:
  u1:
    decisions: {decision1: a}
  u2:
    decisions: {decision1: c}
findings:
  finding1:
    claim: The reader reads the case the switch takes.
    evidence:
      - artifact: sw
"""
"""`a` and `b` share `sw`'s case `base`; `reader` reads `base` in `u1` and `other` in `u2`."""

UNCHANGED = {
    "base": ("unchanged", "present"),
    "other": ("unchanged", "present"),
    "reader#u1": ("unchanged", "present"),
    "reader#u2": ("unchanged", "present"),
}


def statuses(report: api.StatusReport) -> dict[str, tuple[str, str | None]]:
    """Each result's id, and its record's and bytes' statuses."""
    return {id_: (status.state, status.bytes) for id_, status in report.statuses.items()}


def broken(report: api.StatusReport, id_: str) -> list[tuple[str, str]]:
    """Each rule the result `id_` itself breaks: its code, and its level."""
    return [(diagnostic.code, diagnostic.level) for diagnostic in report.statuses[id_].why]


def messages(report: api.StatusReport, id_: str) -> list[str]:
    return [diagnostic.message for diagnostic in report.statuses[id_].why]


def cited(
    resolved: api.ResolvedAnalysis, report: api.StatusReport
) -> dict[str, tuple[tuple[str, ...] | None, str]]:
    """Each evidence of the driving analysis's findings that cites an output: the insight it
    backs, the results it cites, as the model gives them, and its status."""
    cites = {
        (finding.ref, index): evidence.cites
        for finding in resolved.analyses[0].findings
        for index, evidence in enumerate(finding.evidence)
    }
    return {e.insight: (cites[e.insight, e.index], e.state) for e in report.evidence}


@pytest.fixture(scope="module")
def committed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`CHECKED`, built from its commit with the same bytes for every result, its records and
    bytes then committed."""
    top = repository(tmp_path_factory.mktemp("checked"), {"astra.yaml": CHECKED})
    build(top, made=lambda _: b"same\n")
    return repository(top, {})


@pytest.fixture
def checked(committed: Path, tmp_path: Path) -> Path:
    """A copy of `committed` of the test's own."""
    return Path(shutil.copytree(committed, tmp_path / "checked", symlinks=True))


def test_results_read_through_a_switch_are_unchanged_where_nothing_changed(checked: Path) -> None:
    report = api.status(checked)
    assert statuses(report) == UNCHANGED
    assert [(e.insight, e.index, e.state, e.why) for e in report.evidence] == [
        ("findings.finding1", 0, "unchanged", ())
    ]
    assert all(
        status.why == () and status.stale_inputs == () for status in report.statuses.values()
    )
    assert astra("status", str(checked)).exit_code == 0


def test_another_option_selected_for_a_switchs_decision_makes_its_reader_stale(
    checked: Path,
) -> None:
    """Results *made from*: for each switch it reads through, the decision it switches on and
    the option selected for it where it is read, whatever bytes result. `u1` selects `b`,
    whose case is `base` too: `reader` in `u1` reads the same result, and is stale in itself,
    not through what it reads."""
    (checked / "astra.yaml").write_text(
        variant(CHECKED, ("{decision1: a}", "{decision1: b}")), "utf-8"
    )
    report = api.status(checked)
    assert statuses(report) == {**UNCHANGED, "reader#u1": ("stale", "present")}
    assert broken(report, "reader#u1") == [("STALE_RESULT", "error")]
    (message,) = messages(report, "reader#u1")
    assert message.startswith(
        "`sw` switches on `decision1`, which selects `b` in `u1`, where it selected `a` at "
    )
    assert report.statuses["reader#u1"].stale_inputs == ()
    assert api.resolve(checked).results[1].inputs == (api.Source("sw", result="base"),)


def test_another_case_taken_makes_its_reader_stale(checked: Path) -> None:
    """Results *made from*: the case a switch takes, whatever bytes result. `sw`'s case for `a`
    becomes `other`, which has `base`'s bytes; `base`, which no universe now takes, isn't
    planned."""
    text = variant(CHECKED, ("{a: base, b: base, c: other}", "{a: other, b: base, c: other}"))
    (checked / "astra.yaml").write_text(text, "utf-8")
    report = api.status(checked)
    assert statuses(report) == {
        "other": ("unchanged", "present"),
        "reader#u1": ("stale", "present"),
        "reader#u2": ("unchanged", "present"),
    }
    assert broken(report, "reader#u1") == [("STALE_RESULT", "error")]
    (message,) = messages(report, "reader#u1")
    assert message.startswith("`sw`'s case for `a` is `other`, where it was `base` at ")
    assert report.statuses["reader#u1"].stale_inputs == ()


def test_a_result_read_through_a_switch_that_isnt_unchanged_makes_its_reader_stale(
    checked: Path,
) -> None:
    """Results *made from*: `reader` in `u2` reads `other` through `sw`. With `other`'s record
    gone, it is stale only through what it reads: by the entry as written, the switch's, and
    with no rule it breaks itself."""
    (checked / ".astra" / "records" / "other.json").unlink()
    report = api.status(checked)
    assert statuses(report) == {
        **UNCHANGED,
        "other": ("missing", "absent"),
        "reader#u2": ("stale", "present"),
    }
    assert broken(report, "other") == [("MISSING_RECORD", "error")]
    assert (report.statuses["reader#u2"].why, report.statuses["reader#u2"].stale_inputs) == (
        (),
        ("sw",),
    )
    assert astra("status", str(checked)).exit_code == 1


def test_evidence_citing_a_switch_cites_the_case_it_takes_in_each_universe(
    checked: Path,
) -> None:
    """Results *Evidence*: citing a switch without a pin, it cites the result in each of the
    driving analysis's universes of the case the switch takes there, and gets the worst of
    their statuses."""
    report = api.status(checked)
    assert cited(api.resolve(checked), report) == {
        "findings.finding1": (("base", "other"), "unchanged")
    }
    (checked / ".astra" / "records" / "other.json").unlink()
    report = api.status(checked)
    assert cited(api.resolve(checked), report) == {
        "findings.finding1": (("base", "other"), "missing")
    }
    (evidence,) = report.evidence
    assert [(d.code, d.level, d.location.file, d.location.pointer) for d in evidence.why] == [
        ("STALE_EVIDENCE", "error", "astra.yaml", "/findings/finding1/evidence/0/artifact")
    ]


def test_evidence_citing_a_switch_that_takes_nothing_is_missing(checked: Path) -> None:
    """Results *Evidence*: none means `missing`. `gap` has a case for `b` only, which no
    universe selects."""
    text = variant(
        CHECKED, ("  reader:\n", "  gap:\n    switch: decision1\n    cases: {b: base}\n  reader:\n")
    ) + ("  finding2:\n    claim: The gap is cited.\n    evidence:\n      - artifact: gap\n")
    (checked / "astra.yaml").write_text(text, "utf-8")
    report = api.status(checked)
    assert cited(api.resolve(checked), report) == {
        "findings.finding1": (("base", "other"), "unchanged"),
        "findings.finding2": ((), "missing"),
    }
    assert statuses(report) == UNCHANGED
