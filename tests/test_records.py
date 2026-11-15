"""Records, read as UTF-8 JSON text and checked by the record schema their minor version picks;
and `records`: reading one at a place, and writing the record of a run at each place of the
result it made."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from astra import api
from astra._internal.documents.catalogue import Catalogue
from astra._internal.documents.contract import Contract
from astra._internal.documents.load import ParseError, load_json
from astra._internal.results.hashing import digest_bytes
from astra._internal.results.records import read_record
from astra._internal.sources.reader import WorktreeReader
from astra.model import to_json
from tests.conftest import ENVIRONMENT, RUNNER
from tests.spec import DOCUMENTS

VALID = sorted((DOCUMENTS / "valid").glob("ProvenanceRecord-*.json"))

RECORD = json.loads((DOCUMENTS / "valid" / "ProvenanceRecord-001-full.json").read_text("utf-8"))
"""A valid record of 0.1, astra-spec's fixture."""

PLACE = ".astra/records/u1/subanalysis1.output1.json"

RESULT = api.Result(
    "subanalysis1.output1#u1",
    "subanalysis1.outputs.output1",
    (api.Place("subanalysis1.output1#u1", PLACE, "results/u1/subanalysis1.output1.json"),),
    "universes.u1",
    (api.Source("root.data", input="inputs.data"),),
)
"""The planned result `RECORD` is the record of: one place, and one entry, which reads an
input."""

RUN = api.Generation(
    RECORD["generated_by"]["commit"],
    api.Environment(RECORD["generated_by"]["environment"]["iri"]),
    api.Runner("example-runner", "1.2.0"),
    (api.RecordedInput("root.data", RECORD["generated_by"]["inputs"][0]["content_hash"], 10),),
    "2026-10-26T14:00:00.000Z",
    "2026-10-26T14:00:02.000Z",
)
"""The run `RECORD` gives."""

TWICE = replace(
    RESULT,
    places=(
        *RESULT.places,
        api.Place(
            "stage.subanalysis1.output1#u1",
            ".astra/records/u1/stage.subanalysis1.output1.json",
            "results/u1/stage.subanalysis1.output1.json",
        ),
    ),
)
"""`RESULT`, under two names: a place for each."""


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract.load(Catalogue.load())


def check(contract: Contract, record: Any) -> list[tuple[str, str, str | None]]:
    document = load_json(json.dumps(record).encode())
    found = contract.check_record(document, "record.json")
    return [(d.code, d.location.pointer, d.location.key) for d in found]


def test_a_record_of_0_1_is_read_by_the_closed_schema(contract: Contract) -> None:
    assert check(contract, RECORD) == []
    assert check(contract, {**RECORD, "extra": 1}) == [("UNKNOWN_FIELD", "", "extra")]
    assert check(contract, {**RECORD, "spec_version": "0.1.9"}) == []


def test_a_record_of_a_later_minor_is_read_by_the_open_schema(contract: Contract) -> None:
    """It ignores the fields that version adds, and is checked for the rest."""
    later = {**RECORD, "spec_version": "0.2.0", "extra": 1}
    assert check(contract, later) == []
    del later["size"]
    assert check(contract, later) == [("MISSING_FIELD", "", None)]


def test_a_record_below_0_1_has_no_schema(contract: Contract) -> None:
    """Records begin at 0.1.0: INVALID_RECORD, at its version."""
    old = {**RECORD, "spec_version": "0.0.9", "extra": 1}
    assert check(contract, old) == [("INVALID_RECORD", "/spec_version", None)]


def test_a_malformed_version_is_read_by_the_0_1_schema(contract: Contract) -> None:
    assert check(contract, {**RECORD, "spec_version": "0.1"}) == [
        ("INVALID_VALUE", "/spec_version", None)
    ]


@pytest.mark.parametrize(
    "text",
    ['{"size": 1, "size": 2}', '{"size": 1, "\\u0073ize": 2}', '{"size": NaN}', "size: 1"],
)
def test_a_record_that_isnt_json_breaks_invalid_syntax(text: str) -> None:
    """RFC 8259 JSON text, in which no object has two equal names; and no `NaN`, which
    `json.loads` would take."""
    with pytest.raises(ParseError) as raised:
        load_json(text.encode())
    assert raised.value.code == "INVALID_SYNTAX"


