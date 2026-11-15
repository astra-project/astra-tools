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
`astra view UNIVERSE` shows where each result goes in a universe, and `astra status` whether each
is built and current.
[Getting started](https://astra-spec.org/0.1/getting-started/) goes further.

## Commands

| Command | What it does |
|---|---|
| [`astra init`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-init) | Make a minimal analysis, or complete one (idempotent) |
| [`astra validate`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-validate) | Validate an analysis and its whole stack, or every analysis under the current folder |
| [`astra info`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-info) | Show an analysis in brief |
| [`astra view`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-view) | Show the analysis as it is in one universe |
| [`astra status`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-status) | Show how each result stands: its record and its bytes |
| [`astra history`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-history) | Show what git holds of a result's records over time |
| [`astra spec`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-spec) | Describe the fields of ASTRA files |
| [`astra schema`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-schema) | Show or export the LinkML schemas |
| [`astra guide`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-guide) | Print the guide for agents |
| [`astra paper`](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md#astra-paper) | Keep papers by DOI, and verify quotes in them |

The [CLI reference](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md) gives
each command's options, exit codes and examples. The
[specification](https://astra-spec.org/0.1/) says what an analysis means and what each rule asks.

## Python API

`astra.api` is the whole public surface, and the one module another package imports: three
questions of an analysis, answered from its files and git alone in plain data that writes as
JSON; what a tool writes; and the papers that evidence cites.

```python
from astra import api

api.validate(folder)            # is it valid: every rule it breaks, and where
analysis = api.resolve(folder)  # what it means, with every rule of the specification applied
report = api.status(folder)     # how its results stand: each result's status, by its id

api.init_analysis(folder)       # an empty analysis where the folder has none; safe to call again
api.write_records(folder, result, content_hash, size, generated_by)

api.paper(doi)                  # the paper of a DOI, in the paper cache
api.add_paper(doi, pdf=file)    # put one there
api.verify_quote(doi, quote)    # is the quote in it, and on which page
```

A resolved analysis holds every analysis of the stack with what it declares, each universe's
selection, and the planned results, each after every result it reads: its places, what each
entry of its output's `inputs` reads, and its command as it runs. It holds what the rules give
and not what they start from, so it has no switch, no `derived_from` and no template, and each
fact once, so a reference is an id (`outputs.fit`, `stage.decisions.method`, `fit#baseline`).

That is what a runner builds on. It decides itself what to build, in what order and where. A
status report gives it one status for each of those results, by the result's id: what the result itself breaks (`why`), and
which entries read a result that isn't unchanged (`stale_inputs`), so that it can tell, once it
has rebuilt those, whether a result that only read them needs building too. What its run made it
writes with `write_records`, a record at each of the result's places.

The status report holds none of the analysis. `resolve` and `status` each give `head`, the
commit the repository was on, so a runner that asks for both can tell that nothing was committed
between the two.

The status report also says where the bytes of each result and each input are: `present`, or
`absent` and which large-file tool keeps them. astra-tools never fetches them: that is a
runner's to do. git-annex and Git LFS are read without their content, so a clone that has
fetched nothing validates and reads as up to date. An input kept by DVC must be pulled for the
results made from it to be compared, as DVC gives an MD5 and a record a SHA-256.

The paper functions are apart from the rest: the paper cache is a folder of this machine,
`add_paper` uses the network, and matching a quote against a PDF's text is astra-tools' own, as
the specification has no rule on it.

### The data model

What the functions return is defined in
[`src/astra/model/`](https://github.com/astra-project/astra-tools/tree/main/src/astra/model),
a file for each, and those files hold nothing else:

| File | Classes | Where they come from |
|---|---|---|
| `validation_report.py` | `ValidationReport` | `validate` returns it |
| `resolved_analysis.py` | `ResolvedAnalysis`, and the classes it is made of: `Analysis`, `Input`, `Decision`, `Output`, `Insight`, `Universe`, `Result` and their parts | `resolve` returns it |
| `status_report.py` | `StatusReport`, `Status`, `EvidenceStatus` | `status` returns it |
| `provenance_record.py` | `ProvenanceRecord`, `Generation` and its parts | a runner gives `write_records` a `Generation`; a `Status` holds the record |
| `diagnostic.py` | `Diagnostic`, `Location` | the reports hold them |
| `paper.py` | `Paper`, `QuoteStatus` | the paper functions return them |

Every class is a frozen dataclass that holds what JSON holds. Each writes as JSON by one rule:
every field under its name, an optional one left out where it has no value, never null, and a
list or a map always there. `astra validate --json`, `astra info --json` and
`astra status --json` print the three reports exactly so.

## Documentation

The documentation is in [`docs/`](https://github.com/astra-project/astra-tools/blob/main/docs), written for
[Zensical](https://zensical.org/):

| Page | What it holds |
|---|---|
| [CLI reference](https://github.com/astra-project/astra-tools/blob/main/docs/cli.md) | Every command: its arguments, options, output and exit codes |
| [Python API](https://github.com/astra-project/astra-tools/blob/main/docs/api.md) | The functions of `astra.api`, what they raise, and a runner in brief |
| [Data model](https://github.com/astra-project/astra-tools/blob/main/docs/data-model.md) | Every class field by field, with UML diagrams and the JSON of each report |

```bash
uv run --frozen --group docs zensical serve    # preview at http://localhost:8000
uv run --frozen --group docs zensical build --strict
```

`tests/test_docs.py` keeps the pages in step with the code: every command and option, every
function and parameter, every class and field, and each example run against astra-tools.

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
