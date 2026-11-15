"""The data model: what the functions of `astra.api` return, and what a runner hands back.

Definitions only, a file for each:

- `validation_report`: `ValidationReport`, what `validate` returns;
- `resolved_analysis`: `ResolvedAnalysis`, what `resolve` returns, and the classes it is made of;
- `check_report`: `CheckReport`, what `check` returns;
- `provenance_record`: `ProvenanceRecord`, a result's record, which a runner gives
  `write_records` and a check report holds;
- `diagnostic`: `Diagnostic`, a rule broken and where, which the reports hold;
- `paper`: `Paper` and `QuoteStatus`, what the paper functions return.

Every class is a frozen dataclass that holds what JSON holds, and a reference to another element
is its id, never the object. Each writes as JSON by one rule (`to_json`): an object that holds
every field under its name, an optional one left out where it has no value, never null, and a
list or a map always there, empty or not.

Nothing here imports from the rest of astra-tools, so the definitions read on their own; another
package imports the classes from `astra.api`. This isn't astra-spec's `astra.datamodel`, which
holds the classes LinkML generates from the specification's schemas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any


def to_json(value: Any) -> Any:
    """A value of the data model as JSON: each class as an object that holds every field under
    its name, one with no value left out."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            each.name: to_json(item)
            for each in fields(value)
            if (item := getattr(value, each.name)) is not None
        }
    if isinstance(value, Mapping):
        return {key: to_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_json(item) for item in value]
    return value
