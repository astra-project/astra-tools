# Python API

`astra.api` is the whole public surface of astra-tools, and the one module another package
imports. Everything else is private and may change.

```python
from astra import api
```

It holds eight functions, the classes they return ([Data model](data-model.md)) and the errors
they raise ([Errors](#errors)).

| Function | What it does | Returns |
|---|---|---|
| [`validate`](#validate) | Says whether an analysis is valid | [`ValidationReport`](data-model.md#validationreport) |
| [`resolve`](#resolve) | Says what an analysis means | [`ResolvedAnalysis`](data-model.md#resolvedanalysis) |
| [`check`](#check) | Says whether its results' records still hold | [`CheckReport`](data-model.md#checkreport) |
| [`create_boilerplate`](#create_boilerplate) | Writes a new analysis | nothing |
| [`write_records`](#write_records) | Writes a result's record at each of its places | nothing |
| [`paper`](#paper) | Looks a paper up in the paper cache | [`Paper`](data-model.md#paper), or `None` |
| [`add_paper`](#add_paper) | Puts a paper in the paper cache | [`Paper`](data-model.md#paper) |
| [`verify_quote`](#verify_quote) | Seeks a quote in a cached paper | [`QuoteStatus`](data-model.md#quotestatus) |

The first three are functions of the analysis's files and of git, and nothing else. None runs a
recipe. What to build, in what order, where and in which environment is a runner's own
business, and nothing here says it.

## Reading an analysis

`validate`, `resolve` and `check` read an analysis the same way. `path` is the analysis's
folder, the current folder by default, and it holds the analysis's `astra.yaml`: nothing is
searched for. The analysis is read in the working tree of the git repository that holds it, and
each analysis it declares is read with it, in the working tree or at its commit.

A commit of another repository is fetched into the cache, once. With `offline=True` nothing is
fetched, and only the commits kept from earlier fetches can be read.

All three raise:

- [`NoAnalysisError`](#errors) where `path` holds no `astra.yaml`;
- [`GitError`](#errors) where git can't be run;
- [`CacheError`](#errors) where the cache can't be used;
- `OSError` where a file can't be read.

## `validate`

```python
def validate(path=None, *, offline=False) -> ValidationReport
```

The validator's report on the analysis: a [`Diagnostic`](data-model.md#diagnostic) for each
parse, schema and validator rule it breaks, over its whole stack. An analysis that breaks a
`MUST` isn't an error of the function: the report says so, in `valid` and in its diagnostics.

```python
report = api.validate("my-analysis")
for diagnostic in report.diagnostics:
    at = diagnostic.location
    print(f"{at.file}:{at.line} {diagnostic.level} {diagnostic.code} {diagnostic.message}")
```

## `resolve`

```python
def resolve(path=None, *, offline=False) -> ResolvedAnalysis
```

The analysis, resolved: every analysis of its stack with what it declares, each universe's
selection, and the planned results, each with its places, what it reads and its command as it
runs. Every rule of the specification is already applied, so a reader follows ids and applies
none itself.

Raises [`InvalidAnalysisError`](#errors) where the analysis breaks a `MUST`: only a valid
analysis resolves. The error's `report` is the validator's report.

```python
analysis = api.resolve("my-analysis")
for result in analysis.results:
    print(result.id, result.places[0].bytes_path, result.command)
```

## `check`

```python
def check(path=None, *, at=None, offline=False) -> CheckReport
```

The checker's report: the analysis as it resolved, each planned result's
[`Status`](data-model.md#status), and the status of each evidence that cites an output. One
call tells a runner both what the results are and how each stands.

With `at`, a revision of the repository that holds the analysis (a commit, a branch, a tag),
the analysis is checked as it is at that commit, with its records and bytes read there.

Raises [`InvalidAnalysisError`](#errors) where the analysis breaks a `MUST`, and
[`RequestError`](#errors) where `at` names no commit.

```python
report = api.check("my-analysis")
for id, status in report.statuses.items():
    print(id, status.state, status.bytes, [broken.code for broken in status.why])
```

## `create_boilerplate`

```python
def create_boilerplate(directory) -> None
```

Writes a new analysis into `directory`: an `astra.yaml` with a `spec_version` and a label, and
nothing declared. The folder is made if need be. Nothing else is written or looked at, so a
tool scaffolds into a folder under its own conventions. An `astra.yaml` already there is written
over: guard on its presence.

Raises `OSError` where the file can't be written.

## `write_records`

```python
def write_records(folder, result, content_hash, size, generated_by) -> None
```

Records a result as a run made it. `folder` is the analysis's folder, `result` a
[`Result`](data-model.md#result) of its resolved analysis, `content_hash` and `size` the hash
(`sha256:<hex>`) and size of the bytes the recipe made, and `generated_by` the run, a
[`Generation`](data-model.md#generation).

A [`ProvenanceRecord`](data-model.md#provenancerecord) is written at each of the result's
places, with that place's address. Each is JSON with sorted keys, written to a temporary file
and moved into place.

What a record says is the runner's to find out, and true of its run: this function hashes no
file and reads no checkout.

Raises `ValueError`, and writes nothing, where the record would be invalid: `generated_by`
hasn't one item of `inputs` for each entry the result's output lists, or a field hasn't the
form the record schema asks for. Raises `OSError` where a record can't be written.

## Papers

The paper functions are apart from the rest. They aren't functions of an analysis's files: the
paper cache is a folder of this machine, `add_paper` uses the network, and matching a quote
against a PDF's text is astra-tools' own, as the specification has no rule on it.

A paper is kept under its DOI as it was given and, where one was given, its version. The
lookup is exact: `version=7` and no version are two papers.

All three raise [`CacheError`](#errors) where the cache can't be used.

### `paper`

```python
def paper(doi, *, version=None) -> Paper | None
```

The paper of `doi` in the paper cache, at `version` where evidence gives one; `None` where it
isn't there.

### `add_paper`

```python
def add_paper(doi, *, version=None, pdf=None) -> Paper
```

Puts the paper of `doi` in the cache, and returns it. With `pdf`, the PDF at that path is kept.
With none, an arXiv DOI (`10.48550/arXiv.<id>`) is downloaded from arXiv, at `version` where
one is given; no other paper is downloaded. A paper already in the cache is returned as it is.

Raises [`PaperError`](#errors) where no PDF can be got or the file isn't a PDF, and `OSError`
where `pdf` can't be read.

### `verify_quote`

```python
def verify_quote(doi, quote, *, version=None, location=None) -> QuoteStatus
```

Whether `quote`, a [`TextQuoteSelector`](data-model.md#textquoteselector), is in the cached
paper of `doi`. With `location`, a [`FragmentSelector`](data-model.md#fragmentselector) that
gives a page of a PDF (`page=6`), the quote is to be on that page. The arguments are the fields
of an [`Evidence`](data-model.md#evidence), so one from a resolved analysis passes straight in:

```python
for each in analysis.analyses:
    for insight in each.prior_insights:
        for evidence in insight.evidence:
            if evidence.doi and evidence.quote:
                status = api.verify_quote(
                    evidence.doi,
                    evidence.quote,
                    version=evidence.version,
                    location=evidence.location,
                )
                print(insight.ref, status.state, status.page)
```

The match allows for what extracting a PDF's text changes, and a quote's `prefix` or `suffix`
tells one passage from another like it. A paper that isn't in the cache is a state of the
status, `no_paper`, not an error.

Raises [`PaperError`](#errors) where the PDF's text can't be read.

## Errors

| Error | Raised where |
|---|---|
| `NoAnalysisError` | A folder holds no `astra.yaml` |
| `InvalidAnalysisError` | The analysis breaks a `MUST`, so it has no resolved analysis and no statuses. Its `report` attribute is the [`ValidationReport`](data-model.md#validationreport) |
| `RequestError` | What is asked for isn't there: a revision that names no commit. It is a `ValueError` |
| `GitError` | git can't be run |
| `CacheError` | The cache can't be used where the environment puts it |
| `PaperError` | A paper can't be put in the cache, or its PDF's text can't be read |

## A runner, in brief

This is the least a runner does with the API: ask once, build what isn't `unchanged` in the
order the results come in, and record each. It leaves out what the specification's runner rules
ask for, such as building only from a committed tree.

```python
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from astra import api


def digest(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return f"sha256:{hashlib.sha256(data).hexdigest()}", len(data)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


folder = Path(".")
report = api.check(folder)
analysis = report.analysis
analyses = {each.key: each for each in analysis.analyses}
inputs = {each.ref: each for one in analysis.analyses for each in one.inputs}
results = {each.id: each for each in analysis.results}
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True, text=True, check=True
).stdout.strip()

for result in analysis.results:  # each comes after every result it reads
    if report.statuses[result.id].state == "unchanged" or result.command is None:
        continue
    # What each entry reads: an input's file, or another result's bytes.
    read = []
    for source in result.inputs:
        if source.input is not None:
            path = inputs[source.input].path
        else:
            path = results[source.result].places[0].bytes_path
        read.append(api.RecordedInput(source.entry, *digest(folder / path)))
    # The recipe runs in the folder of the analysis its output belongs to.
    owner = analyses[".".join(result.output.split(".")[:-2])]
    started = now()
    subprocess.run(result.command, shell=True, cwd=folder / owner.folder, check=True)
    generation = api.Generation(
        commit=commit,
        environment=api.Environment("urn:example:python-3.13"),
        runner=api.Runner("example-runner", "0.1.0"),
        inputs=tuple(read),
        started=started,
        finished=now(),
    )
    api.write_records(folder, result, *digest(folder / result.places[0].bytes_path), generation)
```

After it, `astra check` reads the record back:

```console
$ astra check
fit#baseline  unchanged  present  .astra/records/baseline/fit.json
  made in urn:example:python-3.13 by example-runner 0.1.0
1 planned result(s), 1 unchanged, 0 stale, 0 missing; 0 absent
```