def test_a_repeated_name_is_named() -> None:
    """A repeated name is INVALID_SYNTAX, whose message names it."""
    with pytest.raises(ParseError, match='the name "size" is twice'):
        load_json(b'{"size": 1, "size": 2}')


def test_a_record_is_utf_8() -> None:
    """A record is JSON text in UTF-8."""
    with pytest.raises(ParseError) as raised:
        load_json(b'{"x": "\xe9"}')
    assert raised.value.code == "INVALID_SYNTAX"


def test_a_record_that_is_json_is_read() -> None:
    assert load_json('{"x": [1, 2.5, "é", null, true]}'.encode()).value == {
        "x": [1, 2.5, "é", None, True]
    }


# --- reading records ---


def test_reading_a_record_gives_it_or_each_rule_it_breaks(
    tmp_path: Path, contract: Contract
) -> None:
    """A record that breaks a parse or schema rule gives its diagnostic, at its place in the
    record; nothing at the path, or a symlink there, is no record."""
    (tmp_path / "record.json").write_text(json.dumps(RECORD))
    (tmp_path / "broken.json").write_text(json.dumps({**RECORD, "size": -1}))
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "link.json").symlink_to("broken.json")
    reader = WorktreeReader(tmp_path, None)
    assert read_record(reader, "record.json", contract) == api.ProvenanceRecord(
        RESULT.id, RECORD["content_hash"], RECORD["size"], RUN
    )
    found = read_record(reader, "broken.json", contract)
    assert isinstance(found, tuple)
    assert [(d.code, d.location.file, d.location.pointer) for d in found] == [
        ("INVALID_VALUE", "broken.json", "/size")
    ]
    found = read_record(reader, "bad.json", contract)
    assert isinstance(found, tuple)
    assert [(d.code, d.location.file, d.location.line) for d in found] == [
        ("INVALID_SYNTAX", "bad.json", 1)
    ]
    assert read_record(reader, "link.json", contract) is None
    assert read_record(reader, "nothere.json", contract) is None


@pytest.mark.parametrize("fixture", VALID, ids=lambda path: path.stem)
def test_every_valid_record_fixture_is_read_as_a_record(
    tmp_path: Path, contract: Contract, fixture: Path
) -> None:
    """A document astra-spec gives as a valid record breaks no parse or schema rule, so it is
    read as a record, and says again what its file says: `inputs` and the times left out of
    the file are a record with none."""
    (tmp_path / "record.json").write_bytes(fixture.read_bytes())
    found = read_record(WorktreeReader(tmp_path, None), "record.json", contract)
    assert isinstance(found, api.ProvenanceRecord), found
    written = json.loads(fixture.read_text("utf-8"))
    written["generated_by"].setdefault("inputs", [])
    assert to_json(found) == written


def test_a_later_minor_versions_fields_are_left_out_of_the_record(
    tmp_path: Path, contract: Contract
) -> None:
    later = {**RECORD, "spec_version": "0.2.0", "extra": 1}
    (tmp_path / "later.json").write_text(json.dumps(later))
    found = read_record(WorktreeReader(tmp_path, None), "later.json", contract)
    assert isinstance(found, api.ProvenanceRecord)
    assert to_json(found) == {**RECORD, "spec_version": "0.2.0"}


# --- writing the record of a run ---


def test_a_record_is_written_with_sorted_keys_two_spaces_and_a_final_line_break(
    tmp_path: Path, contract: Contract
) -> None:
    """The record of a run, at its result's place from the analysis's folder, its folders made:
    exactly astra-spec's fixture, with sorted keys, two-space indentation and a final line
    break. It reads back as the run that was given."""
    api.write_records(tmp_path, RESULT, RECORD["content_hash"], RECORD["size"], RUN)
    path = tmp_path / PLACE
    text = path.read_text("utf-8")
    assert text == json.dumps(RECORD, indent=2, sort_keys=True) + "\n"
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temporary file left
    assert path.stat().st_mode & 0o777 == 0o644
    found = read_record(WorktreeReader(tmp_path, None), PLACE, contract)
    assert found == api.ProvenanceRecord(RESULT.id, RECORD["content_hash"], RECORD["size"], RUN)
    assert isinstance(found, api.ProvenanceRecord) and found.spec_version == "0.1.0"


