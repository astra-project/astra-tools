# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

astra-tools is the **Python CLI and library** for ASTRA 0.1 analyses: it validates them, resolves them into their planned results, checks those results' records, and holds the record format a runner writes. It reads only `0.1.x` analyses; older ones need `astra-tools<0.3`.

**Architecture**:
- **astra-spec** ([separate repo](https://github.com/astra-project/astra-spec)) = the specification. astra-tools reads its JSON Schemas and rule catalogue (`astra.schema`: `jsonschema/`, `rules/rules.json`) at run time, copying nothing.
- **astra-tools** (this repo) = tooling layer: validation, resolution, checking, records, CLI, papers.
- **A runner** (lightcone-cli is one) = what builds the results. It is another package, built on `astra.api`.

astra-tools is intentionally agnostic to any agentic layer or UI. It answers to the specification: argue from it, its conformance suite and its examples, never from one analysis that uses ASTRA.

Both `astra-spec` and this package share the `astra` Python namespace via implicit namespace packages (PEP 420). There is **no** `src/astra/__init__.py`, and never create `src/astra/schema/`.

## Repository Structure

```
src/astra/          # NO __init__.py (namespace package), in layers:
  0 foundations     diagnostics, grammar, model
  1 reading         sources/ (every byte read), cache, load, contract, scaffold
  2 binding         stack
  3 meaning         universes, rules/, validate, view, resolve
  4 results         hashing, records, check, history
  5 surfaces        api (the whole public surface), cli/, spec_render,
                    papers/ and verification/ (the paper cache and quotes, as 0.2 had them)
```

## Key Design Principles

1. **Layers**: a module imports only from its own layer or the ones before it. Rich is imported only under `cli/text/`.
2. **Levels come from the catalogue**: `MUST` is an error, `SHOULD` a warning. astra-tools' own codes are in `diagnostics.py`.
3. **Import cost is part of the API**: `tests/test_import_cost.py` lists what each module may import. Add new modules there.
4. **astra-tools runs nothing, and plans no run**: it says what the files mean (`resolve`), whether they are valid (`validate`) and whether the records still hold (`check`). Which results to build, in what order, in which checkout and environment, and with which paths in a command, is a runner's to say. In the specification the *analysis* plans its results; no tool here is a planner. A function that needs a checkout, a clock, or the hash of bytes no Reader gave it belongs in a runner.
5. **`astra.api` is the public surface**: a tool built on astra-tools imports from there, types included. Add what such a tool needs there, rather than have it reach into a layer.

## Development Commands

### Setup
astra-spec is the release `uv.lock` installs from PyPI. `tests/spec.py` downloads that release's conformance suite, examples and test documents from its tag on GitHub, once, into `~/.cache/astra-tools-tests/`:
```bash
uv sync --frozen
```

### Testing and linting
```bash
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen mypy --strict src/
uv run --frozen ruff check src/ tests/
uv run --frozen ruff format --check src/ tests/
```

## Common Development Tasks

### Moving to a new astra-spec release
astra-tools only ever uses an astra-spec published on PyPI. Once it is, widen the requirement in `pyproject.toml` if need be and, in the same commit as the changes it needs:
```bash
uv lock --upgrade-package astra-spec
uv sync --frozen
```

### Changing a command
The CLI reference and installation page live in astra-spec (`docs/cli.md`, `docs/installation.md`), which astra-spec.org shows. Change them there too, for a new command or option.

## Configuration

- Python >=3.11 (on 3.11, `Traversable.joinpath` takes one argument)
- Ruff (line-length 100), mypy strict
- Versioning: hatch-vcs (from git tags)
- Dependencies: astra-spec, click, httpx, jsonschema, linkml-runtime, pypdf, rapidfuzz, rich, ruamel.yaml; no extras

## Key Conventions

1. git only through the `git` binary; no module-level mutable state; every write atomic (`os.replace`).
2. `README.md` is the PyPI page, so its links are full URLs.
3. Commit subjects: `Area: what changed`.
