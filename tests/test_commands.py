"""The commands `info` and `init`, and what they read an analysis through, on what they
promise: output, exit codes and what they leave on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from astra import api
from astra._internal.analysis.stack import bind
from astra._internal.sources.reader import worktree
from astra.cli import main, read_stack
from tests.conftest import MINIMAL, analysis, git, git_init, repository


def astra(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


# --- read_stack ---


def test_read_stack_gives_the_stack_of_an_analysis_that_neednt_be_valid(tmp_path: Path) -> None:
    """Every analysis of the stack of the analysis in a folder, the root first, with the schema
    diagnostics of a declared file that isn't a valid document; none where the root's file
    isn't one."""
    root = MINIMAL + "analyses: {sub: {path: sub}}\n"
    top = repository(tmp_path, {"astra.yaml": root, "sub/astra.yaml": MINIMAL + "name: x\n"})
    stack = read_stack(top)
    assert stack is not None
    assert [str(identity) for identity in stack.analyses] == [".", "sub"]
    assert [(d.code, d.location.file) for d in bind(*worktree(top))[1]] == [
        ("UNKNOWN_FIELD", "sub/astra.yaml")
    ]
    (top / "astra.yaml").write_text(MINIMAL + "name: x\n")
    assert read_stack(top) is None


# --- info ---


ROOT = """\
spec_version: "0.1.0"
label: Example analysis
analyses:
  subanalysis: {path: subanalysis}
  missing: {path: nothere}
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
    decisions: {decision1: a, subanalysis.decision1: a}
  u2:
    derived_from: u1
    decisions: {decision1: b}
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
"""


VALID = ROOT.replace("  missing: {path: nothere}\n", "").replace(", subanalysis.decision1: a", "")
"""`ROOT` without what makes it invalid: a declaration that reaches nothing, and a selection for
a decision no result of the universe uses."""


def test_info_shows_the_analysis_in_brief(tmp_path: Path) -> None:
    """The driving analysis's label and counts, then its inputs, outputs, decisions and
    universes, each universe with what it selects; then each analysis it declares. A switch is
    no output of the resolved analysis, so none is shown; it shows in what is planned, as
    `output1` is built only where the switch takes it."""
    files = {"astra.yaml": MINIMAL, "subanalysis/astra.yaml": SUBANALYSIS, "data/input1.csv": "1\n"}
    top = repository(tmp_path, files)
    switch = "  switch1:\n    switch: decision1\n    cases: {a: output1, b: input1}\nuniverses:\n"
    repository(top, {"astra.yaml": VALID.replace("universes:\n", switch, 1)})
    result = astra("info", "-f", str(top / "astra.yaml"))
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[:2] == ["Example analysis", "Spec version: 0.1.0"]
    assert "Inputs: 1 | Outputs: 1 | Decisions: 1 | Universes: 2" in lines
    assert "Layout: 1 sub-analysis in subanalysis/" in lines
    assert "Planned results: 1" in lines
    shown = " ".join(result.stdout.split())
    for part in ("Inputs:", "Outputs:", "Decisions:", "Universes:"):
        assert f"\n{part}\n" in result.stdout
    assert "input1 │ data/input1.csv" in shown
    assert "output1 │ metric │ json" in shown and "switch1" not in shown
    assert "decision1:" in shown and "Analysis: subanalysis" in shown
    # The effective selection: `u2` is derived from `u1`, and selects `b` itself.
    assert "  u1: decisions.decision1 = a" in lines
    assert "  u2: decisions.decision1 = b" in lines


