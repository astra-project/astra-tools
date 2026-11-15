"""Records: the record at a result's place, read and written.

A record is read as UTF-8 JSON text (`load.load_json`) and checked by the record schema its
minor version picks (`contract.Contract.check_record`): 0.1's, the open one for a greater minor
version, which ignores the fields it doesn't know, and none below 0.1. One is written
atomically, with sorted keys, two-space indentation and a final line break.

What a record says is a runner's to find out, and true of its run (`FALSE_RECORD`): the bytes
its recipe made and read, the commit it ran from, the environment it ran in. Nothing here hashes
a file or reads a checkout. `write_records` writes what the runner found at every place of the
result it built (`UNRECORDED_RESULT`), and refuses a record a checker would then call invalid.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from astra._internal.documents.catalogue import Catalogue
from astra._internal.documents.contract import Contract
from astra._internal.documents.load import ParseError, load_json
from astra._internal.sources.reader import CommitReader, Reader
from astra.model import to_json
from astra.model.diagnostic import Diagnostic, Location
from astra.model.provenance_record import (
    Environment,
    Generation,
    ProvenanceRecord,
    RecordedInput,
    Runner,
)
from astra.model.resolved_analysis import Result


def _record(value: Mapping[str, Any]) -> ProvenanceRecord:
    """The record whose JSON value the contract accepted; a field of a greater minor version
    than 0.1 is left out."""
    run = value["generated_by"]
    return ProvenanceRecord(
        value["address"],
        value["content_hash"],
        value["size"],
        Generation(
            run["commit"],
            Environment(run["environment"]["iri"]),
            Runner(run["runner"]["id"], run["runner"]["version"]),
            tuple(
                RecordedInput(item["entry"], item["content_hash"], item["size"])
                for item in run.get("inputs", ())
            ),
            run.get("started"),
            run.get("finished"),
        ),
        value["spec_version"],
    )


def read_record(
    reader: Reader, path: str, contract: Contract
) -> ProvenanceRecord | tuple[Diagnostic, ...] | None:
    """The record at `path` in `reader`; or, for one that breaks a parse or schema rule, the
    diagnostic of each, which leave its result `missing` (`INVALID_RECORD`); None where no file
    is there, a symlink being none. Raises OSError where it can't be read."""
    entry = reader.stat(path)
    if entry is None or entry.kind != "file":
        return None
    commit, url = (reader.commit, reader.url) if isinstance(reader, CommitReader) else (None, None)
    try:
        document = load_json(reader.read(path))
    except ParseError as error:
        location = Location(path, "", error.line, error.column, None, commit, url)
        return (contract.catalogue.diagnostic(error.code, error.message, location),)
    found = contract.check_record(document, path)
    if found:
        return tuple(
            replace(d, location=replace(d.location, commit=commit, url=url)) for d in found
        )
    return _record(document.value)


def write_records(
    folder: str | os.PathLike[str],
    result: Result,
    content_hash: str,
    size: int,
    generated_by: Generation,
) -> None:
    """Record `result`, a result of the analysis whose folder is `folder`, as a run made it: at
    each of its places, a record with that place's address, the hash and size of the bytes the
    recipe made, and the run, `generated_by`. Each is JSON with sorted keys, two-space
    indentation and a final line break, written to a temporary file in the same folder, its
    folders made if need be, then moved into place by `os.replace`.

    Raises ValueError, and writes nothing, where `result` is a result from a commit
    (`Result.commit`), which is never built and whose places aren't in the working tree; and
    where the record would be invalid: `generated_by` hasn't one item of `inputs` for each
    entry the result's output lists (`MISSING_RECORD_INPUTS`), or a field hasn't the form the
    record schema asks for. Raises OSError where a record can't be written."""
    if result.commit is not None:
        raise ValueError(
            f"`{result.id}` is a result from the commit {result.commit.id}: it is never built, "
            "and its record is the one at that commit"
        )
    listed = sorted(source.entry for source in result.inputs)
    if sorted(item.entry for item in generated_by.inputs) != listed:
        raise ValueError(
            f"`{result.id}` reads {listed}: a record gives one item of `inputs` for each"
        )
    contract = Contract.load(Catalogue.load())
    written: dict[Path, str] = {}
    for place in result.places:
        record = ProvenanceRecord(place.address, content_hash, size, generated_by)
        text = json.dumps(to_json(record), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        broken = contract.check_record(load_json(text.encode()), place.record_path)
        if broken:
            raise ValueError("; ".join(diagnostic.message for diagnostic in broken))
        written[Path(folder, place.record_path)] = text
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
