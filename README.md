# astra-tools

[![CI](https://github.com/astra-project/astra-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/astra-project/astra-tools/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-green.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

astra-tools is the reference tooling for [ASTRA 0.1](https://astra-spec.org/0.1/), the Agentic
Schema for Transparent Research Analysis. Its command, `astra`, validates an analysis and every
analysis it declares, shows how it looks in each universe, checks what was built against its
records, and reads those records' history from git. It runs no recipe and plans no run: a
runner builds the results and records them, and astra-tools' [Python API](#python-api) tells it
what the results are, where each one goes and what its record holds.

astra-tools reads ASTRA 0.1 files. ASTRA 0.0.x files need its 0.2 line.

## Install

```bash
uv tool install astra-tools
```

Or `pip install astra-tools`. It needs Python 3.11 or later, and git.

While astra-tools for ASTRA 0.1 has only release candidates, uv and pip skip them. Ask for them
with `uv tool install --prerelease allow astra-tools`, or `pip install --pre astra-tools`.

For ASTRA 0.0.x files, install the 0.2 line:

```bash
uv tool install 'astra-tools<0.3'
```

[Installation](https://astra-spec.org/0.1.0rc1/installation/)
gives the details.

## First use

```console
$ astra init my-analysis
✓ created astra.yaml
✓ created .gitignore
✓ created .git
✓ Converged ASTRA analysis scaffold: my-analysis
$ astra validate my-analysis
astra.yaml: valid, 0 error(s), 0 warning(s)
```

`astra init` writes an empty `astra.yaml`, with a `spec_version` and a label, in a git
repository; run again, it changes nothing. Once the analysis has outputs and universes,
`astra view UNIVERSE` shows where each result goes in a universe, and `astra check` whether each
is built and current.
[Getting started](https://astra-spec.org/0.1/getting-started/) goes further.

## Commands

| Command | What it does |
|---|---|
| [`astra init`](https://astra-spec.org/0.1.0rc1/cli/#astra-init) | Make a minimal analysis, or complete one (idempotent) |
| [`astra validate`](https://astra-spec.org/0.1.0rc1/cli/#astra-validate) | Validate an analysis and its whole stack, or every analysis under the current folder |
| [`astra info`](https://astra-spec.org/0.1.0rc1/cli/#astra-info) | Show an analysis in brief |
| [`astra view`](https://astra-spec.org/0.1.0rc1/cli/#astra-view) | Show the analysis as it is in one universe |
| [`astra check`](https://astra-spec.org/0.1.0rc1/cli/#astra-check) | Check the records and bytes of the planned results |
| [`astra history`](https://astra-spec.org/0.1.0rc1/cli/#astra-history) | Show what git holds of a result's records over time |
| [`astra spec`](https://astra-spec.org/0.1.0rc1/cli/#astra-spec) | Describe the fields of ASTRA files |
| [`astra schema`](https://astra-spec.org/0.1.0rc1/cli/#astra-schema) | Show or export the LinkML schemas |
| [`astra guide`](https://astra-spec.org/0.1.0rc1/cli/#astra-guide) | Print the guide for agents |
| [`astra paper`](https://astra-spec.org/0.1.0rc1/cli/#astra-paper) | Keep papers by DOI, and verify quotes in them |

The [CLI reference](https://astra-spec.org/0.1.0rc1/cli/) gives
each command's options, exit codes and examples. The
[specification](https://astra-spec.org/0.1/) says what an analysis means and what each rule asks.

## Python API

`astra.api` is the whole public surface. It asks four questions of an analysis, from its files
and git alone:

```python
from astra import api

api.validate(folder)             # is it valid: every rule it breaks, and where
resolved = api.resolve(folder)   # what it means: its planned results, each after what it reads
resolved.view("baseline")        # ... and how it looks in one universe
api.check(folder)                # do the records still hold: unchanged, stale or missing, and why
api.history(folder)              # what git keeps of those records
```

A planned result gives its address and places, what each entry of its output's `inputs` reads,
the option each of its `decisions` selects, and its command as a template. That is what a
runner builds on. It decides itself what to build, in what order and where; it fills each
command with its own paths (`api.fill`), and writes what its run made as a record at each of
the result's places (`api.Record`, `api.write_record`). Each stale result in a check report
says what changed (`Reason.change`), and `Status.unchanged_given` tells a runner whether a
result that only read what it has just rebuilt needs building too.

## Development

astra-tools is tested against the astra-spec release `uv.lock` installs from PyPI. The tests'
first run downloads that release's conformance suite, examples and test documents from its tag on
GitHub, and keeps them in `~/.cache/astra-tools-tests/`.

```bash
uv sync --frozen
```

The checks:

```bash
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen mypy --strict src/
uv run --frozen ruff check src/ tests/
uv run --frozen ruff format --check src/ tests/
```

[CLAUDE.md](https://github.com/astra-project/astra-tools/blob/main/CLAUDE.md) gives the
layout, the constraints the code keeps, and how to move to a new astra-spec release.

## Licence

BSD 3-Clause: see [LICENSE](https://github.com/astra-project/astra-tools/blob/main/LICENSE).
