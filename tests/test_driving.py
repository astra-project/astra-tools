"""Driving and consuming, the rules on selections: which declarations are driven, and
`DUPLICATE_ELEMENT`, `LOOPING_KEY`, `KEY_THROUGH_COMMIT`, `MISSING_DECISION` and
`UNKNOWN_PIN_UNIVERSE`, with what isn't checked through an undetermined analysis, a name that
names nothing or a key that loops; and the universe each pin and import names.

The first stacks hold `stage`, which declares `inner`, `again: {path: .}` and `parent: {path: ..}`,
with the root declaring `inner` a second time: a keeping one, whose keys spell `stage.inner.d` and
`inner.d`, and a breaking one. Then come keys through a declaration with a `commit`, whose
analysis is only read. The last has `output5`, reading the remote `subanalysis`, with the import
`subanalysis_v1`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from astra import api
from astra._internal.analysis import rules
from astra._internal.analysis.rules.context import Context
from astra._internal.analysis.stack import Element, Identity, Stack, bind
from astra._internal.analysis.universes import Chain, built, imports, pins
from astra._internal.documents.catalogue import Catalogue
from astra._internal.sources.git import Repository
from astra._internal.sources.reader import WorktreeReader
from tests.conftest import by_url, git, repository
from tests.spec import SPEC

OUTPUT = """\
outputs:
  %s:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
"""

INNER = (
    """spec_version: "0.1.0"
decisions:
  d:
    options: {a: {}, b: {}}
"""
    + OUTPUT % "inner_result"
)

STAGE = """spec_version: "0.1.0"
analyses:
  inner: {path: inner}
  again: {path: .}
  parent: {path: ..}