def test_a_record_of_a_run_holds_what_the_runner_gives_it(
    tmp_path: Path, contract: Contract
) -> None:
    """A runner gives what its run made and read: the hash and size of the bytes made, and of
    what each entry read, the commit, environment, runner and times. `started` and `finished`
    are left out of the record where the run gives none, and `inputs` is empty for an output
    that lists none."""
    commit = "a" * 40
    made = digest_bytes(b"{}\n")
    once = api.Result(
        "output1", "outputs.output1", (api.Place("output1", "records/output1.json", "o.json"),)
    )
    api.write_records(
        tmp_path, once, made.content_hash, made.size, api.Generation(commit, ENVIRONMENT, RUNNER)
    )
    assert json.loads((tmp_path / "records" / "output1.json").read_text("utf-8")) == {
        "spec_version": "0.1.0",
        "address": "output1",
        "content_hash": made.content_hash,
        "size": 3,
        "generated_by": {
            "commit": commit,
            "environment": {"iri": ENVIRONMENT.iri},
            "runner": {"id": RUNNER.id, "version": RUNNER.version},
            "inputs": [],
        },
    }
    read = (api.RecordedInput("root.data", made.content_hash, 3),)
    started, finished = "2026-10-26T14:00:00.123Z", "2026-10-26T14:00:02.123Z"
    run = api.Generation(commit, ENVIRONMENT, RUNNER, read, started, finished)
    api.write_records(tmp_path, RESULT, made.content_hash, made.size, run)
    assert json.loads((tmp_path / PLACE).read_text("utf-8"))["generated_by"] == {
        "commit": commit,
        "environment": {"iri": ENVIRONMENT.iri},
        "runner": {"id": RUNNER.id, "version": RUNNER.version},
        "inputs": [{"entry": "root.data", "content_hash": made.content_hash, "size": 3}],
        "started": "2026-10-26T14:00:00.123Z",
        "finished": "2026-10-26T14:00:02.123Z",
    }
    found = read_record(WorktreeReader(tmp_path, None), PLACE, contract)
    assert found == api.ProvenanceRecord(RESULT.id, made.content_hash, made.size, run)


def test_a_time_is_kept_as_the_record_writes_it(tmp_path: Path, contract: Contract) -> None:
    """A record's times are text, in UTC to the millisecond: one is read as written, even the
    30th of February, which the schema's pattern lets through and no calendar has; and one in
    another form isn't written."""
    run = replace(RUN, started="2026-02-30T14:00:00.000Z")
    api.write_records(tmp_path, RESULT, RECORD["content_hash"], RECORD["size"], run)
    found = read_record(WorktreeReader(tmp_path, None), PLACE, contract)
    assert isinstance(found, api.ProvenanceRecord)
    assert found.generated_by.started == "2026-02-30T14:00:00.000Z"
    for moment in ("2026-10-26T14:00:00Z", "2026-10-26T16:00:00.000+02:00"):
        with pytest.raises(ValueError, match="started"):
            api.write_records(
                tmp_path / "other",
                RESULT,
                RECORD["content_hash"],
                RECORD["size"],
                replace(RUN, started=moment),
            )
    assert not (tmp_path / "other").exists()


def test_a_result_with_two_places_gets_a_record_at_each(tmp_path: Path, contract: Contract) -> None:
    """`UNRECORDED_RESULT`: one run, recorded at each place of the result it made, each record
    with its own place's address and nothing else of its own."""
    api.write_records(tmp_path, TWICE, RECORD["content_hash"], RECORD["size"], RUN)
    reader = WorktreeReader(tmp_path, None)
    for place in TWICE.places:
        assert read_record(reader, place.record_path, contract) == api.ProvenanceRecord(
            place.address, RECORD["content_hash"], RECORD["size"], RUN
        )
    first, second = (
        json.loads((tmp_path / place.record_path).read_text("utf-8")) for place in TWICE.places
    )
    assert second == {**first, "address": "stage.subanalysis1.output1#u1"}
    assert sorted(p.name for p in (tmp_path / ".astra" / "records" / "u1").iterdir()) == [
        "stage.subanalysis1.output1.json",
        "subanalysis1.output1.json",
    ]


