"""The packaged report schema follows the public JSON form, with no runtime generation."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft201909Validator

from astra import api
from astra.model import to_json
from tests.conftest import MINIMAL, build, repository

RESOURCE = files("astra.model").joinpath("reports.schema.json")
ROOT = Path(__file__).parents[1]


@pytest.fixture
def schema() -> dict[str, Any]:
    return json.loads(RESOURCE.read_text(encoding="utf-8"))


def test_the_packaged_schema_is_generated_from_the_model() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate-report-schema.py"), "--check"],
        check=True,
    )


def test_the_schema_is_valid(schema: dict[str, Any]) -> None:
    Draft201909Validator.check_schema(schema)


def test_real_reports_validate_before_and_after_building(
    schema: dict[str, Any], tmp_path: Path
) -> None:
    top = repository(tmp_path, {"astra.yaml": MINIMAL})
    validator = Draft201909Validator(schema)
    for report in (api.validate(top), api.resolve(top), api.status(top)):
        validator.validate(report.to_json())
    build(top)
    report = api.status(top)
    assert report.statuses["result"].record is not None
    validator.validate(report.to_json())
    (top / "astra.yaml").write_text("spec_version: '0.1.0'\noutputs: false\n", "utf-8")
    invalid = api.validate(top)
    assert not invalid.valid and invalid.diagnostics
    validator.validate(invalid.to_json())


@pytest.fixture
def examples() -> dict[str, dict[str, Any]]:
    """Populated instances cover every dataclass reachable from the three reports."""
    location = api.Location("astra.yaml", "/outputs/fit", 2, 3, "fit", "abc", "https://example.org")
    diagnostic = api.Diagnostic(
        "EXAMPLE", "warning", "An example diagnostic", location, (location,)
    )
    evidence = api.Evidence(
        doi="10.1234/example",
        version=1,
        quote=api.TextQuoteSelector("quoted text", "before", "after"),
        location=api.FragmentSelector("page=6", "https://example.org/selector"),
    )
    insight = api.Insight(
        "findings.conclusion",
        "finding",
        "A claim",
        (evidence, api.Evidence(cites=("fit#baseline",), artifact="fit#baseline")),
        "Conclusion",
        "Details",
        "Scope",
        ("tag",),
    )
    analysis = api.Analysis(
        "",
        ".",
        api.Commit("abc", "https://example.org/repo.git"),
        inputs=(api.Input("inputs.catalog", "catalog.csv", "Catalog", "Details", ("data",)),),
        decisions=(
            api.Decision("decisions.method", (api.Option("a", insights=("prior_insights.p",)),)),
        ),
        outputs=(
            api.Output(
                "outputs.fit", "metric", "json", resources=api.Resources(2, "1G", "1h", "2G", 1)
            ),
        ),
        findings=(insight,),
        universes=(api.Universe("universes.baseline", {"decisions.method": "a"}),),
    )
    result = api.Result(
        "fit#baseline",
        "outputs.fit",
        (api.Place("fit#baseline", "fit.json", "fit.csv"),),
        "universes.baseline",
        (api.Source("catalog", input="inputs.catalog"),),
        "python fit.py",
        api.Commit("abc"),
    )
    record = api.ProvenanceRecord(
        "fit#baseline",
        "sha256:abc",
        12,
        api.Generation(
            "abc",
            api.Environment("urn:example:env"),
            api.Runner("runner", "1"),
            (api.RecordedInput("catalog", "sha256:def", 3),),
            "started",
            "finished",
        ),
    )
    reports = (
        api.ResolvedAnalysis("0.1.0", "abc", (analysis,), (result,), (diagnostic,)),
        api.ValidationReport("astra.yaml", False, (diagnostic,), ("UNIMPLEMENTED",)),
        api.StatusReport(
            "abc",
            {
                "fit#baseline": api.Status(
                    "stale", api.Bytes("absent", "Git LFS"), record, (diagnostic,), ("catalog",)
                )
            },
            (api.EvidenceStatus(insight.ref, 0, "stale", (diagnostic,)),),
            {"inputs.catalog": api.Bytes("present")},
        ),
    )
    found: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if is_dataclass(value) and not isinstance(value, type):
            found[type(value).__name__] = to_json(value)
            for field in fields(value):
                visit(getattr(value, field.name))
        elif isinstance(value, Mapping):
            for item in value.values():
                visit(item)
        elif isinstance(value, tuple):
            for item in value:
                visit(item)

    visit(reports)
    return found


def test_each_definition_validates_its_model_and_rejects_missing_or_null_fields(
    schema: dict[str, Any], examples: dict[str, dict[str, Any]]
) -> None:
    assert examples.keys() == schema["$defs"].keys()
    for name, definition in schema["$defs"].items():
        validator = Draft201909Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})
        example = examples[name]
        validator.validate(example)
        validator.validate({**example, "future_field": {"value": None}})
        for field in definition["required"]:
            missing = {key: value for key, value in example.items() if key != field}
            assert not validator.is_valid(missing), (name, field)
        for field in definition["properties"]:
            assert not validator.is_valid({**example, field: None}), (name, field)


@pytest.mark.parametrize("name", ["ResolvedAnalysis", "ValidationReport", "StatusReport"])
def test_report_versions_cannot_be_omitted_or_changed(
    schema: dict[str, Any], examples: dict[str, dict[str, Any]], name: str
) -> None:
    validator = Draft201909Validator(schema)
    example = examples[name]
    validator.validate(example)
    assert not validator.is_valid({**example, "schema_version": "unknown.v1"})
    assert not validator.is_valid(
        {key: value for key, value in example.items() if key != "schema_version"}
    )
