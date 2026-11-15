"""The checker: each planned result's status, by the check rules, and the evidence's; what a
result that isn't unchanged breaks itself (`Status.why`) and which of its entries read a result
that isn't what it was made from (`Status.stale_inputs`), which is all a runner goes by;
`api.status`, its report as JSON, and `astra status`.

The stacks are the worked example, built as a runner builds it (`conftest.build`); an `inner`
reached through `inner` and `stage.inner`; an analysis from a commit, read through its records;
and astra-spec's record fixtures, at a planned result's place. At the end, every check code of
rules.json has a case that breaks it, and each edit of the worked example in `EDITS`, its
records committed, gives the effects it lists.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from astra import api
from astra._internal.documents.catalogue import Catalogue
from astra._internal.results.hashing import Digest, digest_bytes
from astra._internal.results.status import CODES
from astra.cli import main
from astra.model.status_report import Status, StatusReport
from tests.conftest import (
    ENVIRONMENT,
    MINIMAL,
    RUNNER,
    build,
    git,
    owner,
    remake,
    repository,
)
from tests.spec import DOCUMENTS
from tests.test_planned import ROOT, SUBANALYSIS
from tests.test_resolve import FROM_COMMIT as DRIVING
from tests.test_resolve import INNER, LIB, PAIR, STAGE
from tests.test_validate import WORKED_EXAMPLE


def astra(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


def statuses(report: StatusReport) -> dict[str, tuple[str, str | None]]:
    """Each result's id, and its record's and bytes' statuses."""
    return {id_: (status.state, status.bytes) for id_, status in report.statuses.items()}


def codes(report: StatusReport, id_: str) -> list[str]:
    """The codes of the rules the result `id_` itself breaks."""
    return [broken.code for broken in report.statuses[id_].why]


def messages(report: StatusReport, id_: str) -> list[str]:
    return [broken.message for broken in report.statuses[id_].why]


def errors(status: Status) -> list[str]:
    """The codes of the `MUST`s a result itself breaks: a result that is stale with none is
    stale only through what it reads."""
    return [broken.code for broken in status.why if broken.level == "error"]


def recorded(status: Status) -> dict[str, Digest]:
    """What a result's record says its recipe read, by entry."""
    assert status.record is not None
    return {
        item.entry: Digest(item.content_hash, item.size)
        for item in status.record.generated_by.inputs
    }


def cited(report: StatusReport) -> list[tuple[str, int, tuple[str, ...] | None, str]]:
    """Each evidence with a status: the insight it backs, which item of its `evidence`, the
    results it cites, as the report's analysis gives them, and its status."""
    insights = {
        insight.ref: insight
        for analysis in report.analysis.analyses
        for insight in (*analysis.prior_insights, *analysis.findings)
    }
    return [
        (each.insight, each.index, insights[each.insight].evidence[each.index].cites, each.state)
        for each in report.evidence
    ]


def rewrite(path: Path, change: Callable[[dict[str, Any]], object]) -> None:
    """Change the JSON value of the record at `path` in place."""
    value = json.loads(path.read_text("utf-8"))
    change(value)
    path.write_text(json.dumps(value), "utf-8")


