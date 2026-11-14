"""Records, read as UTF-8 JSON text and checked by the record schema their minor version picks;
and `records`: reading one at a place, writing one, and the record a runner makes of its run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from astra.contract import Contract
from astra.diagnostics import Catalogue
from astra.hashing import digest_bytes
from astra.load import ParseError, load_json
from astra.records import Record, RecordedInput, Runner, read_record, timestamp, write_record
from astra.sources.reader import WorktreeReader
from tests.conftest import RUNNER
from tests.spec import DOCUMENTS

RECORD = json.loads((DOCUMENTS / "valid" / "ProvenanceRecord-001-full.json").read_text("utf-8"))
"""A valid record of 0.1, astra-spec's fixture."""


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


# --- reading and writing records, and the record of a run ---


def test_a_record_is_written_with_sorted_keys_two_spaces_and_a_final_line_break(
    tmp_path: Path, contract: Contract
) -> None:
    record = Record.from_json(RECORD)
    path = tmp_path / ".astra" / "records" / "u1" / "output1.json"
    write_record(path, record)
    text = path.read_text("utf-8")
    assert text == json.dumps(RECORD, indent=2, sort_keys=True) + "\n"
    assert [p.name for p in path.parent.iterdir()] == ["output1.json"]  # no temporary file left
    reader = WorktreeReader(tmp_path, None)
    assert read_record(reader, ".astra/records/u1/output1.json", contract) == record


def test_reading_a_record_gives_it_or_each_rule_it_breaks(
    tmp_path: Path, contract: Contract
) -> None:
    """A record that breaks a parse or schema rule gives its diagnostic, at its place in the
    record; nothing at the path, or a symlink there, is no record."""
    (tmp_path / "broken.json").write_text(json.dumps({**RECORD, "size": -1}))
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "link.json").symlink_to("broken.json")
    reader = WorktreeReader(tmp_path, None)
    found = read_record(reader, "broken.json", contract)
    assert isinstance(found, tuple)
    assert [(d.code, d.location.file, d.location.pointer) for d in found] == [
        ("INVALID_VALUE", "broken.json", "/size")
    ]
    found = read_record(reader, "bad.json", contract)
    assert isinstance(found, tuple) and [d.code for d in found] == ["INVALID_SYNTAX"]
    assert read_record(reader, "link.json", contract) is None
    assert read_record(reader, "nothere.json", contract) is None


def test_a_later_minor_versions_fields_are_left_out_of_the_record(contract: Contract) -> None:
    later = {**RECORD, "spec_version": "0.2.0", "extra": 1}
    assert Record.from_json(later).to_json() == {**RECORD, "spec_version": "0.2.0"}


def test_a_record_of_a_run_holds_what_the_runner_gives_it(
    tmp_path: Path, contract: Contract
) -> None:
    """A runner makes a record of what its run made and read, at each place of the result it
    built, with that place's address: the hash and size of the bytes made, and of what each
    entry read, the commit, environment, runner and times. `inputs`, `started` and `finished`
    are left out of its JSON where it has none, and it reads back as it was written."""
    commit = "a" * 40
    made = digest_bytes(b"{}\n")
    started = datetime(2026, 10, 26, 14, 0, 0, 123456, tzinfo=UTC)
    record = Record(
        "stage.inner.output1#u1",
        made.content_hash,
        made.size,
        commit,
        "urn:example:env",
        Runner("example-runner", "1.2.0"),
        started=timestamp(started),
        finished=timestamp(started + timedelta(seconds=2)),
    )
    assert record.digest == made
    assert record.to_json() == {
        "spec_version": "0.1.0",
        "address": "stage.inner.output1#u1",
        "content_hash": made.content_hash,
        "size": 3,
        "generated_by": {
            "commit": commit,
            "environment": {"iri": "urn:example:env"},
            "runner": {"id": "example-runner", "version": "1.2.0"},
            "started": "2026-10-26T14:00:00.123Z",
            "finished": "2026-10-26T14:00:02.123Z",
        },
    }
    read = (RecordedInput("inner.output1", made.content_hash, 3),)
    reading = Record(
        "through_inner#u1", made.content_hash, 3, commit, "urn:example:env", RUNNER, read
    )
    assert reading.inputs[0].digest == made
    assert reading.to_json()["generated_by"] == {
        "commit": commit,
        "environment": {"iri": "urn:example:env"},
        "runner": {"id": RUNNER.id, "version": RUNNER.version},
        "inputs": [{"entry": "inner.output1", "content_hash": made.content_hash, "size": 3}],
    }
    path = ".astra/records/u1/through_inner.json"
    write_record(tmp_path / path, reading)
    assert read_record(WorktreeReader(tmp_path, None), path, contract) == reading


def test_a_time_is_given_in_utc_to_the_millisecond() -> None:
    """`timestamp` gives a moment as a record gives a time, whatever its zone."""
    moment = datetime(2026, 10, 26, 16, 0, 0, 999999, tzinfo=timezone(timedelta(hours=2)))
    assert timestamp(moment) == "2026-10-26T14:00:00.999Z"
