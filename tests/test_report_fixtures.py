"""Portable JSON oracles: real repositories, read only through the public API."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft201909Validator

from astra import api

FIXTURES = Path(__file__).parent / "report-fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text("utf-8"))


def test_fixture_specification_release_is_installed() -> None:
    assert version("astra-spec") == MANIFEST["specification"]["release"]


def build(case: Path, place: Path) -> Path:
    """Build the portable case using precisely its manifest's environment."""
    work = Path(shutil.copytree(case / "files", place / "work"))
    (place / "home").mkdir()
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(place / "home"),
        "GIT_CEILING_DIRECTORIES": str(place),
        **MANIFEST["git_environment"],
    }
    subprocess.run(["sh", "-eu", str(case / "setup.sh")], cwd=work, env=environment, check=True)
    return work


@pytest.mark.parametrize("name", MANIFEST["cases"])
@pytest.mark.parametrize("operation", ["validate", "resolve", "status"])
def test_public_report_matches_portable_json(
    name: str, operation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = FIXTURES / name
    work = build(case, tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    actual = getattr(api, operation)(work, offline=True).to_json()
    expected = json.loads((case / f"{operation}.json").read_text("utf-8"))
    schema = json.loads(files("astra.model").joinpath("reports.schema.json").read_text("utf-8"))
    Draft201909Validator(schema).validate(expected)
    assert actual == expected
