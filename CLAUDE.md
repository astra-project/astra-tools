# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

astra-tools is the **Python CLI and library** for ASTRA 0.1 analyses: it validates them, resolves them into one plain data model, checks their results' records, and writes the records a runner gives it. It reads only `0.1.x` analyses; older ones need `astra-tools<0.3`.

**Architecture**:
- **astra-spec** ([separate repo](https://github.com/astra-project/astra-spec)) = the specification. astra-tools reads its JSON Schemas and rule catalogue (`astra.schema`: `jsonschema/`, `rules/rules.json`) at run time, copying nothing.
- **astra-tools** (this repo) = tooling layer: validation, resolution, checking, records, CLI, papers.
- **A runner** (lightcone-cli is one) = what builds the results. It is another package, built on `astra.api`.

astra-tools is intentionally agnostic to any agentic layer or UI. It answers to the specification: argue from it, its conformance suite and its examples, never from one analysis that uses ASTRA.

Both `astra-spec` and this package share the `astra` Python namespace via implicit namespace packages (PEP 420). There is **no** `src/astra/__init__.py`, and never create `src/astra/schema/`.

## Repository Structure

```
src/astra/            # NO __init__.py (namespace package)
  api.py              the whole public surface: the functions, and every class and error re-exported
  errors.py           what the functions raise
  model/              the data model: definitions only, a file for each thing a function returns
  cli/                the `astra` command; rich only under cli/text/
  _internal/          everything else, in layers:
    sources/          every byte read: git, readers, remotes, stand-ins, the cache
    documents/        a file as a document: load, contract, catalogue, document, grammar,
                      scaffold, spec_render
    analysis/         the stack and what it means: stack, universes, rules/, validate, resolve
    results/          records, hashing, status, history (the `astra history` command's)
    papers/           the paper cache, downloads, PDF text and quotes; library is what api offers
docs/                 the CLI, API and data-model reference, for Zensical (zensical.toml)
```

## Key Design Principles

1. **Layers**: a module of `_internal` imports only from its own layer, the ones before it, `astra.model` and `astra.errors`; `papers` builds on `sources` alone. `astra.model` imports nothing else of astra-tools. `tests/test_layout.py` keeps both, and what the top level holds. Rich is imported only under `cli/text/`.
2. **Levels come from the catalogue**: `MUST` is an error, `SHOULD` a warning. astra-tools' own codes are in `_internal/documents/catalogue.py`.
3. **Import cost is part of the API**: `tests/test_import_cost.py` lists what each module may import. Add new modules there.
4. **astra-tools runs nothing, and plans no run**: it says what the files mean (`resolve`), whether they are valid (`validate`) and how the results stand, whether their records still hold (`status`, which applies the specification's check rules: the specification calls the tool that does a checker). Which results to build, in what order, in which checkout and environment, is a runner's to say. In the specification the *analysis* plans its results; no tool here is a planner. A function that needs a checkout, a clock, or the hash of bytes no Reader gave it belongs in a runner.
5. **`astra.api` is the public surface**: `validate`, `resolve`, `status`, `init_analysis`, `write_records`, the paper functions (`paper`, `add_paper`, `verify_quote`), and every class of the data model and error. A tool built on astra-tools imports from there and nowhere else, types included. Add what such a tool needs there, rather than have it reach into `_internal`. Offer a function and plain data, never a class of `_internal`.
6. **The data model is plain data, defined in `model/` and nowhere else**: frozen dataclasses with no methods beyond `to_json`, holding only what JSON holds. Each file of `model/` defines what one function returns, and no logic. A reference is an id (`outputs.fit`, `stage.decisions.method`, `fit#baseline`), never an object; the resolved analysis holds what the specification's rules give, not what they start from (no switch, no `derived_from`, no template), and each fact once. `Stack`, `Element`, `Identity`, `Planned` and `Context` are how astra-tools works it out, and stay inside. A report holds its own answer and no other's: a `StatusReport` has no analysis in it, as `resolve` gives that, and each gives `head`, the commit read, for a runner to tell the two agree. One thing has one model and one JSON form (`model.to_json`): where a command shows what a function of `astra.api` returns, its `--json` prints that, never a shape of its own.
7. **Only a valid analysis resolves**: `resolve` and `status` raise `InvalidAnalysisError` with the validator's report otherwise, so nothing downstream of them handles an undetermined field.

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

### Changing a command, a function or the data model
The reference is in `docs/` (`cli.md`, `api.md`, `data-model.md`), written for Zensical (`zensical.toml`). Change it in the same commit: `tests/test_docs.py` fails for a command, an option, a function, a parameter, a class or a field the pages leave out, and runs their examples.
```bash
uv run --frozen --group docs zensical build --strict
```
Zensical's defaults render the admonitions, tables and Mermaid diagrams the pages use; a `[project.markdown_extensions]` table would replace those defaults, so there is none. In its theme a Mermaid dependency arrow (`..>`, `-->`) has no head: the class diagrams show a reference by id as an aggregation (`o--`).

## Configuration

- Python >=3.11 (on 3.11, `Traversable.joinpath` takes one argument)
- Ruff (line-length 100), mypy strict
- Versioning: hatch-vcs (from git tags)
- Dependencies: astra-spec, click, httpx, jsonschema, linkml-runtime, pypdf, rapidfuzz, rich, ruamel.yaml; no extras

## Key Conventions

1. git only through the `git` binary; no module-level mutable state; every write atomic (`os.replace`).
2. `README.md` is the PyPI page, so its links are full URLs.
3. Commit subjects: `Area: what changed`.
