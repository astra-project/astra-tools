"""What importing each module, and running the light commands, may pull in.

`astra --help` and `validate --json` import neither rich nor the heavy packages,
and rich is imported only under `astra/cli/text/`. Each run is a fresh interpreter, since this
one has imported everything already.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import analysis, git_init

WATCHED = ("rich", "linkml_runtime", "pypdf", "rapidfuzz", "jsonschema", "ruamel.yaml")
"""The dependencies whose import costs enough to watch."""

HEAVY = {"rich", "linkml_runtime", "pypdf", "rapidfuzz"}
"""Imported only by the commands that need them."""

ALLOWED = {
    "astra._internal": (),
    "astra._internal.analysis": (),
    "astra._internal.analysis.resolve": ("ruamel.yaml",),
    "astra._internal.analysis.rules": ("ruamel.yaml",),
    "astra._internal.analysis.rules.commits": ("ruamel.yaml",),
    "astra._internal.analysis.rules.context": ("ruamel.yaml",),
    "astra._internal.analysis.rules.decisions": ("ruamel.yaml",),
    "astra._internal.analysis.rules.declarations": ("ruamel.yaml",),
    "astra._internal.analysis.rules.driving": ("ruamel.yaml",),
    "astra._internal.analysis.rules.inputs": ("ruamel.yaml",),
    "astra._internal.analysis.rules.insights": ("ruamel.yaml",),
    "astra._internal.analysis.rules.names": ("ruamel.yaml",),
    "astra._internal.analysis.rules.outputs": ("ruamel.yaml",),
    "astra._internal.analysis.rules.pins": ("ruamel.yaml",),
    "astra._internal.analysis.rules.recipes": ("ruamel.yaml",),
    "astra._internal.analysis.rules.universes": ("ruamel.yaml",),
    "astra._internal.analysis.stack": ("ruamel.yaml",),
    "astra._internal.analysis.universes": ("ruamel.yaml",),
    "astra._internal.analysis.validate": ("ruamel.yaml",),
    "astra._internal.documents": (),
    "astra._internal.documents.catalogue": (),
    "astra._internal.documents.contract": (),
    "astra._internal.documents.document": (),
    "astra._internal.documents.grammar": (),
    "astra._internal.documents.load": ("ruamel.yaml",),
    "astra._internal.documents.scaffold": (),
    "astra._internal.documents.spec_render": (),
    "astra._internal.papers": (),
    "astra._internal.papers.cache": (),
    "astra._internal.papers.download": (),
    "astra._internal.papers.library": (),
    "astra._internal.papers.pdf": ("rapidfuzz",),
    "astra._internal.results": (),
    "astra._internal.results.status": ("ruamel.yaml",),
    "astra._internal.results.hashing": (),
    "astra._internal.results.history": ("ruamel.yaml",),
    "astra._internal.results.records": ("ruamel.yaml",),
    "astra._internal.sources": (),
    "astra._internal.sources.cache": (),
    "astra._internal.sources.git": (),
    "astra._internal.sources.paths": (),
    "astra._internal.sources.reader": (),
    "astra._internal.sources.remote": (),
    "astra._internal.sources.standins": (),
    "astra.api": ("ruamel.yaml",),
    "astra.cli": (),
    "astra.cli.status": (),
    "astra.cli.guide": (),
    "astra.cli.history": (),
    "astra.cli.info": (),
    "astra.cli.init": (),
    "astra.cli.paper": (),
    "astra.cli.schema": (),
    "astra.cli.spec": (),
    "astra.cli.text": ("rich",),
    "astra.cli.text.status": ("rich",),
    "astra.cli.text.history": ("rich", "ruamel.yaml"),
    "astra.cli.text.info": ("rich", "ruamel.yaml"),
    "astra.cli.text.validate": ("rich",),
    "astra.cli.text.view": ("rich",),
    "astra.cli.validate": (),
    "astra.cli.view": (),
    "astra.errors": (),
    "astra.model": (),
    "astra.model.status_report": (),
    "astra.model.diagnostic": (),
    "astra.model.paper": (),
    "astra.model.provenance_record": (),
    "astra.model.resolved_analysis": (),
    "astra.model.validation_report": (),
}
"""Each module, with what importing it may pull in of `WATCHED`. A new module is added here."""

SRC = Path(__file__).parents[1] / "src" / "astra"


def test_every_module_is_listed() -> None:
    modules = set()
    for path in SRC.rglob("*.py"):
        parts = path.relative_to(SRC.parent).with_suffix("").parts
        modules.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    assert modules == set(ALLOWED)


def imported(code: str, env: dict[str, str] | None = None) -> set[str]:
    """Which of `WATCHED` running `code` in a fresh interpreter imports."""
    probe = (
        f"{code}\nimport json, sys\nprint(json.dumps([n for n in {WATCHED!r} if n in sys.modules]))"
    )
    process = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
    )
    return set(json.loads(process.stdout.splitlines()[-1]))


@pytest.mark.parametrize("module", sorted(ALLOWED))
def test_importing_a_module_pulls_in_only_what_it_is(module: str) -> None:
    assert imported(f"import {module}") <= set(ALLOWED[module])


def run(*args: str) -> str:
    """Code that runs `astra <args>`, its output thrown away."""
    return (
        "import contextlib, io\n"
        "from astra.cli import main\n"
        "with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())):\n"
        "    try:\n"
        f"        main({list(args)!r}, prog_name='astra')\n"
        "    except SystemExit:\n"
        "        pass\n"
    )


def test_help_imports_no_heavy_package() -> None:
    assert imported(run("--help")) & HEAVY == set()


def test_validate_json_imports_no_heavy_package(tmp_path: Path) -> None:
    folder = analysis(git_init(tmp_path))
    assert imported(run("validate", str(folder), "--json")) & HEAVY == set()


def importing(packages: set[str]) -> list[str]:
    """The modules of astra-tools whose source imports one of `packages`, or a module of one."""
    found = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_bytes())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.split(".")[0] in packages for name in names):
                found.append(path.relative_to(SRC).as_posix())
    return found


def test_rich_is_imported_only_under_cli_text() -> None:
    found = importing({"rich"})
    assert found and all(path.startswith("cli/text/") for path in found)


def test_pypdf_and_rapidfuzz_are_imported_only_under_papers() -> None:
    found = importing({"pypdf", "rapidfuzz"})
    assert found and all(path.startswith("_internal/papers/") for path in found)