def test_info_shows_each_other_analysis_of_the_stack_after_the_driving_one(tmp_path: Path) -> None:
    """Each analysis the driving one declares, directly or not, by its key and its file, one
    at a commit with the commit."""
    files = {"astra.yaml": MINIMAL, "subanalysis/astra.yaml": SUBANALYSIS, "data/input1.csv": "1\n"}
    top = repository(tmp_path, files)
    first = git(top, "rev-parse", "HEAD").strip()
    declared = f"  previous: {{path: ., commit: '{first}'}}\ninputs:\n"
    repository(top, {"astra.yaml": VALID.replace("inputs:\n", declared, 1)})
    result = astra("info", "-f", str(top / "astra.yaml"), "-o")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "Analysis: subanalysis  subanalysis/astra.yaml" in lines
    assert f"Analysis: previous  astra.yaml at {first}" in lines
    assert result.stdout.count("\nOutputs:\n") == 3 and "\nDecisions:\n" not in result.stdout
    assert lines.index("Example analysis") < lines.index(
        "Analysis: subanalysis  subanalysis/astra.yaml"
    )


def test_info_of_an_analysis_that_breaks_a_must_shows_why_and_exits_1(
    tmp_path: Path, outside: Path
) -> None:
    """Only a valid analysis resolves, as text or as JSON: the errors are shown as
    `astra validate` shows them."""
    files = {"astra.yaml": VALID, "subanalysis/astra.yaml": SUBANALYSIS + "name: x\n"}
    declaring = repository(tmp_path / "declaring", {**files, "data/input1.csv": "1\n"})
    invalid = analysis(git_init(tmp_path / "repo"), MINIMAL + "name: x\n")
    for folder in (declaring, invalid, analysis(outside)):
        result = astra("info", "--file", str(folder / "astra.yaml"))
        assert result.exit_code == 1
        assert result.stdout == astra("validate", str(folder)).stdout
        assert "error" in result.stdout


def test_info_exits_1_where_there_is_no_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(git_init(tmp_path))
    result = astra("info")
    assert result.exit_code == 1
    assert result.stderr.startswith("Error: No astra.yaml found in current directory or parents.")


