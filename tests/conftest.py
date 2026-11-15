"""Shared by the tests: the cache kept apart, git, and results built as a runner builds them.
astra-spec's conformance suite and examples are in `tests/spec.py`."""

from __future__ import annotations

import importlib.metadata
import subprocess
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest

from astra import api
from astra._internal.analysis.resolve import read
from astra._internal.results.hashing import Digest, digest_bytes, digest_file
from astra._internal.results.history import History
from astra._internal.sources.remote import Remotes

MINIMAL = """\
spec_version: "0.1.0"
outputs:
  result:
    type: metric
    format: json
    recipe:
      command: python make.py '{output}'
"""
"""A minimal `astra.yaml` that makes something: a `spec_version` and one output."""


def pytest_report_header(config: pytest.Config) -> str:
    return f"astra-spec {importlib.metadata.version('astra-spec')}"


@pytest.fixture(autouse=True, scope="session")
def session_cache(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """A cache for fixtures wider than a test, such as a module's built repository, which are set
    up before `cache` and would otherwise use the user's own."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ASTRA_CACHE_DIR", str(tmp_path_factory.mktemp("session-cache")))
        yield


@pytest.fixture(autouse=True)
def cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test's cache is a folder of its own, outside every repository."""
    monkeypatch.setenv("ASTRA_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))


@pytest.fixture
def outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder in no git repository: git looks for none above it."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    folder = tmp_path / "analysis"
    folder.mkdir()
    return folder


def git_init(folder: Path) -> Path:
    """A new git repository whose working tree is `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(folder)], check=True)
    return folder


GIT = (
    "git",
    "-c",
    "user.name=astra-tools tests",
    "-c",
    "user.email=tests@astra.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "protocol.file.allow=always",
)
"""git, with an identity of its own, never signing, and free to add a local submodule."""


def git(top: Path, *args: str) -> str:
    """Run git in the working tree `top`, and give what it prints."""
    process = subprocess.run([*GIT, "-C", str(top), *args], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    return process.stdout


def repository(top: Path, files: Mapping[str, str | bytes]) -> Path:
    """The git repository at `top`, made if need be, with `files` (each path from `top`, and
    its text or bytes) written and committed: a stack of analyses, say, as
    `{"astra.yaml": ROOT, "sub/astra.yaml": SUB, "sub/data/x.csv": "1,2\n"}`. Gives `top`."""
    if not (top / ".git").exists():
        git_init(top)
    for path, content in files.items():
        (top / path).parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        (top / path).write_bytes(data)
    git(top, "add", "--all")
    git(top, "commit", "--quiet", "--no-verify", "--allow-empty", "--message", "stack")
    return top


def analysis(folder: Path, text: str = MINIMAL) -> Path:
    """`folder`, made if need be, with `text` as its `astra.yaml`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "astra.yaml").write_text(text, encoding="utf-8")
    return folder


RUNNER = api.Runner("astra-tools-tests", "1")
ENVIRONMENT = api.Environment("urn:example:environment1")


def owner(analysis: api.ResolvedAnalysis, result: api.Result) -> api.Analysis:
    """The analysis `result` belongs to: its universe's or, for a result built once, its
    output's."""
    for each in analysis.analyses:
        held = each.outputs if result.universe is None else each.universes
        if (result.universe or result.output) in [element.ref for element in held]:
            return each
    raise LookupError(result.id)


def build(
    top: Path,
    folder: Path | None = None,
    *,
    commit: str | None = None,
    made: Callable[[api.Result], bytes] = lambda result: f"{result.places[0].address}\n".encode(),
) -> tuple[api.Result, ...]:
    """Build the analysis in `folder`, `top` by default, a folder of the working tree whose top
    is `top`, as a runner would but without running a recipe: each planned result that isn't a
    result from a commit, each after what it reads, gets the bytes `made` gives it at each of
    its default places, and a record at each of its places, naming `commit` (HEAD by default) as
    the commit its recipe ran from. What an entry reads of a result from a commit is got from
    git. Nothing is committed. Gives the planned results."""
    root = folder or top
    commit = commit or git(top, "rev-parse", "HEAD").strip()
    analysis = api.resolve(root)
    inputs = {each.ref: each for found in analysis.analyses for each in found.inputs}
    results = {result.id: result for result in analysis.results}
    for result in analysis.results:
        if owner(analysis, result).commit is not None:
            continue
        data = made(result)
        for place in result.places:
            (root / place.file_path).parent.mkdir(parents=True, exist_ok=True)
            (root / place.file_path).write_bytes(data)
        read_ = []
        for source in result.inputs:
            found: Digest
            if source.input is not None:
                found = digest_file(root / inputs[source.input].path)
            else:
                upstream = results[source.result or ""]
                at = owner(analysis, upstream).commit
                if at is None:
                    found = digest_file(root / upstream.places[0].file_path)
                else:
                    remotes = Remotes()
                    history = History(read(root, remotes), remotes)
                    found = digest_bytes(history.get(upstream.places[0].address, at.id))
            read_.append(api.RecordedInput(source.entry, found.content_hash, found.size))
        hashed = digest_bytes(data)
        run = api.Generation(commit, ENVIRONMENT, RUNNER, tuple(read_))
        api.write_records(root, result, hashed.content_hash, hashed.size, run)
    return analysis.results


def remake(top: Path, id_: str, data: bytes, environment: api.Environment = ENVIRONMENT) -> None:
    """Make the root's result `id_` again in the working tree `top`, as a runner would from
    HEAD: `data` its bytes, and its record, of what it reads in the working tree, run in
    `environment`."""
    analysis = api.resolve(top)
    paths = {each.ref: each.path for found in analysis.analyses for each in found.inputs}
    paths |= {result.id: result.places[0].file_path for result in analysis.results}
    (result,) = [result for result in analysis.results if result.id == id_]
    (top / result.places[0].file_path).write_bytes(data)
    found = [
        (source.entry, digest_file(top / paths[source.input or source.result or ""]))
        for source in result.inputs
    ]
    listed = tuple(api.RecordedInput(entry, d.content_hash, d.size) for entry, d in found)
    made = digest_bytes(data)
    run = api.Generation(git(top, "rev-parse", "HEAD").strip(), environment, RUNNER, listed)
    api.write_records(top, result, made.content_hash, made.size, run)