@pytest.mark.parametrize(
    "inputs",
    [
        pytest.param((), id="no item for an entry"),
        pytest.param((*RUN.inputs, RUN.inputs[0]), id="two items for an entry"),
        pytest.param(
            (*RUN.inputs, replace(RUN.inputs[0], entry="other")),
            id="an item for an entry it doesn't list",
        ),
        pytest.param((replace(RUN.inputs[0], entry="data"),), id="an entry that isn't as written"),
    ],
)
def test_a_run_that_didnt_read_exactly_what_its_result_lists_isnt_recorded(
    tmp_path: Path, inputs: tuple[api.RecordedInput, ...]
) -> None:
    """`MISSING_RECORD_INPUTS`: a record gives one item of `inputs` for each entry its result's
    output lists, by the entry as written, and no other. One that wouldn't is refused, and
    nothing is written, at either place."""
    with pytest.raises(ValueError, match="one item of `inputs` for each"):
        api.write_records(
            tmp_path, TWICE, RECORD["content_hash"], RECORD["size"], replace(RUN, inputs=inputs)
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("field", "content_hash", "size", "run"),
    [
        pytest.param("content_hash", "7af13c", 732, RUN, id="a hash without its algorithm"),
        pytest.param(
            "content_hash", RECORD["content_hash"].upper(), 732, RUN, id="a hash in upper case"
        ),
        pytest.param("size", RECORD["content_hash"], -1, RUN, id="a negative size"),
        pytest.param(
            "commit",
            RECORD["content_hash"],
            732,
            replace(RUN, commit="a7d9ea9"),
            id="a short commit",
        ),
        pytest.param(
            "iri",
            RECORD["content_hash"],
            732,
            replace(RUN, environment=api.Environment("no scheme")),
            id="an environment that is no IRI",
        ),
        pytest.param(
            "content_hash",
            RECORD["content_hash"],
            732,
            replace(RUN, inputs=(replace(RUN.inputs[0], content_hash="sha256:0"),)),
            id="an input's hash too short",
        ),
    ],
)
def test_a_record_the_schema_would_refuse_isnt_written(
    tmp_path: Path,
    contract: Contract,
    field: str,
    content_hash: str,
    size: int,
    run: api.Generation,
) -> None:
    """A field that hasn't the form the record schema asks for would leave the result `missing`
    as soon as it is checked (`INVALID_RECORD`): the record is refused, naming the field, and
    nothing is written, at either place."""
    with pytest.raises(ValueError, match=f"^`{field}` "):
        api.write_records(tmp_path, TWICE, content_hash, size, run)
    assert list(tmp_path.iterdir()) == []
    # The same run, with the forms the schema asks for, is written.
    api.write_records(tmp_path, TWICE, RECORD["content_hash"], RECORD["size"], RUN)
    for place in TWICE.places:
        found = read_record(WorktreeReader(tmp_path, None), place.record_path, contract)
        assert isinstance(found, api.ProvenanceRecord)


def test_writing_a_record_again_replaces_it(tmp_path: Path, contract: Contract) -> None:
    """A result made again is recorded again, in place of its record."""
    api.write_records(tmp_path, RESULT, RECORD["content_hash"], RECORD["size"], RUN)
    made = digest_bytes(b"other\n")
    api.write_records(tmp_path, RESULT, made.content_hash, made.size, RUN)
    found = read_record(WorktreeReader(tmp_path, None), PLACE, contract)
    assert found == api.ProvenanceRecord(RESULT.id, made.content_hash, made.size, RUN)
    assert [p.name for p in (tmp_path / PLACE).parent.iterdir()] == ["subanalysis1.output1.json"]


def test_a_result_from_a_commit_isnt_recorded(tmp_path: Path) -> None:
    """It is never built, and its places are in its commit's tree: written in the working tree
    they would name no place of its, and could be a tracked record's of another analysis."""
    from_commit = replace(RESULT, commit=api.Commit("c" * 40))
    with pytest.raises(ValueError, match="is a result from the commit c{40}: it is never built"):
        api.write_records(tmp_path, from_commit, RECORD["content_hash"], RECORD["size"], RUN)
    assert not (tmp_path / ".astra").exists()