def test_info_reads_the_astra_yaml_here_or_above(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = repository(tmp_path, {"astra.yaml": MINIMAL})
    (top / "src").mkdir()
    monkeypatch.chdir(top / "src")
    result = astra("info")
    assert result.exit_code == 0
    assert "Inputs: 0 | Outputs: 1 | Decisions: 0 | Universes: 0" in result.stdout


def test_info_shows_only_the_parts_asked_for(tmp_path: Path) -> None:
    files = {"astra.yaml": MINIMAL, "subanalysis/astra.yaml": SUBANALYSIS, "data/input1.csv": "1\n"}
    top = repository(tmp_path, files)
    repository(top, {"astra.yaml": VALID})
    shown = astra("info", "-f", str(top / "astra.yaml"), "-d", "-i").stdout
    parts = [part for part in ("Inputs:", "Outputs:", "Decisions:", "Universes:")]
    assert [part for part in parts if f"\n{part}\n" in shown] == ["Inputs:", "Decisions:"]


def test_info_json_is_the_analysis_as_it_resolves(tmp_path: Path) -> None:
    """The resolved analysis, as `api.resolve` gives it, which only a valid analysis has: one
    that breaks a MUST gets the validator's report, and exit 1."""
    files = {"astra.yaml": MINIMAL, "subanalysis/astra.yaml": SUBANALYSIS, "data/input1.csv": "1\n"}
    top = repository(tmp_path, files)
    repository(top, {"astra.yaml": VALID})
    result = astra("info", "-f", str(top / "astra.yaml"), "--json")
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document == api.resolve(top).to_json()
    root, sub = document["analyses"]
    assert (root["key"], root["label"]) == ("", "Example analysis")
    assert root["declares"] == {"subanalysis": "subanalysis"}
    assert sub["folder"] == "subanalysis"
    repository(top, {"astra.yaml": ROOT})
    result = astra("info", "-f", str(top / "astra.yaml"), "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout) == api.validate(top).to_json()


# --- init ---


def test_init_makes_an_analysis_in_a_new_repository_that_validates(tmp_path: Path) -> None:
    folder = tmp_path / "new" / "analysis"
    result = astra("init", str(folder))
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "✓ created astra.yaml",
        "✓ created .gitignore",
        "✓ created .git",
        f"✓ Converged ASTRA analysis scaffold: {folder}",
    ]
    assert (folder / ".git").is_dir() and (folder / ".gitignore").is_file()
    assert api.validate(folder).diagnostics == ()
    assert astra("validate", str(folder)).exit_code == 0


def test_init_converges_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run again, it changes nothing; on a folder with an astra.yaml of its own, it keeps it.
    Where git knows who commits, the new repository gets a first commit."""
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "astra-tools tests")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "tests@astra.invalid")
    folder = tmp_path / "analysis"
    assert astra("init", str(folder)).exit_code == 0
    assert git(folder, "log", "--format=%s").strip() == "Initial ASTRA analysis structure"
    again = astra("init", str(folder))
    assert (again.exit_code, again.stdout) == (0, f"✓ {folder} already converged\n")
    (folder / "astra.yaml").write_text("mine\n")
    assert astra("init", str(folder)).exit_code == 0
    assert (folder / "astra.yaml").read_text() == "mine\n"
    assert astra("init", str(folder), "--no-git").exit_code == 2  # an analysis is in a repository


def test_init_check_writes_nothing_and_json_reports(tmp_path: Path) -> None:
    folder = tmp_path / "analysis"
    result = astra("init", str(folder), "--check", "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "converged": False,
        "created": ["astra.yaml", ".gitignore", ".git"],
        "repaired": [],
        "unchanged": [],
        "warnings": [],
    }
    assert not folder.exists()
    assert astra("init", str(folder)).exit_code == 0
    done = astra("init", str(folder), "--check")
    assert (done.exit_code, done.stdout) == (0, f"✓ {folder} is converged — nothing to do\n")


def test_init_analysis_writes_an_empty_analysis_and_nothing_else(tmp_path: Path) -> None:
    """What `astra init` and downstream tools scaffold through: an astra.yaml, valid once its
    folder is in a repository, with no universes folder."""
    top = git_init(tmp_path)
    api.init_analysis(top / "stage")
    assert [path.name for path in (top / "stage").iterdir()] == ["astra.yaml"]
    assert 'label: "stage"' in (top / "stage" / "astra.yaml").read_text()
    assert api.validate(top / "stage").diagnostics == ()


def test_init_analysis_is_idempotent(tmp_path: Path) -> None:
    """Called again it changes nothing, and it never writes over an analysis: not one a user
    has edited, and not a link that leads nowhere."""
    top = git_init(tmp_path)
    api.init_analysis(top)
    scaffold = (top / "astra.yaml").read_bytes()
    api.init_analysis(top)
    assert (top / "astra.yaml").read_bytes() == scaffold
    (top / "astra.yaml").write_text(MINIMAL)
    api.init_analysis(top)
    assert (top / "astra.yaml").read_text() == MINIMAL
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "astra.yaml").symlink_to("nowhere.yaml")
    api.init_analysis(linked)
    assert (linked / "astra.yaml").is_symlink() and not (linked / "nowhere.yaml").exists()


def test_init_inside_a_working_tree_makes_no_repository_through_the_cli(tmp_path: Path) -> None:
    top = git_init(tmp_path)
    result = astra("init", str(top / "stage"))
    assert result.exit_code == 0 and "✓ created .git" not in result.stdout.splitlines()
    assert not (top / "stage" / ".git").exists()


def test_init_exits_2_for_a_file(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x")
    assert astra("init", str(tmp_path / "file")).exit_code == 2


def test_init_makes_the_repository_where_git_knows_no_one_to_commit_as(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a user name and email, there is no first commit, and the repository is made
    all the same."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("EMAIL", "")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.delenv(f"GIT_{who}_NAME", raising=False)
        monkeypatch.delenv(f"GIT_{who}_EMAIL", raising=False)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    folder = tmp_path / "analysis"
    result = astra("init", str(folder))
    assert result.exit_code == 0 and "✓ created .git" in result.stdout
    assert (folder / ".git").is_dir() and (folder / "astra.yaml").is_file()
    assert astra("init", str(folder), "--check").exit_code == 0
