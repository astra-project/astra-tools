"""The package's layout: a namespace shared with astra-spec, the public surface at its top, the
data model on its own, the layers below, and the core dependencies."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.metadata
import inspect
import re
import sys
from pathlib import Path

import pytest

from astra import api, errors

SRC = Path(__file__).parents[1] / "src" / "astra"


def test_the_namespace_has_no_init_and_no_schema() -> None:
    assert not (SRC / "__init__.py").exists()
    assert not (SRC / "schema").exists()


def test_the_top_level_is_the_public_surface_the_command_line_and_the_rest() -> None:
    """What another package imports is `api`; `errors` and `model` hold what it gives, for a
    reader to find; everything else is the command line, or under `_internal`."""
    found = {path.name for path in SRC.iterdir() if path.name != "__pycache__"}
    assert found == {"api.py", "errors.py", "model", "cli", "_internal", "py.typed"}


def imports(path: Path) -> set[str]:
    """The modules of astra-tools that the source at `path` imports, wherever in it."""
    found = set()
    for node in ast.walk(ast.parse(path.read_bytes())):
        names = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
        found |= {name for name in names if name == "astra" or name.startswith("astra.")}
    return found


def test_the_model_and_the_errors_import_nothing_else_of_astra_tools() -> None:
    """The definitions read on their own: beside the standard library, a file of the model
    imports only the model, and `errors` only the model."""
    for path in [*(SRC / "model").glob("*.py"), SRC / "errors.py"]:
        assert all(name.startswith("astra.model") for name in imports(path)), path.name
        other = {
            node.module.split(".")[0]
            for node in ast.walk(ast.parse(path.read_bytes()))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert other <= {"astra", *sys.stdlib_module_names}, path.name


LAYERS = {
    "sources": {"sources"},
    "documents": {"documents"},
    "analysis": {"sources", "documents", "analysis"},
    "results": {"sources", "documents", "analysis", "results"},
    "papers": {"sources", "papers"},
}
"""Each layer of `_internal`, with the layers a module of it may import from."""


@pytest.mark.parametrize("layer", sorted(LAYERS))
def test_a_layer_imports_only_from_itself_and_the_ones_before_it(layer: str) -> None:
    assert {path.name for path in (SRC / "_internal").iterdir() if path.is_dir()} - {
        "__pycache__"
    } == set(LAYERS)
    allowed = tuple(f"astra._internal.{name}" for name in LAYERS[layer])
    for path in (SRC / "_internal" / layer).rglob("*.py"):
        for name in imports(path):
            assert name.startswith(("astra.model", "astra.errors", *allowed)), (path.name, name)


def test_the_api_gives_every_class_of_the_model_and_every_error() -> None:
    """`astra.api` is the one place another package imports from, so it leaves nothing out."""
    classes = set()
    for path in (SRC / "model").glob("*.py"):
        module = importlib.import_module(f"astra.model.{path.stem}".removesuffix(".__init__"))
        classes |= {
            name
            for name, value in vars(module).items()
            if dataclasses.is_dataclass(value) and value.__module__ == module.__name__
        }
    raised = {
        name
        for name, value in vars(errors).items()
        if inspect.isclass(value) and issubclass(value, Exception)
    }
    functions = {name for name in api.__all__ if inspect.isfunction(getattr(api, name))}
    assert classes and raised and set(api.__all__) == classes | raised | functions
    assert functions == {
        "validate",
        "resolve",
        "status",
        "write_records",
        "init_analysis",
        "paper",
        "add_paper",
        "verify_quote",
    }


def test_the_dependencies_and_no_extras() -> None:
    requires = importlib.metadata.requires("astra-tools") or []
    assert not [r for r in requires if "extra ==" in r]
    names = {re.sub(r"[-_.]+", "-", re.match(r"[A-Za-z0-9._-]+", r)[0]).lower() for r in requires}
    assert names == {
        "astra-spec",
        "click",
        "httpx",
        "jsonschema",
        "linkml-runtime",
        "pypdf",
        "rapidfuzz",
        "rich",
        "ruamel-yaml",
    }
