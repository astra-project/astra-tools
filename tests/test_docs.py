"""The documentation in `docs/`: it covers every command and option, every function of
`astra.api` and every class and field of the data model, and its examples are what
astra-tools gives."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click
import pytest

from astra import api, errors
from astra.cli import COMMANDS
from tests.conftest import repository

DOCS = Path(__file__).parents[1] / "docs"
MODEL = Path(__file__).parents[1] / "src" / "astra" / "model"


def page(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The section of `text` under `heading`, a line such as "## `astra init`": up to the next
    heading of its level or above."""
    start = text.index(f"\n{heading}\n")
    depth = len(heading.split(" ")[0])
    end = re.search(rf"\n#{{1,{depth}}} ", text[start + 1 :])
    return text[start : start + 1 + end.start()] if end else text[start:]


def blocks(text: str, language: str) -> list[str]:
    """The fenced code blocks of `text` in `language`."""
    return re.findall(rf"```{language}\n(.*?)```", text, re.S)


# --- the command line ---


def flags(command: click.Command) -> set[str]:
    """Every spelling of every option of `command`, `--help` aside."""
    return {
        flag
        for parameter in command.params
        if isinstance(parameter, click.Option)
        for flag in parameter.opts
    }


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_every_command_and_option_is_in_the_cli_reference(name: str) -> None:
    command = importlib.import_module(COMMANDS[name]).command
    text = section(page("cli.md"), f"## `astra {name}`")
    assert f"(#astra-{name})" in page("cli.md"), "the command is in the table at a glance"
    documented = [command]
    if isinstance(command, click.Group):
        for sub, subcommand in command.commands.items():
            assert re.search(rf"astra {name} {re.escape(sub)}\b", text), sub
            documented.append(subcommand)
    for each in documented:
        for flag in flags(each):
            assert re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text), (each.name, flag)


# --- the API ---


FUNCTIONS = sorted(name for name in api.__all__ if inspect.isfunction(getattr(api, name)))


@pytest.mark.parametrize("name", FUNCTIONS)
def test_every_function_and_parameter_is_in_the_api_reference(name: str) -> None:
    text = page("api.md")
    heading = next(h for h in (f"## `{name}`", f"### `{name}`") if f"\n{h}\n" in text)
    own = section(text, heading)
    assert f"(#{name})" in text, "the function is in the table"
    for parameter in inspect.signature(getattr(api, name)).parameters:
        assert re.search(rf"\b{parameter}\b", own), parameter


def test_every_error_is_in_the_api_reference() -> None:
    table = section(page("api.md"), "## Errors")
    raised = {
        name
        for name, value in vars(errors).items()
        if inspect.isclass(value) and issubclass(value, Exception)
    }
    assert raised and all(f"| `{name}` |" in table for name in raised)


# --- the data model ---


def classes() -> list[type]:
    found = []
    for path in sorted(MODEL.glob("*.py")):
        module = importlib.import_module(f"astra.model.{path.stem}".removesuffix(".__init__"))
        found += [
            value
            for value in vars(module).values()
            if dataclasses.is_dataclass(value)
            and isinstance(value, type)
            and value.__module__ == module.__name__
        ]
    return found


@pytest.mark.parametrize("cls", classes(), ids=lambda cls: cls.__name__)
def test_every_class_and_field_is_in_the_data_model(cls: type) -> None:
    """Each class has a section with a row for each of its fields, and no other row; and it is
    drawn in a diagram."""
    text = page("data-model.md")
    rows = re.findall(r"^\| `(\w+)` \|", section(text, f"### `{cls.__name__}`"), re.M)
    assert rows == [field.name for field in dataclasses.fields(cls)]
    drawn = "\n".join(blocks(text, "mermaid"))
    assert re.search(rf"\b{cls.__name__}\b", drawn)


# --- the examples ---


FIT = """\
import json
import sys
from pathlib import Path

catalog, method, output = sys.argv[1:]
Path(output).parent.mkdir(parents=True, exist_ok=True)
Path(output).write_text(json.dumps({"method": method}))
"""


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """The analysis the pages take their examples from, in a repository, with nothing built."""
    (spec,) = blocks(section(page("data-model.md"), "## The resolved analysis"), "yaml")
    assert spec in page("cli.md"), "the CLI reference uses the same analysis"
    return repository(tmp_path, {"astra.yaml": spec, "data/catalog.csv": "x,y\n", "fit.py": FIT})


def test_the_json_examples_are_what_the_functions_give(example: Path) -> None:
    text = page("data-model.md")
    (validated,) = blocks(section(text, "### `ValidationReport`"), "json")
    assert json.loads(validated) == api.validate(example).to_json()
    (resolved,) = blocks(section(text, "## The resolved analysis"), "json")
    assert json.loads(resolved) == api.resolve(example).to_json()
    (checked,) = blocks(section(text, "## The status report"), "json")
    report = api.status(example).to_json()
    assert json.loads(checked) == {key: report[key] for key in ("statuses", "evidence")}


def test_the_runner_of_the_api_reference_builds_and_records(example: Path) -> None:
    """Run as it is written, it leaves the example's result `unchanged`."""
    (runner,) = blocks(section(page("api.md"), "## A runner, in brief"), "python")
    path = os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]])
    subprocess.run(
        [sys.executable, "-c", runner], cwd=example, env={**os.environ, "PATH": path}, check=True
    )
    status = api.status(example).statuses["fit#baseline"]
    assert (status.state, status.bytes) == ("unchanged", "present")
    assert status.record is not None and status.record.generated_by.runner.id == "example-runner"