decisions:
  d:
    options:
      a: {}
      b: {}
      c: {excluded: It isn't what stage is for.}
""" + (OUTPUT % "stage_result").replace(
    "    recipe:", "    decisions: [d, inner.d, parent.decision1]\n    recipe:"
)
"""`stage`: a sub-analysis, so it has no universes, and the root's universes set its
decisions."""

LIB = (
    """spec_version: "0.1.0"
analyses:
  deep: {path: deep}
  parent: {path: ..}
"""
    + OUTPUT % "lib_result"
)
"""An analysis with no decisions, which declares another and its parent."""

ROOT = (
    """spec_version: "0.1.0"
analyses:
  stage: {path: stage}
  stage2: {path: stage}
  inner: {path: stage/inner}
  lib: {path: lib}
  self: {path: .}
  bad: {path: bad}
decisions:
  decision1:
    options: {a: {}, b: {}}
"""
    + (OUTPUT % "result").replace(
        "    recipe:", "    decisions: [decision1, stage.d, stage.inner.d]\n    recipe:"
    )
    + """\
universes:
  u1:
    decisions: {decision1: a, stage.d: a, stage.inner.d: a}
  u2:
    decisions: {decision1: b, stage.d: a, inner.d: b}
  u3:
    derived_from: u1
    decisions: {stage.inner.d: b}
"""
)

KEPT_FILES = {
    "astra.yaml": ROOT.replace("  bad: {path: bad}\n", ""),
    "stage/astra.yaml": STAGE,
    "stage/inner/astra.yaml": INNER,
    "lib/astra.yaml": LIB,
    "lib/deep/astra.yaml": 'spec_version: "0.1.0"\n' + OUTPUT % "deep_result",
}

BROKEN_FILES = {
    **KEPT_FILES,
    "astra.yaml": ROOT
    + """\
  two_keys:
    decisions: {decision1: a, stage.d: a, stage.inner.d: a, inner.d: a}
  other_key:
    derived_from: u1
    decisions: {inner.d: b}
  again:
    decisions: {decision1: a, stage2.again.d: c, stage.inner.d: a}
  parent:
    decisions: {stage.d: a, stage.inner.d: a, stage.parent.decision1: a}
  itself:
    decisions: {self.decision1: a, stage.d: a, stage.inner.d: a}
  unset:
    decisions: {decision1: b}
  through_bad:
    decisions: {decision1: a, stage.d: a, stage.inner.d: a, bad.parent.decision1: a}
  through_nothing:
    decisions: {decision1: a, stage.d: a, stage.inner.d: a, stage.nothere.parent.decision1: a}
""",
    "bad/astra.yaml": LIB + "name: not a field\n",
}

CHECKED = rules.universes.CODES | rules.driving.CODES
"""The codes of the rules on selections."""

ROOT_ID = Identity("")


def found(report: api.ValidationReport) -> list[tuple[str, str, str, str | None]]:
    return [
        (d.code, d.location.file, d.location.pointer, d.location.key)
        for d in report.diagnostics
        if d.code in CHECKED
    ]


def bound(top: Path, folder: str = "") -> Stack:
    stack = bind(WorktreeReader(top, Repository(top)), folder)[0]
    assert stack is not None
    return stack


def driven(stack: Stack) -> dict[Identity, tuple[Chain, ...]]:
    """The chains each analysis's universes drive, given what they use (Results *uses*)."""
    return dict(Context(stack, Catalogue.load()).driven)


def chains(stack: Stack, identity: Identity = ROOT_ID) -> set[tuple[str, ...]]:
    return {tuple(d.id for d in chain) for chain in driven(stack)[identity]}


@pytest.fixture(scope="module")
def kept(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repository(tmp_path_factory.mktemp("kept"), KEPT_FILES)


@pytest.fixture(scope="module")
def broken(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repository(tmp_path_factory.mktemp("broken"), BROKEN_FILES)


@pytest.fixture(scope="module")
def broken_report(broken: Path) -> api.ValidationReport:
    return api.validate(broken)


# --- Which declarations are driven ---


def test_each_chain_a_key_goes_through_is_driven_on_its_own(kept: Path) -> None:
    """`stage.inner.d` drives `stage` and, through it, `stage`'s `inner`, and `inner.d`
    the root's own `inner`; `lib`, with no decisions, is driven whenever the driver's file
    declares it, and so is its `deep`, but not its `..`, which leads back; nor `self`, `stage2`
    or `stage`'s `again`, which no key goes through."""
    assert chains(bound(kept)) == {
        ("stage",),
        ("stage", "inner"),
        ("inner",),
        ("lib",),
        ("lib", "deep"),
    }


def test_driving_extends_through_no_declaration_with_a_commit(tmp_path: Path) -> None:
    """`lib`, with no decisions, is driven where the root declares it by `path` alone, and so is
    its `deep`, none of whose decisions the root's universes use; declared with a `commit`, by
    `path` or by `url` (the root's own top at that commit), an analysis is only read, so neither
    it nor what it declares is driven or built in the root's universes."""
    files = {"astra.yaml": 'spec_version: "0.1.0"\n', "lib/astra.yaml": LIB}
    top = repository(tmp_path, {**files, "lib/deep/astra.yaml": INNER})
    first = git(top, "rev-parse", "HEAD").strip()
    root = (
        'spec_version: "0.1.0"\n'
        "analyses:\n"
        "  here: {path: lib}\n"
        f"  old: {{path: lib, commit: '{first}'}}\n"
        f"  remote: {{url: '{top.as_uri()}', commit: '{first}'}}\n"
        "decisions:\n"
        "  decision1:\n"
        "    options: {a: {}, b: {}}\n"
        + (OUTPUT % "result").replace("    recipe:", "    decisions: [decision1]\n    recipe:")
        + "universes:\n"
        "  u1:\n"
        "    decisions: {decision1: a}\n"
    )
    stack = bound(repository(top, {"astra.yaml": root}))
    assert chains(stack) == {("here",), ("here", "deep")}
    assert list(built(driven(stack)[ROOT_ID], ROOT_ID)) == [
        ROOT_ID,
        Identity("lib"),
        Identity("lib/deep"),
    ]


def test_the_analyses_built_in_a_universe_are_known_by_identity(kept: Path) -> None:
    """The driver itself, and each analysis a driven declaration reaches, once however
    many chains reach it (`stage.inner` and `inner`)."""
    stack = bound(kept)
    assert list(built(driven(stack)[ROOT_ID], ROOT_ID)) == [
        ROOT_ID,
        Identity("stage"),
        Identity("stage/inner"),
        Identity("lib"),
        Identity("lib/deep"),
    ]


def test_a_key_that_loops_drives_nothing(broken: Path) -> None:
    """`stage2.again.d` loops, so it drives neither `stage2` nor `again`."""
    found = chains(bound(broken))
    assert ("stage2",) not in found
    assert ("stage2", "again") not in found


def test_a_stack_driven_as_written_breaks_no_rule_on_selections(kept: Path) -> None:
    """`stage.inner.d` and `inner.d` spell one decision, set under either in different
    universes; u3 changes it under the key it inherits."""
    assert found(api.validate(kept)) == []


# --- the rules ---


def test_each_rule_on_driving_is_broken(broken_report: api.ValidationReport) -> None:
    """Two own keys spelling one decision, even selecting one option, and a key spelling
    an inherited decision under another key (DUPLICATE_ELEMENT); `stage.again.d` written through
    `again: {path: .}`, `stage.parent.decision1` back to the root, and `self.decision1`
    (LOOPING_KEY); and a universe that leaves unset decisions driven by another universe's keys
    (MISSING_DECISION). A key that loops still names its decision, so the excluded `stage.d: c`
    is EXCLUDED_OPTION_SELECTED and `unset`'s neighbours aren't missing."""
    assert found(broken_report) == [
        ("DUPLICATE_ELEMENT", "astra.yaml", "/universes/two_keys/decisions", "inner.d"),
        ("DUPLICATE_ELEMENT", "astra.yaml", "/universes/other_key/decisions", "inner.d"),
        ("EXCLUDED_OPTION_SELECTED", "astra.yaml", "/universes/again/decisions", "stage2.again.d"),
        ("LOOPING_KEY", "astra.yaml", "/universes/again/decisions", "stage2.again.d"),
        ("LOOPING_KEY", "astra.yaml", "/universes/parent/decisions", "stage.parent.decision1"),
        ("LOOPING_KEY", "astra.yaml", "/universes/itself/decisions", "self.decision1"),
        ("MISSING_DECISION", "astra.yaml", "/universes/unset/decisions", None),
        ("MISSING_DECISION", "astra.yaml", "/universes/unset/decisions", None),
    ]


def test_duplicate_element_names_the_other_key(broken_report: api.ValidationReport) -> None:
    """Each decision has one key, so the message says which to remove, and the other key is a
    related place."""
    two, inherited = [d for d in broken_report.diagnostics if d.code == "DUPLICATE_ELEMENT"]
    assert "`inner.d` and `stage.inner.d` spell one decision" in two.message
    assert [(r.pointer, r.key) for r in two.related] == [
        ("/universes/two_keys/decisions", "stage.inner.d")
    ]
    assert "inherits as `stage.inner.d`" in inherited.message
    assert [(r.pointer, r.key) for r in inherited.related] == [
        ("/universes/u1/decisions", "stage.inner.d")
    ]


def test_looping_key_says_how_to_key_the_decision(broken_report: api.ValidationReport) -> None:
    """`stage.d` is never written `stage.again.d`, and the root's own decisions are keyed by their
    ids alone."""
    messages = [d.message for d in broken_report.diagnostics if d.code == "LOOPING_KEY"]
    assert "leads back to `stage2`, already on its chain" in messages[0]
    assert "key the decision as `stage2.d`" in messages[0]
    for message in messages[1:]:
        assert "leads back to this analysis" in message
        assert "key the decision as `decision1`" in message


def test_missing_decision_names_each_decision_unset(broken_report: api.ValidationReport) -> None:
    """Whichever universe has the key that drives `stage` and `inner`, `unset` sets their
    decisions."""
    messages = [
        d.message
        for d in broken_report.diagnostics
        if d.code == "MISSING_DECISION" and d.location.file == "astra.yaml"
    ]
    assert [message.split("`")[3] for message in messages] == ["stage.d", "stage.inner.d"]
    assert "this analysis's universes drive `stage`" in messages[0]


def test_nothing_through_an_undetermined_analysis_or_a_name_that_names_nothing(
    broken_report: api.ValidationReport,
) -> None:
    """`bad.parent.decision1` is judged up to `bad`, whose file is invalid, and
    `stage.nothere.parent.decision1` up to `nothere`, which `stage` doesn't declare: neither loops;
    no decision of `bad` is missing; the second names nothing."""
    reported = {
        (d.code, d.location.key)
        for d in broken_report.diagnostics
        if d.location.pointer.startswith(("/universes/through_", "/universes/bad"))
        or d.location.file == "bad/astra.yaml"
    }
    assert reported == {
        ("UNRESOLVED_ADDRESS", "stage.nothere.parent.decision1"),
        ("UNKNOWN_FIELD", "name"),
    }


# --- Keys through a commit: KEY_THROUGH_COMMIT ---

DECIDED = """spec_version: "0.1.0"
decisions:
  d:
    options: {a: {}, b: {}}
""" + (OUTPUT % "out").replace("    recipe:", "    decisions: [d]\n    recipe:")
"""An analysis with a decision `d`, which its `out`, built per universe, uses."""

NOWHERE = "file:///nowhere/at/all.git"
"""A remote no commit can be got from."""


def declaring(analyses: str, text: str = DECIDED) -> str:
    """`text`, which declares `analyses` (a flow map)."""
    return text.replace('spec_version: "0.1.0"\n', f'spec_version: "0.1.0"\nanalyses: {analyses}\n')


def keying(analyses: str, keys: str = "", outputs: str = "") -> str:
    """A root that declares `analyses` (a flow map), with `outputs` beside its `result`, and a
    `u1` that sets `keys` (flow map entries) beside its own `decision1`: `result` lists each
    decision they key, so that `u1` uses it."""
    listed = ", ".join(
        ("decision1", *(key.split(":")[0].strip() for key in keys.split(",") if key))
    )
    result = (OUTPUT % "result").replace("    recipe:", f"    decisions: [{listed}]\n    recipe:")
    selection = ", ".join(filter(None, ("decision1: a", keys)))
    return declaring(
        analyses,
        'spec_version: "0.1.0"\ndecisions:\n  decision1:\n    options: {a: {}, b: {}}\n'
        + result
        + outputs
        + f"universes:\n  u1:\n    decisions: {{{selection}}}\n",
    )


def keyed(report: api.ValidationReport) -> list[tuple[str, str, str | None, str | None]]:
    """Each KEY_THROUGH_COMMIT, as its file, its pointer, its key and its commit."""
    return [
        (d.location.file, d.location.pointer, d.location.key, d.location.commit)
        for d in report.diagnostics
        if d.code == "KEY_THROUGH_COMMIT"
    ]


def head(top: Path) -> str:
    return git(top, "rev-parse", "HEAD").strip()


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A repository whose top and `stage` each hold `DECIDED`."""
    return repository(tmp_path / "library", {"astra.yaml": DECIDED, "stage/astra.yaml": DECIDED})


@pytest.mark.parametrize(
    ("analyses", "key", "through", "why"),
    [
        (  # case 136
            "{remote: {url: '<url>', commit: '<remote>'}}",
            "remote.d",
            "remote",
            "declared by `url` and `commit`",
        ),
        (  # case 137
            "{old: {path: stage, commit: '<first>'}}",
            "old.d",
            "old",
            "declared with a `commit`",
        ),
        (  # its own folder at an earlier commit: another analysis, so no LOOPING_KEY
            "{previous: {path: ., commit: '<first>'}}",
            "previous.d",
            "previous",
            "declared with a `commit`",
        ),
        (  # case 138: through a sub-analysis, then its remote
            "{stage: {path: stage}}",
            "stage.remote.d",
            "stage.remote",
            "declared by `url` and `commit`",
        ),
        (  # a sub-analysis at an earlier commit, then its parent there
            "{old: {path: stage, commit: '<first>'}}",
            "old.parent.d",
            "old",
            "declared with a `commit`",
        ),
        (  # an unreachable remote: the key still goes through it
            f"{{remote: {{url: '{NOWHERE}', commit: '{'0' * 40}'}}}}",
            "remote.d",
            "remote",
            "declared by `url` and `commit`",
        ),
    ],
    ids=["url", "path-commit", "self-commit", "to-remote", "to-parent", "unreachable"],
)
def test_a_key_through_a_declaration_with_a_commit_breaks_key_through_commit(
    tmp_path: Path, library: Path, analyses: str, key: str, through: str, why: str
) -> None:
    """Reported at the key, naming the declarations up to the first with a `commit`, whose
    analysis is only read, never driven, whether or not it can be got. Such a key still drives
    for the other rules, so it breaks this one rule, and no LOOPING_KEY."""
    url, remote = library.as_uri(), head(library)
    stage = declaring(f"{{parent: {{path: ..}}, remote: {{url: '{url}', commit: '{remote}'}}}}")
    top = repository(tmp_path / "root", {"astra.yaml": DECIDED, "stage/astra.yaml": stage})
    text = analyses.replace("<url>", url).replace("<remote>", remote).replace("<first>", head(top))
    report = api.validate(repository(top, {"astra.yaml": keying(text, f"{key}: a")}))
    assert keyed(report) == [("astra.yaml", "/universes/u1/decisions", key, None)]
    (diagnostic,) = [d for d in report.diagnostics if d.code == "KEY_THROUGH_COMMIT"]
    assert (
        f"`{key}` goes through `{through}`, {why}, whose analysis is only read, never driven: "
        "remove the key" in diagnostic.message
    )
    others = {d.code for d in report.diagnostics} - {"KEY_THROUGH_COMMIT", "REMOTE_UNREACHABLE"}
    assert others == set(), [d.message for d in report.diagnostics]


def test_a_key_through_a_commit_that_sets_some_decisions_has_nothing_missing(
    tmp_path: Path,
) -> None:
    """The root reads `out` unpinned, which uses `d` and `e`, and keys only `d` through a
    declaration with a `commit`: the analysis is driven only by that key, and isn't driven under
    the specification, so no MISSING_DECISION for `e` follows, whose advice, to set it too,
    KEY_THROUGH_COMMIT's contradicts; nor, as the key drives `old`, any UNDRIVEN_DECLARATION or
    NOT_BUILT_IN_UNIVERSE on reading it."""
    both = DECIDED.replace("decisions:\n  d:\n", "decisions:\n  e:\n    options: {a: {}}\n  d:\n")
    both = both.replace("    decisions: [d]\n", "    decisions: [d, e]\n")
    top = repository(tmp_path / "root", {"astra.yaml": DECIDED, "stage/astra.yaml": both})
    root = keying(f"{{old: {{path: stage, commit: '{head(top)}'}}}}", "old.d: a")
    root = root.replace("    decisions: [", "    inputs: [old.out]\n    decisions: [", 1)
    report = api.validate(repository(top, {"astra.yaml": root}))
    assert [d.code for d in report.diagnostics] == ["KEY_THROUGH_COMMIT"], [
        d.message for d in report.diagnostics
    ]


def test_a_key_through_a_commit_in_a_universe_with_no_effective_selection_is_reported(
    tmp_path: Path,
) -> None:
    """`unknown` derives from no universe, so it has no effective selection, but its own keys
    are still checked by KEY_THROUGH_COMMIT, as by LOOPING_KEY."""
    top = repository(tmp_path / "root", {"astra.yaml": DECIDED, "stage/astra.yaml": DECIDED})
    root = keying(f"{{old: {{path: stage, commit: '{head(top)}'}}}}")
    root += "  unknown:\n    derived_from: nowhere\n    decisions: {old.d: a}\n"
    report = api.validate(repository(top, {"astra.yaml": root}))
    assert keyed(report) == [("astra.yaml", "/universes/unknown/decisions", "old.d", None)]


def test_reading_an_analysis_from_a_commit_unpinned_suggests_a_pin(
    tmp_path: Path, library: Path
) -> None:
    """Where what is read in a universe of the root is of an analysis from a commit, which no
    universe here may drive, NOT_BUILT_IN_UNIVERSE and UNDRIVEN_DECLARATION say so: an output
    is read pinned to one of that analysis's own universes, and a decision isn't used at all.
    Neither advises driving it, which would break KEY_THROUGH_COMMIT."""
    top = repository(tmp_path / "root", {"astra.yaml": DECIDED, "stage/astra.yaml": DECIDED})
    reading = (
        (OUTPUT % "reading")
        .removeprefix("outputs:\n")
        .replace(
            "    recipe:", "    inputs: [old.out, remote.out]\n    decisions: [old.d]\n    recipe:"
        )
    )
    analyses = (
        f"{{old: {{path: stage, commit: '{head(top)}'}}, "
        f"remote: {{url: '{library.as_uri()}', commit: '{head(library)}'}}}}"
    )
    report = api.validate(repository(top, {"astra.yaml": keying(analyses, "", reading)}))
    messages = {
        (d.code, d.location.pointer): d.message
        for d in report.diagnostics
        if d.code in ("NOT_BUILT_IN_UNIVERSE", "UNDRIVEN_DECLARATION")
    }
    assert sorted(messages) == [
        (code, f"/outputs/reading/{at}")
        for code in ("NOT_BUILT_IN_UNIVERSE", "UNDRIVEN_DECLARATION")
        for at in ("decisions/0", "inputs/0", "inputs/1")
    ]
    output = messages["NOT_BUILT_IN_UNIVERSE", "/outputs/reading/inputs/0"]
    assert output.endswith(
        "where that analysis isn't built: it is read through `old`, declared with a `commit`, "
        "whose analysis is only read, never driven. Pin one of its own universes"
    )
    decision = messages["NOT_BUILT_IN_UNIVERSE", "/outputs/reading/decisions/0"]
    assert decision.endswith("never driven. Use a decision of this analysis instead")
    remote = messages["UNDRIVEN_DECLARATION", "/outputs/reading/inputs/1"]
    assert remote.endswith(
        "through `remote`, declared by `url` and `commit`, whose analysis is only read, never "
        "driven: pin one of its own universes"
    )
    listed = messages["UNDRIVEN_DECLARATION", "/outputs/reading/decisions/0"]
    assert listed.endswith("never driven: use a decision of this analysis instead")
    for message in messages.values():
        assert "Drive one from them" not in message
        assert "set a decision through it" not in message


def test_a_remotes_universe_keying_through_a_commit_is_reported_in_its_file(
    tmp_path: Path,
) -> None:
    """In a remote, the remote's own `u1` keys through `previous`, its own folder at an earlier
    commit. It is reported in the remote's file at its commit, and the root's declaration of the
    remote breaks DECLARED_ANALYSIS_INVALID."""
    remote = repository(tmp_path / "remote", {"astra.yaml": DECIDED})
    analyses = f"{{previous: {{path: ., commit: '{head(remote)}'}}}}"
    repository(remote, {"astra.yaml": keying(analyses, "previous.d: a")})
    at = head(remote)
    root = declaring(f"{{remote: {{url: '{remote.as_uri()}', commit: '{at}'}}}}")
    report = api.validate(repository(tmp_path / "root", {"astra.yaml": root}))
    assert keyed(report) == [("astra.yaml", "/universes/u1/decisions", "previous.d", at)]
    assert [d.code for d in report.diagnostics if d.location.commit is None] == [
        "DECLARED_ANALYSIS_INVALID"
    ]


SWITCHING = """\
  chosen:
    switch: decision1
    cases: {a: remote.out#va, b: remote.out#vb}
  reads:
    type: metric
    format: json
    inputs: [chosen]
    recipe:
      command: python make.py '{inputs.chosen}' '{output}'
"""
"""A switch over a remote's `out`, pinned to each of two of the remote's own universes."""


def test_a_switch_over_a_remotes_pinned_results_keeps_key_through_commit(
    tmp_path: Path, library: Path
) -> None:
    """Case 139: a switch's cases read a remote's output pinned to two of its own universes, so
    each universe of the root reads one of them, and none drives the remote."""
    universes = "universes:\n  va: {decisions: {d: a}}\n  vb: {decisions: {d: b}}\n"
    repository(library, {"astra.yaml": DECIDED + universes})
    root = keying(
        f"{{remote: {{url: '{library.as_uri()}', commit: '{head(library)}'}}}}", "", SWITCHING
    )
    root += "  u2:\n    decisions: {decision1: b}\n"
    report = api.validate(repository(tmp_path / "root", {"astra.yaml": root}))
    assert (report.diagnostics, report.valid) == ((), True)


# --- Pins and imported universes ---

SUBANALYSIS = """\
spec_version: "0.1.0"
analyses:
  inner: <inner>
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
  u1:
    decisions: {decision1: a}
  v1:
    decisions: {decision1: b}
  inner_w1: {analysis: inner, universe: w1}
"""
"""`subanalysis`, the top of a repository of its own, with universes `u1` and `v1` of its own and
an import of its `inner`'s `w1`."""

SUBANALYSIS_INNER = """\
spec_version: "0.1.0"
decisions:
  e:
    options: {a: {}, b: {}}
outputs:
  output2:
    type: metric
    format: json
    decisions: [e]
    recipe:
      command: python make.py '{decisions.e}' '{output}'
universes:
  w1:
    decisions: {e: a}
"""
"""`subanalysis`'s `inner`, the top of another, with a universe `w1` of its own."""

PINNING = """\
spec_version: "0.1.0"
analyses:
  subanalysis: <subanalysis>
  again: <subanalysis>
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
  output5:
    type: table
    format: csv
    inputs:
      - subanalysis.output1#u1               # the root's u1, where subanalysis isn't built
      - subanalysis.output1#subanalysis_u1   # subanalysis's own u1, imported
      - subanalysis.output1#v1               # subanalysis's own v1
      - subanalysis.output1#subanalysis_v1   # the import of subanalysis's v1
      - output1#u2
      - input1#u1
    recipe:
      command: python make.py '{output}'
  output6:
    type: table
    format: csv
    inputs:
      - subanalysis.output1#v9
      - output1#v1
      - input1#v1
      - subanalysis.output1#inner_w1
      - nothere.output1#v9
      - output1#nothing_v9
    recipe:
      command: python make.py '{output}'
universes:
  u1:
    decisions: {decision1: a}
  u2:
    decisions: {decision1: b}
  subanalysis_u1:                            # an import of subanalysis's u1
    analysis: subanalysis
    universe: u1
  subanalysis_v1:                  # an import of subanalysis's own universe v1
    analysis: subanalysis
    universe: v1
  again_u1: {analysis: again, universe: u1}
  nothing_v9: {analysis: subanalysis, universe: v9}
findings:
  insight1:
    claim: The two universes differ.
    evidence: [{artifact: "output1#u9"}, {artifact: "subanalysis.output1#v1"}]
"""
"""`output5`, and in `output6` a pin for each way to name no universe."""


@pytest.fixture(scope="module")
def pinning(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The root, in a folder beside `subanalysis` and `inner`, each a remote."""
    top = tmp_path_factory.mktemp("pinning")
    inner = by_url(top / "inner", {"astra.yaml": SUBANALYSIS_INNER})
    files = {"astra.yaml": SUBANALYSIS.replace("<inner>", inner), "data/input1.csv": "2\n"}
    subanalysis = by_url(top / "subanalysis", files)
    files = {"astra.yaml": PINNING.replace("<subanalysis>", subanalysis), "data/input1.csv": "1\n"}
    return repository(top / "root", files)


def test_a_pin_names_the_files_entry_or_the_elements_analysiss_universe(pinning: Path) -> None:
    """`#u1` names the root's own `u1`, `#subanalysis_u1` the universe the import names, and
    `#v1`, since the root has no `v1`, `subanalysis`'s, as the import `subanalysis_v1` does; a
    pin on an input names a universe too."""
    stack = bound(pinning)
    named = {
        r.pointer: pinned
        for r, pinned in pins(stack, imports(stack)).items()
        if r.file == ROOT_ID and r.pointer[:2] == ("outputs", "output5")
    }
    subanalysis = Identity("", head(pinning.parent / "subanalysis"))
    assert named == {
        ("outputs", "output5", "inputs", 0): Element(ROOT_ID, "universe", "u1"),
        ("outputs", "output5", "inputs", 1): Element(subanalysis, "universe", "u1"),
        ("outputs", "output5", "inputs", 2): Element(subanalysis, "universe", "v1"),
        ("outputs", "output5", "inputs", 3): Element(subanalysis, "universe", "v1"),
        ("outputs", "output5", "inputs", 4): Element(ROOT_ID, "universe", "u2"),
        ("outputs", "output5", "inputs", 5): Element(ROOT_ID, "universe", "u1"),
    }


def test_imports_of_one_universe_name_that_one_universe(pinning: Path) -> None:
    """An import resolves in its file by identity, under any id and through any
    declaration; one in a declared analysis's file can name the universe of an analysis it
    declares."""
    found = imports(bound(pinning))
    subanalysis = Identity("", head(pinning.parent / "subanalysis"))
    subanalysis_u1 = Element(subanalysis, "universe", "u1")
    assert found[ROOT_ID, "subanalysis_u1"] == found[ROOT_ID, "again_u1"] == subanalysis_u1
    assert found[ROOT_ID, "subanalysis_v1"] == Element(subanalysis, "universe", "v1")
    assert found[ROOT_ID, "nothing_v9"] is None
    inner_w1 = Element(Identity("", head(pinning.parent / "inner")), "universe", "w1")
    assert found[subanalysis, "inner_w1"] == inner_w1


def test_a_pin_that_names_no_universe_breaks_unknown_pin_universe(pinning: Path) -> None:
    """Neither the file nor the element's analysis has the universe, as for an element of
    the file's own analysis; an import in the other analysis's file isn't one of its universes;
    and evidence pins as `Output.inputs` does. A reference that names nothing isn't checked,
    nor a pin naming the file's entry, an import that names nothing."""
    report = api.validate(pinning)
    pinned = [
        (d.location.pointer, d.level)
        for d in report.diagnostics
        if d.code == "UNKNOWN_PIN_UNIVERSE"
    ]
    assert pinned == [
        ("/outputs/output6/inputs/0", "error"),
        ("/outputs/output6/inputs/1", "error"),
        ("/outputs/output6/inputs/2", "error"),
        ("/outputs/output6/inputs/3", "error"),
        ("/findings/insight1/evidence/0/artifact", "error"),
    ]
    messages = [d.message for d in report.diagnostics if d.code == "UNKNOWN_PIN_UNIVERSE"]
    assert "nor has `subanalysis` a universe `v9`" in messages[0]
    assert "is an import in `subanalysis`'s file" in messages[3]


def test_examples_iris_pipeline_drives_as_written(tmp_path: Path) -> None:
    """astra-spec's `examples/iris_pipeline`: the root's universes drive both stages, whose
    `..` and sibling declarations lead nowhere they must set; `mlp_svm` inherits the rest."""
    shutil.copytree(SPEC / "examples" / "iris_pipeline", tmp_path / "pipeline")
    top = repository(tmp_path / "pipeline", {})
    assert found(api.validate(top)) == []
    assert chains(bound(top)) == {("feature_extraction",), ("classification",)}