UNCHANGED = {
    "output1#u1": ("unchanged", "present"),
    "output1#u2": ("unchanged", "present"),
    "output2": ("unchanged", "present"),
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The worked example, committed with its input, and built from that commit."""
    files = {"astra.yaml": WORKED_EXAMPLE, "data/input1.csv": "1\n"}
    top = repository(tmp_path_factory.mktemp("worked"), files)
    build(top)
    return top


@pytest.fixture
def worked(built: Path, tmp_path: Path) -> Path:
    """A copy of `built` of the test's own."""
    return Path(shutil.copytree(built, tmp_path / "worked", symlinks=True))


# --- the worked example: every rule kept, and MISSING_RECORD ---


def test_a_built_analysis_is_unchanged_and_present(worked: Path) -> None:
    """A result for which every rule holds is `unchanged` and `present`, and so is the evidence
    that cites it. A checker reads records only through planned results, so a record of nothing
    planned isn't read."""
    (worked / ".astra" / "records" / "output3.json").write_text("not a record")
    report = api.status(worked)
    assert statuses(report) == UNCHANGED
    assert all(status.why == () for status in report.statuses.values())
    assert all(status.stale_inputs == () for status in report.statuses.values())
    assert cited(report) == [("findings.insight1", 0, ("output2",), "unchanged")]
    assert report.evidence[0].why == ()
    # The report holds the analysis as it resolved, whose results these are, by id: one call
    # tells a runner what the results are and how each stands.
    assert report.analysis == api.resolve(worked)
    assert list(report.statuses) == [result.id for result in report.analysis.results]
    # Each status holds the record at its result's place.
    for id_, status in report.statuses.items():
        assert status.record is not None and status.record.address == id_
        assert status.record.generated_by.environment == ENVIRONMENT


def test_a_result_with_no_record_is_missing(tmp_path: Path) -> None:
    """MISSING_RECORD: a result built nowhere is `missing`, with no recorded bytes (`absent`), and
    neither INVALID_RECORD, MISPLACED_RECORD nor MISSING_RECORD_INPUTS is checked for it, nor
    ABSENT_RESULT, for a result that is `missing`. Its status holds no record."""
    files = {"astra.yaml": WORKED_EXAMPLE, "data/input1.csv": "1\n"}
    report = api.status(repository(tmp_path, files))
    assert statuses(report) == {id_: ("missing", "absent") for id_ in UNCHANGED}
    assert codes(report, "output2") == ["MISSING_RECORD"]
    assert report.statuses["output2"].record is None
    # A result that is missing itself says nothing of what it reads.
    assert report.statuses["output2"].stale_inputs == ()


def test_a_record_missing_at_one_place_makes_that_result_missing(worked: Path) -> None:
    """MISSING_RECORD, at `.astra/records/{universe}/{name}.json`; and a result made from it has
    a valid record, but not what it was made from, so it is stale: through the entry that reads
    it, and by no rule it breaks itself."""
    (worked / ".astra" / "records" / "u2" / "output1.json").unlink()
    report = api.status(worked)
    assert statuses(report)["output1#u2"] == ("missing", "absent")
    assert codes(report, "output1#u2") == ["MISSING_RECORD"]
    (broken,) = report.statuses["output1#u2"].why
    assert (broken.level, broken.location.file) == ("error", ".astra/records/u2/output1.json")
    assert statuses(report)["output2"] == ("stale", "present")
    assert report.statuses["output2"].why == ()
    assert report.statuses["output2"].stale_inputs == ("output1#u2",)


# --- INVALID_RECORD, and astra-spec's record fixtures ---


INVALID = sorted((DOCUMENTS / "invalid").glob("ProvenanceRecord-*.json"))
VALID = sorted((DOCUMENTS / "valid").glob("ProvenanceRecord-*.json"))


def header(fixture: Path) -> str:
    """The code a fixture's `.header` sidecar names, as `# rule: CODE`."""
    text = fixture.with_suffix(".header").read_text("utf-8")
    return next(line.split(":", 1)[1].strip() for line in text.splitlines() if "rule:" in line)


@pytest.mark.parametrize("fixture", INVALID, ids=lambda path: path.stem)
def test_an_invalid_record_fixture_leaves_its_result_missing(worked: Path, fixture: Path) -> None:
    """A record that breaks a parse or schema rule leaves its result `missing`, under
    INVALID_RECORD, whose message ends with the code it breaks, and isn't checked by
    MISPLACED_RECORD or MISSING_RECORD_INPUTS, nor its bytes by ABSENT_RESULT."""
    shutil.copy(fixture, worked / ".astra" / "records" / "output2.json")
    found = api.status(worked).statuses["output2"]
    assert (found.state, found.bytes, found.record) == ("missing", "absent", None)
    assert {(broken.code, broken.level) for broken in found.why} == {("INVALID_RECORD", "error")}
    assert all(broken.message.endswith(f" ({header(fixture)})") for broken in found.why)
    assert all(broken.location.file == ".astra/records/output2.json" for broken in found.why)


@pytest.mark.parametrize("fixture", VALID, ids=lambda path: path.stem)
def test_a_valid_record_fixture_breaks_no_parse_or_schema_rule(worked: Path, fixture: Path) -> None:
    """Read at a planned result's place, it is judged by the other rules: its address and commit
    are another result's, so the result is still missing, but not by INVALID_RECORD."""
    shutil.copy(fixture, worked / ".astra" / "records" / "output2.json")
    found = codes(api.status(worked), "output2")
    assert "INVALID_RECORD" not in found
    assert "MISPLACED_RECORD" in found


def test_a_record_of_a_later_minor_version_is_read_by_the_open_schema(worked: Path) -> None:
    """A field it doesn't know is ignored in a record of a greater minor version, and is
    UNKNOWN_FIELD in one of 0.1; a record below 0.1 has no schema, which is INVALID_RECORD
    itself, so its message names no other code."""
    path = worked / ".astra" / "records" / "output2.json"
    rewrite(path, lambda value: value.update(spec_version="0.2.0", later=1))
    report = api.status(worked)
    assert statuses(report)["output2"] == ("unchanged", "present")
    record = report.statuses["output2"].record
    assert record is not None and record.spec_version == "0.2.0"
    rewrite(path, lambda value: value.update(spec_version="0.1.3"))
    first = api.status(worked).statuses["output2"].why[0]
    assert (first.code, first.location.key) == ("INVALID_RECORD", "later")
    assert first.message.endswith(" (UNKNOWN_FIELD)")
    rewrite(path, lambda value: value.update(spec_version="0.0.9"))
    first = api.status(worked).statuses["output2"].why[0]
    assert (first.code, first.location.pointer) == ("INVALID_RECORD", "/spec_version")
    assert first.message == "records begin at 0.1.0: 0.0.9 has no schema"


# --- MISPLACED_RECORD and MISSING_RECORD_INPUTS ---


def test_a_record_of_another_result_is_misplaced(worked: Path) -> None:
    """MISPLACED_RECORD: a record is the record only of the result its `address` names, so the
    status of the result whose place it is at holds none."""
    records = worked / ".astra" / "records"
    shutil.copy(records / "u1" / "output1.json", records / "u2" / "output1.json")
    report = api.status(worked)
    assert statuses(report)["output1#u2"] == ("missing", "absent")
    assert codes(report, "output1#u2") == ["MISPLACED_RECORD"]
    assert report.statuses["output1#u2"].record is None
    assert report.statuses["output2"].stale_inputs == ("output1#u2",)


def test_a_record_holds_one_item_for_each_entry_its_output_lists(worked: Path) -> None:
    """MISSING_RECORD_INPUTS: exactly one item for each entry its output lists at the record's
    commit, matched by `entry`, and no other item."""
    path = worked / ".astra" / "records" / "output2.json"
    original = json.loads(path.read_text("utf-8"))
    items = original["generated_by"]["inputs"]

    def check(new: list[dict[str, Any]]) -> tuple[str, list[str]]:
        rewrite(path, lambda value: value["generated_by"].update(inputs=new))
        report = api.status(worked)
        return statuses(report)["output2"][0], codes(report, "output2")

    assert check(items[::-1]) == ("unchanged", [])  # their order carries no meaning
    assert check(items[:1]) == ("missing", ["MISSING_RECORD_INPUTS"])
    assert check([*items, items[0]]) == ("missing", ["MISSING_RECORD_INPUTS"])
    extra = {**items[0], "entry": "input1"}
    assert check([*items, extra]) == ("missing", ["MISSING_RECORD_INPUTS"])


def test_a_record_of_an_output_that_lists_no_inputs_has_none(tmp_path: Path) -> None:
    """A record of an output that lists no inputs gives none, and can leave `inputs` out."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL})
    build(top)
    path = top / ".astra" / "records" / "result.json"
    assert json.loads(path.read_text("utf-8"))["generated_by"]["inputs"] == []
    assert statuses(api.status(top)) == {"result": ("unchanged", "present")}
    rewrite(path, lambda value: value["generated_by"].pop("inputs"))
    report = api.status(top)
    assert statuses(report) == {"result": ("unchanged", "present")}
    record = report.statuses["result"].record
    assert record is not None and record.generated_by.inputs == ()


def test_a_record_whose_commit_cant_be_read_makes_its_result_stale(worked: Path) -> None:
    """A valid record naming a commit the repository hasn't makes its result
    `stale`, with that as its reason; and so does one naming a commit at which its output
    isn't there. Its bytes are still compared with the record's, which its status holds."""
    path = worked / ".astra" / "records" / "output2.json"
    rewrite(path, lambda value: value["generated_by"].update(commit="0" * 40))
    report = api.status(worked)
    assert statuses(report)["output2"] == ("stale", "present")
    assert codes(report, "output2") == ["STALE_RESULT"]
    assert "0" * 40 in messages(report, "output2")[0]
    found = report.statuses["output2"]
    assert found.record is not None and found.record.generated_by.commit == "0" * 40
    assert found.stale_inputs == ()  # nothing it reads is compared with what that commit gives
    (worked / "astra.yaml").write_text(MINIMAL)
    git(worked, "commit", "--quiet", "--all", "--message", "minimal")
    before = git(worked, "rev-parse", "HEAD").strip()
    (worked / "astra.yaml").write_text(WORKED_EXAMPLE)
    rewrite(path, lambda value: value["generated_by"].update(commit=before))
    report = api.status(worked)
    assert statuses(report)["output2"] == ("stale", "present")
    assert codes(report, "output2") == ["STALE_RESULT"]
    assert "`output2` names no output" in messages(report, "output2")[0]


# --- STALE_RESULT: when a result is unchanged ---


def test_editing_a_description_or_a_label_changes_nothing(worked: Path) -> None:
    """Editing a description leaves a result unchanged, and so does a label: STALE_RESULT
    compares neither. A finding reworded is in `EDITS`."""
    text = WORKED_EXAMPLE.replace(
        "    type: table\n", "    type: table\n    description: The comparison.\n"
    )
    (worked / "astra.yaml").write_text(text.replace("label: Example", "label: An example"))
    assert statuses(api.status(worked)) == UNCHANGED


@pytest.mark.parametrize(
    "old, new, what",
    [
        ("python src/output1.py", "python3 src/output1.py", "its recipe's command"),
        ("format: json", "format: csv", "its format is `csv`, where it was `json`"),
    ],
)
def test_a_change_to_the_outputs_declaration_makes_it_stale(
    worked: Path, old: str, new: str, what: str
) -> None:
    """STALE_RESULT: its recipe's command, and its format, the extension of its default place
    so that its bytes are absent there too; and `output2`, which reads it, is stale. The first
    breaks the rule itself, at its record; the second only reads results that aren't unchanged,
    by the entries that read them."""
    (worked / "astra.yaml").write_text(WORKED_EXAMPLE.replace(old, new, 1))
    report = api.status(worked)
    assert statuses(report)["output1#u1"][0] == "stale"
    first = report.statuses["output1#u1"].why[0]
    assert (first.code, first.level) == ("STALE_RESULT", "error")
    assert first.message.startswith(what)
    assert first.location.file == ".astra/records/u1/output1.json"
    assert report.statuses["output1#u1"].stale_inputs == ()
    assert statuses(report)["output2"][0] == "stale"
    assert errors(report.statuses["output2"]) == []
    assert report.statuses["output2"].stale_inputs == ("output1#u1", "output1#u2")


def test_the_order_of_inputs_counts_and_that_of_decisions_doesnt(tmp_path: Path) -> None:
    """Results *made from*: its inputs and their order (`{inputs}` passes them in that order),
    and its decisions, in any order (each reaches the recipe by name)."""
    text = WORKED_EXAMPLE.replace(
        "    options:\n      a: {}\n      b: {}\n",
        "    options:\n      a: {}\n      b: {}\n  decision2:\n    options: {c: {}}\n",
    ).replace("decisions: [decision1]", "decisions: [decision1, decision2]")
    text = text.replace("{decision1: a}", "{decision1: a, decision2: c}").replace(
        "{decision1: b}", "{decision1: b, decision2: c}"
    )
    top = repository(tmp_path, {"astra.yaml": text, "data/input1.csv": "1\n"})
    build(top)
    (top / "astra.yaml").write_text(
        text.replace("[decision1, decision2]", "[decision2, decision1]")
    )
    report = api.status(top)
    assert {s[0] for s in statuses(report).values()} == {"unchanged"}
    (top / "astra.yaml").write_text(
        text.replace("[output1#u1, output1#u2]", "[output1#u2, output1#u1]")
    )
    report = api.status(top)
    assert statuses(report)["output2"][0] == "stale"
    assert messages(report, "output2") == [
        "its inputs are [`output1#u2`, `output1#u1`], in that order, where they were "
        f"[`output1#u1`, `output1#u2`] at {git(top, 'rev-parse', 'HEAD').strip()[:12]}"
    ]
    # What it reads is unchanged, each by its entry, in whatever order.
    assert report.statuses["output2"].stale_inputs == ()


def test_a_result_made_again_with_other_bytes_makes_its_readers_stale(worked: Path) -> None:
    """The script `output1`'s recipe runs is edited, and all three stay unchanged;
    once `output1` in `u1` is made again with other bytes, it is unchanged itself, and `output2`
    is stale through the entry that reads it, by no rule of its own: its record gives the bytes
    it read, which aren't the ones `output1`'s record now gives. It stays so until it is
    rebuilt, and is unchanged again where the rebuilt bytes are the same."""
    (worked / "src").mkdir()
    (worked / "src" / "output1.py").write_text("print('edited')\n")
    git(worked, "add", "src")
    git(worked, "commit", "--quiet", "--message", "the script is edited")
    assert statuses(api.status(worked)) == UNCHANGED
    remake(worked, "output1#u1", b"output1#u1\n")  # the same bytes
    assert statuses(api.status(worked)) == UNCHANGED
    remake(worked, "output1#u1", b"other\n")
    report = api.status(worked)
    assert statuses(report)["output1#u1"] == ("unchanged", "present")
    compared = report.statuses["output2"]
    assert (compared.state, compared.bytes, compared.why) == ("stale", "present", ())
    assert compared.stale_inputs == ("output1#u1",)
    assert recorded(compared)["output1#u1"] == digest_bytes(b"output1#u1\n")
    remade = report.statuses["output1#u1"].record
    assert remade is not None and remade.content_hash == digest_bytes(b"other\n").content_hash
    remake(worked, "output2", b"output2\n")
    assert statuses(api.status(worked)) == UNCHANGED


# --- What a runner goes by, once it has rebuilt what a result reads ---


def test_a_result_stale_only_through_what_it_reads_breaks_no_rule_itself(worked: Path) -> None:
    """Results *made from*: a result made from a stale one is stale only until that one is
    rebuilt with the hash it recorded. `output1`'s command changes, so both its results break
    STALE_RESULT themselves, and read nothing that isn't unchanged; `output2` is stale only
    through them: no error in its `why`, both entries in `stale_inputs`, and its record still
    there, giving for each entry the bytes its recipe read. A runner that rebuilds both needs
    nothing else, and no second check, to tell whether `output2` is unchanged again: it is
    where each was rebuilt with the hash the record gives for its entry."""
    text = WORKED_EXAMPLE.replace("python src/output1.py", "python3 src/output1.py", 1)
    (worked / "astra.yaml").write_text(text)
    report = api.status(worked)
    for id_ in ("output1#u1", "output1#u2"):
        own = report.statuses[id_]
        assert (own.state, errors(own), own.stale_inputs) == ("stale", ["STALE_RESULT"], ())
    compared = report.statuses["output2"]
    assert (compared.state, compared.why) == ("stale", ())
    assert compared.stale_inputs == ("output1#u1", "output1#u2")
    assert recorded(compared) == {
        "output1#u1": digest_bytes(b"output1#u1\n"),
        "output1#u2": digest_bytes(b"output1#u2\n"),
    }


def test_a_result_stale_in_itself_and_through_what_it_reads_says_both(worked: Path) -> None:
    """`output2`'s own command changes, and so does the content of the input both results of
    `output1` read: `output2` breaks STALE_RESULT itself, and reads two results that aren't
    unchanged. The error in its `why` says that rebuilding those with the bytes it read
    wouldn't leave it unchanged."""
    text = WORKED_EXAMPLE.replace("python src/output2.py", "python3 src/output2.py", 1)
    (worked / "astra.yaml").write_text(text)
    (worked / "data" / "input1.csv").write_text("2\n")
    compared = api.status(worked).statuses["output2"]
    assert (compared.state, errors(compared)) == ("stale", ["STALE_RESULT"])
    assert compared.stale_inputs == ("output1#u1", "output1#u2")


LFS = f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a' * 64}\nsize 6\n"

STANDING_IN = MINIMAL.replace("    format: json\n", "    format: json\n    inputs: [input1]\n") + (
    "inputs:\n  input1: {path: data/input1.bin}\n"
)


def test_an_inputs_content_is_never_what_stands_in_for_it(tmp_path: Path) -> None:
    """STALE_RESULT compares the content of its inputs, never what stands in for it: a
    Git LFS pointer gives its content's hash and size, and the record of what the
    recipe read holds those, not the pointer's own. An input whose content changed is the
    result's own change, not a stale input: only an entry that reads a result is one."""
    top = repository(tmp_path, {"astra.yaml": STANDING_IN, "data/input1.bin": LFS})
    build(top)  # it hashes the pointer, as no runner would
    report = api.status(top)
    assert statuses(report) == {"result": ("stale", "present")}
    assert codes(report, "result") == ["STALE_RESULT"]
    assert messages(report, "result") == [
        "the content of `input1`, data/input1.bin, isn't what the recipe read"
    ]
    assert report.statuses["result"].stale_inputs == ()
    path = top / ".astra" / "records" / "result.json"
    content = {"entry": "input1", "content_hash": f"sha256:{'a' * 64}", "size": 6}
    rewrite(path, lambda value: value["generated_by"].update(inputs=[content]))
    assert statuses(api.status(top)) == {"result": ("unchanged", "present")}


# --- ABSENT_RESULT ---


def test_bytes_that_arent_the_recorded_ones_are_absent(worked: Path) -> None:
    """ABSENT_RESULT, a SHOULD: other bytes, a stand-in or nothing at the default place are
    `absent`, which leaves the record `unchanged` and the check passing. It is a warning in the
    result's `why`, so no error there, and the status still holds the record: its own bytes
    being absent is no change of what a result is made from."""
    (worked / "results" / "output2.csv").write_text("other\n")
    report = api.status(worked)
    assert statuses(report)["output2"] == ("unchanged", "absent")
    (broken,) = [broken for status in report.statuses.values() for broken in status.why]
    assert (broken.code, broken.level, broken.location.file) == (
        "ABSENT_RESULT",
        "warning",
        "results/output2.csv",
    )
    assert broken.message == "the bytes at results/output2.csv aren't the ones its record gives"
    found = report.statuses["output2"]
    assert (errors(found), found.stale_inputs) == ([], ())
    assert found.record is not None and found.record.address == "output2"
    assert astra("status", str(worked)).exit_code == 0
    (worked / "results" / "output2.csv").write_text(LFS)
    assert statuses(api.status(worked))["output2"] == ("unchanged", "absent")
    (worked / "results" / "output2.csv").unlink()
    report = api.status(worked)
    assert statuses(report)["output2"] == ("unchanged", "absent")
    assert messages(report, "output2") == [
        "no file is at results/output2.csv, the result's default place"
    ]


# --- STALE_EVIDENCE ---


def test_evidence_gets_the_status_of_the_results_it_cites(worked: Path) -> None:
    """STALE_EVIDENCE: an `artifact` pinned names one result; one naming an output built per
    universe without a pin cites its results in each of the root's universes, and gets the
    worst of their statuses, `missing` then `stale`."""
    text = WORKED_EXAMPLE.replace(
        "      - artifact: output2\n",
        "      - artifact: output2\n      - artifact: output1#u2\n      - artifact: output1\n",
    )
    (worked / "astra.yaml").write_text(text)
    report = api.status(worked)
    assert cited(report) == [
        ("findings.insight1", 0, ("output2",), "unchanged"),
        ("findings.insight1", 1, ("output1#u2",), "unchanged"),
        ("findings.insight1", 2, ("output1#u1", "output1#u2"), "unchanged"),
    ]
    assert all(evidence.why == () for evidence in report.evidence)
    (worked / "astra.yaml").write_text(text.replace("{decision1: a}", "{decision1: b}"))
    report = api.status(worked)
    assert [e.state for e in report.evidence] == ["stale", "unchanged", "stale"]
    (worked / ".astra" / "records" / "u2" / "output1.json").unlink()
    report = api.status(worked)
    assert [e.state for e in report.evidence] == ["stale", "missing", "missing"]
    evidence = report.evidence[2]
    assert [(d.code, d.level, d.location.pointer) for d in evidence.why] == [
        ("STALE_EVIDENCE", "error", "/findings/insight1/evidence/2/artifact")
    ]
    assert evidence.why[0].message == (
        "the evidence cites `output1#u1`, `output1#u2`: one of them is missing"
    )


UNBUILT = MINIMAL + (
    """\
analyses:
  lib: {path: lib}
findings:
  insight1:
    claim: lib's out is cited.
    evidence:
      - artifact: lib.out
"""
)
"""A root with no universes, whose evidence cites `lib`'s `out`, built per universe, without a
pin."""


def test_evidence_that_cites_no_result_is_missing_and_fails_the_check(tmp_path: Path) -> None:
    """An `artifact` naming an output built per universe without a pin cites its results in
    each of the root's universes where its analysis is built, here none, as the root has none,
    and if there are none, it is `missing`; `astra status` exits 1, though every planned result
    is unchanged."""
    top = repository(tmp_path, {"astra.yaml": UNBUILT, "lib/astra.yaml": LIB})
    build(top)
    report = api.status(top)
    assert statuses(report) == {"result": ("unchanged", "present")}
    assert cited(report) == [("findings.insight1", 0, (), "missing")]
    assert [d.code for d in report.evidence[0].why] == ["STALE_EVIDENCE"]
    assert "cites no result" in report.evidence[0].why[0].message
    assert astra("status", str(top)).exit_code == 1


CITING = (
    PAIR
    + """\
findings:
  insight1:
    claim: Both chains reach one result.
    evidence:
      - artifact: stage.inner.output1#u1
"""
)


@pytest.fixture
def pair(tmp_path: Path) -> Path:
    """`inner`, reached through `inner` and `stage.inner`, built, with evidence citing
    `stage.inner.output1#u1`."""
    files = {"astra.yaml": CITING, "stage/astra.yaml": STAGE, "stage/inner/astra.yaml": INNER}
    top = repository(tmp_path, files)
    build(top)
    return top


def test_a_result_with_two_names_has_the_worst_status_of_its_places(pair: Path) -> None:
    """A result with two names has a record at each of its places and one status, the worst of
    its places': what each place breaks, there; its bytes `present` only where they are at each
    default place; and its record, the first place's, only where every place holds one that is
    the result's. Whatever reads it reads a result that isn't unchanged, by whichever name."""
    whole = api.status(pair).statuses["inner.output1#u1"]
    assert (whole.state, whole.bytes, whole.why) == ("unchanged", "present", ())
    assert whole.record is not None and whole.record.address == "inner.output1#u1"
    (pair / "results" / "u1" / "stage.inner.output1.json").unlink()
    absent = api.status(pair).statuses["inner.output1#u1"]
    assert (absent.state, absent.bytes) == ("unchanged", "absent")
    assert [(d.code, d.location.file) for d in absent.why] == [
        ("ABSENT_RESULT", "results/u1/stage.inner.output1.json")
    ]
    assert absent.record == whole.record
    (pair / ".astra" / "records" / "u1" / "stage.inner.output1.json").unlink()
    report = api.status(pair)
    missing = report.statuses["inner.output1#u1"]
    assert (missing.state, missing.bytes, missing.record) == ("missing", "absent", None)
    assert [(d.code, d.location.file) for d in missing.why] == [
        ("MISSING_RECORD", ".astra/records/u1/stage.inner.output1.json")
    ]
    assert report.statuses["through_inner#u1"].stale_inputs == ("inner.output1",)
    assert report.statuses["through_stage#u1"].stale_inputs == ("stage.inner.output1",)
    assert report.statuses["stage.staged#u1"].stale_inputs == ("inner.output1",)
    # The same result in the other universe is another result, with its own places.
    assert statuses(report)["inner.output1#u2"] == ("unchanged", "present")


def test_a_place_that_is_stale_and_one_that_is_missing_make_the_result_missing(pair: Path) -> None:
    """The worst of its places', `missing` then `stale`, with what each breaks."""
    records = pair / ".astra" / "records" / "u1"
    rewrite(records / "inner.output1.json", lambda v: v["generated_by"].update(commit="0" * 40))
    report = api.status(pair)
    stale = report.statuses["inner.output1#u1"]
    assert (stale.state, codes(report, "inner.output1#u1")) == ("stale", ["STALE_RESULT"])
    assert stale.record is not None and stale.record.generated_by.commit == "0" * 40
    (records / "stage.inner.output1.json").unlink()
    report = api.status(pair)
    missing = report.statuses["inner.output1#u1"]
    assert (missing.state, missing.record) == ("missing", None)
    assert codes(report, "inner.output1#u1") == ["STALE_RESULT", "MISSING_RECORD"]


CITING_SUBANALYSIS = SUBANALYSIS + (
    """\
findings:
  own:
    claim: Its decision changes its output.
    evidence:
      - artifact: output1
      - artifact: unread
"""
)
"""`subanalysis`, whose evidence cites its `output1`, built per universe, and `unread`,
which nothing plans."""


def test_a_declared_analysiss_evidence_citing_a_planned_result_gets_a_status(
    tmp_path: Path,
) -> None:
    """A check covers the evidence of each declared analysis that cites a result
    the root plans, not only the root's. `subanalysis`'s `output1` cites its results in each of
    the root's universes, as the root's evidence does, and not in `subanalysis`'s own `u1` and
    `v1`, though `output5`'s pins plan them too. `unread`, which the root doesn't plan, gets no
    status. A missing one fails the check (`STALE_EVIDENCE`), located in the file that holds
    it."""
    files = {
        "astra.yaml": ROOT,
        "data/input1.csv": "1\n",
        "subanalysis/astra.yaml": CITING_SUBANALYSIS,
        "subanalysis/data/input1.csv": "2\n",
    }
    top = repository(tmp_path, files)
    build(top)
    cites = ("subanalysis.output1#u1", "subanalysis.output1#u2")
    report = api.status(top)
    assert cited(report) == [
        ("findings.insight1", 0, cites, "unchanged"),
        ("subanalysis.findings.own", 0, cites, "unchanged"),
    ]
    # `unread` cites nothing planned: the analysis says so, and a check doesn't cover it.
    (own,) = report.analysis.analyses[1].findings
    assert [evidence.cites for evidence in own.evidence] == [cites, ()]
    (top / "subanalysis" / ".astra" / "records" / "v1" / "output1.json").unlink()
    report = api.status(top)
    assert statuses(report)["subanalysis:output1#v1"] == ("missing", "absent")
    assert [e.state for e in report.evidence] == ["unchanged", "unchanged"]
    (top / ".astra" / "records" / "u2" / "subanalysis.output1.json").unlink()
    report = api.status(top)
    assert [e.state for e in report.evidence] == ["missing", "missing"]
    assert [(d.code, d.location.file, d.location.pointer) for d in report.evidence[1].why] == [
        ("STALE_EVIDENCE", "subanalysis/astra.yaml", "/findings/own/evidence/0/artifact")
    ]
    result = astra("status", str(top))
    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    at = lines.index("subanalysis.findings.own evidence 0  missing")
    assert lines[at + 1].endswith(
        "error STALE_EVIDENCE the evidence cites `subanalysis.output1#u1`, "
        "`subanalysis.output1#u2`: one of them is missing"
    )


def test_evidence_citing_a_result_by_either_name_gets_that_results_status(pair: Path) -> None:
    """Evidence citing `stage.inner.output1#u1` cites the one result `inner`'s `output1` has in
    `u1`, whichever of its names the `artifact` gives, and gets its status, the worst of its
    places'."""
    assert cited(api.status(pair)) == [("findings.insight1", 0, ("inner.output1#u1",), "unchanged")]
    (pair / ".astra" / "records" / "u1" / "inner.output1.json").unlink()
    (evidence,) = api.status(pair).evidence
    assert evidence.state == "missing"
    assert [d.code for d in evidence.why] == ["STALE_EVIDENCE"]


# --- Results from a commit ---


FROM_COMMIT = """\
spec_version: "0.1.0"
analyses:
  lib: {path: lib, commit: "%s"}
outputs:
  result:
    type: table
    format: csv
    inputs: [lib.out#v1]
    recipe:
      command: python make.py {inputs} '{output}'
findings:
  insight1:
    claim: lib's once is cited, and read by nothing.
    evidence:
      - artifact: lib.once
"""
"""A root that reads `lib`'s `out` in `lib`'s own `v1`, and cites `lib`'s `once`, `lib` read at
a commit that holds its records."""


def test_results_of_an_analysis_from_a_commit_are_read_through_their_records(
    tmp_path: Path,
) -> None:
    """`lib` is built at `A` and its records committed in `B`, which the root declares.
    Its results are read through their records at `B`, unchanged where nothing changed between
    `A` and `B`; only `out`, which a planned result reads, gets a bytes status, from what `B`
    holds."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL, "lib/astra.yaml": LIB})
    build(top, top / "lib")
    holding = git(repository(top, {}), "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": FROM_COMMIT % holding})
    report = api.status(top)
    assert statuses(report) == {
        "lib:out#v1": ("unchanged", "present"),
        "result": ("missing", "absent"),
        "lib:once": ("unchanged", None),
    }
    results = {result.id: result for result in report.analysis.results}
    assert owner(report.analysis, results["lib:out#v1"]).commit == api.Commit(holding)
    assert cited(report) == [("findings.insight1", 0, ("lib:once",), "unchanged")]
    build(top)
    assert {s[0] for s in statuses(api.status(top)).values()} == {"unchanged"}


CHAINED = LIB.replace(
    "universes:",
    "  twice:\n    type: metric\n    format: json\n    inputs: [once]\n"
    "    recipe:\n      command: python make.py {inputs} '{output}'\nuniverses:",
)
"""`lib`, whose `twice` reads its `once`."""


def test_a_result_of_an_analysis_from_a_commit_that_a_planned_result_reads_has_its_bytes(
    tmp_path: Path,
) -> None:
    """ABSENT_RESULT: only a result of an analysis from a commit that no
    planned result reads is left out. `once` is read by `twice`, itself read through its
    record, so it gets a bytes status from what `B` holds, which hasn't its bytes: `absent`,
    and ABSENT_RESULT, at its default place in that commit."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL, "lib/astra.yaml": CHAINED})
    build(top, top / "lib")
    (top / "lib" / "results" / "once.json").unlink()
    holding = git(repository(top, {}), "rev-parse", "HEAD").strip()
    root = FROM_COMMIT.split("findings:")[0].replace("lib.out#v1", "lib.twice")
    report = api.status(repository(top, {"astra.yaml": root % holding}))
    assert statuses(report) == {
        "lib:twice": ("unchanged", "present"),
        "lib:once": ("unchanged", "absent"),
        "result": ("missing", "absent"),
    }
    (broken,) = report.statuses["lib:once"].why
    assert (broken.code, broken.location.file, broken.location.commit) == (
        "ABSENT_RESULT",
        "lib/results/once.json",
        holding,
    )


def test_a_result_of_an_analysis_from_a_commit_is_stale_where_its_commit_changed_it(
    tmp_path: Path,
) -> None:
    """Unchanged only where nothing STALE_RESULT compares changed between the commit its
    record names, `A`, and the declared one, `B`; and a result made from it is stale too,
    through the entry that reads it."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL, "lib/astra.yaml": LIB})
    build(top, top / "lib")
    edited = LIB.replace("python make.py '{decisions.d}'", "python3 make.py '{decisions.d}'")
    holding = git(repository(top, {"lib/astra.yaml": edited}), "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": FROM_COMMIT % holding})
    build(top)
    report = api.status(top)
    assert statuses(report)["lib:out#v1"] == ("stale", "present")
    assert errors(report.statuses["lib:out#v1"]) == ["STALE_RESULT"]
    assert statuses(report)["lib:once"] == ("unchanged", None)
    found = report.statuses["result"]
    assert (found.state, found.why, found.stale_inputs) == ("stale", (), ("lib.out#v1",))


def test_results_of_an_analysis_from_another_repository_are_read_from_its_remote(
    tmp_path: Path,
) -> None:
    """In the repository that holds that analysis at the commit it is read at, got from its
    `url`, the record's own commit too."""
    remote = repository(tmp_path / "remote", {"astra.yaml": LIB})
    build(remote)
    holding = git(repository(remote, {}), "rev-parse", "HEAD").strip()
    url = remote.as_uri()
    text = FROM_COMMIT.replace('{path: lib, commit: "%s"}', f"{{url: '{url}', commit: '%s'}}")
    top = repository(tmp_path / "top", {"astra.yaml": text % holding})
    report = api.status(top)
    assert statuses(report) == {
        "lib:out#v1": ("unchanged", "present"),
        "result": ("missing", "absent"),
        "lib:once": ("unchanged", None),
    }
    assert report.statuses["lib:out#v1"].why == ()
    results = {result.id: result for result in report.analysis.results}
    assert owner(report.analysis, results["lib:out#v1"]).commit == api.Commit(holding, url)
    assert report.evidence[0].state == "unchanged"


def test_what_a_driver_builds_of_an_analysis_from_a_commit_is_checked_as_its_own(
    tmp_path: Path,
) -> None:
    """What the root's universes build of `lib` belongs to the root, and
    its record names the root's commit, at which the root's file declares `lib` at its commit;
    a universe that selects another option for `lib`'s decision makes it stale, and what reads
    it."""
    top = repository(tmp_path, {"astra.yaml": MINIMAL, "lib/astra.yaml": LIB})
    build(top, top / "lib")
    holding = git(repository(top, {}), "rev-parse", "HEAD").strip()
    repository(top, {"astra.yaml": DRIVING % holding})
    build(top)
    assert {s[0] for s in statuses(api.status(top)).values()} == {"unchanged"}
    (top / "astra.yaml").write_text((DRIVING % holding).replace("lib.d: a", "lib.d: b"))
    report = api.status(top)
    assert statuses(report)["lib.out#u1"][0] == "stale"
    assert errors(report.statuses["lib.out#u1"]) == ["STALE_RESULT"]
    assert statuses(report)["lib:out#v1"][0] == "unchanged"
    found = report.statuses["result#u1"]
    assert (found.state, errors(found), found.stale_inputs) == ("stale", [], ("lib.out",))


# --- --at ---


def test_at_a_commit_the_stack_records_and_bytes_are_read_there(worked: Path) -> None:
    """`at=<commit>` checks the stack as it is at that commit, with its records and
    bytes read there: not yet committed, they aren't there."""
    report = api.status(worked, at="HEAD")
    assert {s[0] for s in statuses(report).values()} == {"missing"}
    git(worked, "add", "--all")
    git(worked, "commit", "--quiet", "--message", "records")
    head = git(worked, "rev-parse", "HEAD~1").strip()[:12]
    text = WORKED_EXAMPLE.replace("decisions: {decision1: a}", "decisions: {decision1: b}")
    (worked / "astra.yaml").write_text(text)
    report = api.status(worked, at="HEAD")
    assert statuses(report) == UNCHANGED
    # The analysis is the one that commit holds, whose `u1` still selects `a`.
    assert report.analysis.analyses[0].universes[0].selection == {"decisions.decision1": "a"}
    report = api.status(worked)
    assert statuses(report)["output1#u1"][0] == "stale"
    assert messages(report, "output1#u1") == [
        f"`decision1` selects `b` in `u1`, where it selected `a` at {head}"
    ]
    with pytest.raises(api.RequestError):
        api.status(worked, at="nowhere")


# --- An analysis that breaks a MUST has no statuses ---


UNDETERMINED = """\
  broken:
    type: table
    format: csv
    inputs: [nothing]
    recipe:
      command: python src/broken.py '{inputs}' '{output}'
  reader:
    type: table
    format: csv
    inputs: [broken]
    recipe:
      command: python src/reader.py '{inputs}' '{output}'
"""
"""Two outputs for the worked example: `broken` reads an address that names nothing, and
`reader` reads `broken`."""

INVALID_WORKED = WORKED_EXAMPLE.replace("\nuniverses:", UNDETERMINED + "\nuniverses:").replace(
    "      - artifact: output2\n", "      - artifact: output2\n      - artifact: reader\n"
)
"""The worked example, broken by `UNDETERMINED`, with evidence citing `reader` too."""

CYCLE = MINIMAL + "".join(
    f"  {id_}:\n    type: metric\n    format: json\n    inputs: [{reads}]\n"
    "    recipe:\n      command: python make.py '{inputs}' '{output}'\n"
    for id_, reads in (("first", "second"), ("second", "first"))
)
"""Two outputs that read each other, beside `result`."""


@pytest.mark.parametrize(
    ("text", "broken"),
    [
        pytest.param(INVALID_WORKED, ["UNRESOLVED_ADDRESS"], id="an address that names nothing"),
        pytest.param(CYCLE, ["OUTPUT_CYCLE", "OUTPUT_CYCLE"], id="two outputs on a cycle"),
        pytest.param(
            MINIMAL.replace("type: metric", "type: plot"),
            ["INVALID_VALUE"],
            id="a file that isn't a valid document",
        ),
    ],
)
def test_an_analysis_that_breaks_a_must_isnt_checked(
    worked: Path, text: str, broken: list[str]
) -> None:
    """An analysis that breaks a `MUST` resolves to nothing, so it has no planned results to
    give statuses to, not even those the error leaves alone: `check` raises, with the
    validator's report, which says where."""
    (worked / "astra.yaml").write_text(text)
    with pytest.raises(api.InvalidAnalysisError) as raised:
        api.status(worked)
    report = raised.value.report
    assert not report.valid
    assert [d.code for d in report.diagnostics if d.level == "error"] == broken


# --- The report as JSON ---


def test_the_report_as_json_holds_the_analysis_and_each_status_by_result_id(worked: Path) -> None:
    """The analysis as it resolved, each result's status by its id, in the results' order, with
    what it breaks and what its record says, which names the environment and the runner that
    says what it holds; then the evidence. A field with no value is left out, never null."""
    (worked / "results" / "output2.csv").unlink()
    report = api.status(worked)
    shape = report.to_json()
    assert json.loads(json.dumps(shape)) == shape
    assert list(shape) == ["analysis", "statuses", "evidence"]
    assert shape["analysis"] == report.analysis.to_json()
    assert list(shape["statuses"]) == ["output1#u1", "output1#u2", "output2"]
    record = json.loads((worked / ".astra" / "records" / "output2.json").read_text("utf-8"))
    assert record["generated_by"]["environment"] == {"iri": ENVIRONMENT.iri}
    assert shape["statuses"]["output2"] == {
        "state": "unchanged",
        "bytes": "absent",
        "record": record,
        "why": [
            {
                "code": "ABSENT_RESULT",
                "level": "warning",
                "message": "no file is at results/output2.csv, the result's default place",
                "location": {"file": "results/output2.csv", "pointer": ""},
                "related": [],
            }
        ],
        "stale_inputs": [],
    }
    assert shape["evidence"] == [
        {"insight": "findings.insight1", "index": 0, "state": "unchanged", "why": []}
    ]
    assert "null" not in json.dumps(shape)


def test_the_json_says_what_a_result_breaks_and_which_entries_read_what_isnt_unchanged(
    worked: Path,
) -> None:
    """A stale result's `why` holds what it breaks itself, at its record, and `stale_inputs`
    the entries that read a result that isn't unchanged. A status gives what its result's
    record says as `record`, left out where there is none that is the result's."""
    (worked / "data" / "input1.csv").write_text("2\n")
    shape = api.status(worked).to_json()["statuses"]
    one = shape["output1#u1"]
    assert (one["state"], one["stale_inputs"]) == ("stale", [])
    assert [(d["code"], d["level"], d["location"]["file"]) for d in one["why"]] == [
        ("STALE_RESULT", "error", ".astra/records/u1/output1.json")
    ]
    assert one["record"]["address"] == "output1#u1"
    compared = shape["output2"]
    assert (compared["state"], compared["why"]) == ("stale", [])
    assert compared["stale_inputs"] == ["output1#u1", "output1#u2"]
    assert [item["entry"] for item in compared["record"]["generated_by"]["inputs"]] == [
        "output1#u1",
        "output1#u2",
    ]
    (worked / ".astra" / "records" / "output2.json").unlink()
    shape = api.status(worked).to_json()
    assert shape["statuses"]["output2"]["state"] == "missing"
    assert "record" not in shape["statuses"]["output2"]
    (evidence,) = shape["evidence"]
    assert (evidence["state"], [d["code"] for d in evidence["why"]]) == (
        "missing",
        ["STALE_EVIDENCE"],
    )
    assert evidence["why"][0]["location"]["pointer"] == "/findings/insight1/evidence/0/artifact"


# --- astra status ---


def test_astra_check_exits_0_when_every_result_is_unchanged(worked: Path) -> None:
    result = astra("status", str(worked))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "output1#u1  unchanged  present  .astra/records/u1/output1.json"
    # Under each result with a record, the environment it names and the runner that recorded
    # it, which is the one to say what that environment holds.
    assert lines[1] == f"  made in {ENVIRONMENT.iri} by {RUNNER.id} {RUNNER.version}"
    assert lines[6] == "findings.insight1 evidence 0  unchanged"
    assert lines[-1] == "3 planned result(s), 3 unchanged, 0 stale, 0 missing; 0 absent"


def test_astra_check_exits_1_when_one_isnt(worked: Path) -> None:
    """Under a result, what it breaks itself, then each entry that reads a result that isn't
    what it was made from."""
    (worked / "data" / "input1.csv").write_text("2\n")
    result = astra("status", str(worked))
    assert result.exit_code == 1
    assert "  error STALE_RESULT the content of `input1`" in result.stdout
    lines = result.stdout.splitlines()
    at = lines.index("output2  stale  present  .astra/records/output2.json")
    assert lines[at + 1 : at + 3] == [
        "  `output1#u1` reads `output1#u1`, which isn't what it was made from",
        "  `output1#u2` reads `output1#u2`, which isn't what it was made from",
    ]
    assert lines[-1] == "3 planned result(s), 0 unchanged, 3 stale, 0 missing; 0 absent"
    shape = json.loads(astra("status", str(worked), "--json").stdout)
    assert [status["state"] for status in shape["statuses"].values()] == ["stale"] * 3
    assert shape == api.status(worked).to_json()


def test_astra_check_names_the_environment_only_of_a_record_that_is_the_results(
    worked: Path,
) -> None:
    """A result with no record, or one that breaks a rule, has no environment to name."""
    (worked / ".astra" / "records" / "output2.json").unlink()
    (worked / ".astra" / "records" / "u2" / "output1.json").write_text("{")
    result = astra("status", str(worked))
    assert result.exit_code == 1
    assert result.stdout.count("  made in ") == 1
    lines = result.stdout.splitlines()
    at = lines.index(f"  made in {ENVIRONMENT.iri} by {RUNNER.id} {RUNNER.version}")
    assert lines[at - 1].startswith("output1#u1  unchanged")
    broken = lines[lines.index("output1#u2  missing  absent  .astra/records/u2/output1.json") + 1]
    assert broken.startswith("  1:2 error INVALID_RECORD ") and broken.endswith(" (INVALID_SYNTAX)")
    assert lines[-1] == "3 planned result(s), 1 unchanged, 0 stale, 2 missing; 2 absent"


def test_astra_check_of_an_invalid_analysis_shows_why_and_exits_1(worked: Path) -> None:
    """The errors, as `astra validate` shows them, and no status; with `--json`, the
    validator's report."""
    (worked / "astra.yaml").write_text(INVALID_WORKED)
    result = astra("status", str(worked))
    assert result.exit_code == 1
    assert "UNRESOLVED_ADDRESS" in result.stdout
    assert "planned result(s)" not in result.stdout
    assert result.stdout == astra("validate", str(worked)).stdout
    report = json.loads(astra("status", str(worked), "--json").stdout)
    assert report == api.validate(worked).to_json()
    assert report["valid"] is False
    assert [d["code"] for d in report["diagnostics"]] == ["UNRESOLVED_ADDRESS"]


def test_astra_check_exits_2_where_it_cant_check(tmp_path: Path, worked: Path) -> None:
    result = astra("status", str(tmp_path / "nothere"))
    assert result.exit_code == 2
    result = astra("status", str(worked), "--at", "nowhere")
    assert result.exit_code == 2
    assert "--at" in result.stderr


# --- Every check code has a case ---


def _pop_an_input(top: Path) -> None:
    rewrite(
        top / ".astra/records/output2.json", lambda value: value["generated_by"]["inputs"].pop()
    )


BREAKING: Mapping[str, Callable[[Path], object]] = {
    "MISSING_RECORD": lambda top: (top / ".astra/records/output2.json").unlink(),
    "INVALID_RECORD": lambda top: (top / ".astra/records/output2.json").write_text("{"),
    "MISPLACED_RECORD": lambda top: shutil.copy(
        top / ".astra/records/u1/output1.json", top / ".astra/records/u2/output1.json"
    ),
    "MISSING_RECORD_INPUTS": _pop_an_input,
    "STALE_RESULT": lambda top: (top / "data/input1.csv").write_text("2\n"),
    "ABSENT_RESULT": lambda top: (top / "results/output2.csv").unlink(),
    "STALE_EVIDENCE": lambda top: (top / "astra.yaml").write_text(
        WORKED_EXAMPLE.replace("{decision1: a}", "{decision1: b}")
    ),
}
"""For each check code, an edit of the built worked example that breaks it. The worked example
as built keeps every one (`test_a_built_analysis_is_unchanged_and_present`)."""


def test_every_check_code_has_a_case() -> None:
    """The codes the checker declares are the check layer's, and each has a case."""
    assert CODES == set(BREAKING) == set(Catalogue.load().codes("check"))


@pytest.mark.parametrize("code", sorted(BREAKING))
def test_the_checker_reports_each_code(worked: Path, code: str) -> None:
    """Each at the level its rule gives: a `MUST` an error, a `SHOULD` a warning."""
    edit = BREAKING[code]
    edit(worked)
    report = api.status(worked)
    found = [broken for status in report.statuses.values() for broken in status.why]
    found += [broken for evidence in report.evidence for broken in evidence.why]
    assert code in {broken.code for broken in found}, found
    catalogue = Catalogue.load()
    assert all(broken.level == catalogue.level(broken.code) for broken in found)


# --- Edits of the worked example, the records committed ---


@pytest.fixture(scope="module")
def committed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The worked example with the scripts its recipes run, built from its commit, its records
    and bytes then committed in a later commit."""
    files = {
        "astra.yaml": WORKED_EXAMPLE,
        "data/input1.csv": "1\n",
        "src/output1.py": "print('output1')\n",
        "src/output2.py": "print('output2')\n",
    }
    top = repository(tmp_path_factory.mktemp("committed"), files)
    build(top)
    return repository(top, {})


def _select(universe: str, option: str) -> Callable[[Path], object]:
    """The edit by which `universe` selects `option` for `decision1`."""
    old = "{decision1: a}" if universe == "u1" else "{decision1: b}"
    text = WORKED_EXAMPLE.replace(
        f"{universe}:\n    decisions: {old}", f"{universe}:\n    decisions: {{decision1: {option}}}"
    )
    assert text != WORKED_EXAMPLE
    return lambda top: (top / "astra.yaml").write_text(text)


Edit = tuple[Callable[[Path], object], tuple[str, str, str], Mapping[str, str], tuple[str, ...]]

EDITS: Mapping[str, Edit] = {
    "`u1` selects another option for `decision1`": (
        _select("u1", "b"),
        ("stale", "unchanged", "stale"),
        {"output1#u1": "`decision1` selects `b` in `u1`, where it selected `a` at {commit}"},
        ("output1#u1",),
    ),
    "`insight1`'s claim is reworded": (
        lambda top: (top / "astra.yaml").write_text(
            WORKED_EXAMPLE.replace("give different results.", "don't give the same results.")
        ),
        ("unchanged", "unchanged", "unchanged"),
        {},
        (),
    ),
    "the script that `output1`'s recipe runs is edited": (
        lambda top: (top / "src/output1.py").write_text("print('edited')\n"),
        ("unchanged", "unchanged", "unchanged"),
        {},
        (),
    ),
    "`data/input1.csv` is changed": (
        lambda top: (top / "data/input1.csv").write_text("2\n"),
        ("stale", "stale", "stale"),
        {
            "output1#u1": "the content of `input1`, data/input1.csv, isn't what the recipe read",
            "output1#u2": "the content of `input1`, data/input1.csv, isn't what the recipe read",
        },
        ("output1#u1", "output1#u2"),
    ),
    "`u2` selects `a`": (
        _select("u2", "a"),
        ("unchanged", "stale", "stale"),
        {"output1#u2": "`decision1` selects `a` in `u2`, where it selected `b` at {commit}"},
        ("output1#u2",),
    ),
}
"""Each edit, the statuses it leaves `output1` in `u1`, `output1` in `u2` and `output2` with,
what the checker says each result that breaks STALE_RESULT itself changed, `{commit}` being the
commit the records name, and the entries through which `output2`, which breaks nothing itself,
reads a result that isn't unchanged."""


@pytest.mark.parametrize("edit", EDITS)
def test_each_edit_gives_its_effect(committed: Path, tmp_path: Path, edit: str) -> None:
    top = Path(shutil.copytree(committed, tmp_path / "top", symlinks=True))
    assert statuses(api.status(top)) == UNCHANGED
    change, effect, said, through = EDITS[edit]
    change(top)
    report = api.status(top)
    assert tuple(s[0] for s in statuses(report).values()) == effect
    commit = git(top, "rev-parse", "HEAD~1").strip()[:12]
    assert {id_: messages(report, id_) for id_ in report.statuses} == {
        id_: [said[id_].format(commit=commit)] if id_ in said else [] for id_ in report.statuses
    }
    assert report.statuses["output1#u1"].stale_inputs == ()
    assert report.statuses["output1#u2"].stale_inputs == ()
    assert report.statuses["output2"].stale_inputs == through
