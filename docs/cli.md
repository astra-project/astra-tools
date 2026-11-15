# CLI reference

`astra` validates ASTRA analyses, shows what they mean, and checks what was built against its
records. It runs no recipe: a runner builds the results and writes their records, and `astra`
reads them.

## Conventions

- **PATH** is an analysis's folder, the current folder by default. Nothing is searched for: the
  analysis is the `astra.yaml` in that folder. `astra validate` and `astra info` name the
  analysis another way, each described below.
- **A valid analysis.** `info`, `view`, `status` and `history` answer only for an analysis that
  breaks no `MUST`. For one that does, they print what `astra validate` prints, and exit 1.
- **Exit codes:**
    - 0 when the command answers;
    - 1 when the analysis breaks a `MUST`, a planned result isn't `unchanged`, or what was asked
      for isn't there (no analysis, nothing in git, a paper or a quote);
    - 2 for a usage error, an analysis that can't be read, a broken environment (git or the
      cache unusable, a folder that can't be written), or an internal error.
- **Diagnostics** are grouped by file, one per line, as `line:col level CODE message`. A code
  is a rule of the specification, listed under
  [Rules](https://astra-spec.org/0.1/specification/#rules), or one of astra-tools' own. The
  level is `error` for a `MUST` broken and `warning` for a `SHOULD`.
- **JSON.** `validate`, `info` and `status` take `--json`, and print the
  [data model](data-model.md) as it writes: `validate` a
  [`ValidationReport`](data-model.md#validationreport), `info` a
  [`ResolvedAnalysis`](data-model.md#resolvedanalysis), and `status` a
  [`StatusReport`](data-model.md#statusreport). The paper commands that verify quotes print
  [`QuoteStatus`](data-model.md#quotestatus). The exit code is the same with and without
  `--json`.
- **Colour** is left out where `NO_COLOR` is set, or where the output isn't a terminal.
- **The cache** keeps the commits fetched from remotes, the validity of analyses read at a
  commit, the hashes of files, and papers. It sits outside every repository:
  `$XDG_CACHE_HOME/astra` or `~/.cache/astra` on Linux, `~/Library/Caches/astra` on macOS.
  `ASTRA_CACHE_DIR`, an absolute path, moves it.
- `astra --help`, and `--help` after any command, give each command's options.
  `astra --version` gives astra-tools' version. `ASTRA_DEBUG=1` prints the traceback of an
  internal error.

The examples come from one small analysis:

```yaml
spec_version: "0.1.0"
label: Example
inputs:
  catalog: {path: data/catalog.csv}
decisions:
  method:
    options: {ols: {}, robust: {}}
outputs:
  fit:
    type: metric
    format: json
    inputs: [catalog]
    decisions: [method]
    recipe:
      command: python fit.py {inputs.catalog} {decisions.method} {output}
universes:
  baseline:
    decisions: {method: ols}
```

## Commands at a glance

| Command | What it does |
|---|---|
| [`astra init`](#astra-init) | Make a minimal analysis, or complete one |
| [`astra validate`](#astra-validate) | Validate an analysis and its whole stack |
| [`astra info`](#astra-info) | Show an analysis in brief |
| [`astra view`](#astra-view) | Show the analysis as it is in one universe |
| [`astra status`](#astra-status) | Check the records and bytes of the planned results |
| [`astra history`](#astra-history) | Show what git holds of a result's records over time |
| [`astra spec`](#astra-spec) | Describe the fields of ASTRA files |
| [`astra schema`](#astra-schema) | Show or export the LinkML schemas |
| [`astra guide`](#astra-guide) | Print the guide for agents |
| [`astra paper`](#astra-paper) | Keep cited papers, and verify quotes in them |

## `astra init`

```text
astra init [DIRECTORY] [--check] [--json]
```

Converges DIRECTORY, the current folder by default, into a minimal analysis. It creates
whatever is missing and never writes over a file: an `astra.yaml` with a `spec_version` and a
label, a `.gitignore`, and a git repository where none holds DIRECTORY already. A folder that
has an `astra.yaml` or other files is adopted, not refused, so it is safe to run again.

| Option | Meaning |
|---|---|
| `--check` | Write nothing: report what would be created, and exit 1 where something would |
| `--json` | Print the report as JSON: `converged`, and the names `created`, `repaired`, `unchanged`, and `warnings` |

```console
$ astra init my-analysis
✓ created astra.yaml
✓ created .gitignore
✓ created .git
✓ Converged ASTRA analysis scaffold: my-analysis
$ cat my-analysis/astra.yaml
# ASTRA Analysis Specification

spec_version: "0.1.0"
label: "my-analysis"
```

## `astra validate`

```text
astra validate [FILE] [-e | --verify-evidence] [--skip-evidence] [--json] [--offline]
```

Checks every parse, schema and validator rule over the whole stack: the analysis and every
analysis it declares, each at its commit. It reads no results; `astra status` does. Exits 0 when
every analysis is valid and 1 when one breaks a `MUST`. A `SHOULD` that is broken is a warning,
and doesn't change the exit code.

FILE is an analysis's `astra.yaml`, or its folder. With no FILE, every root analysis under the
current folder is validated: each `astra.yaml` that no other one declares. Hidden folders,
`node_modules`, `venv`, `__pycache__` and `results` aren't searched.

| Option | Meaning |
|---|---|
| `-e`, `--verify-evidence` | Also seek each quote of the analysis's evidence in the paper it cites, which must be in the paper cache ([`astra paper add`](#astra-paper)) |
| `--skip-evidence` | Verify no evidence, and don't suggest it |
| `--json` | Print the [`ValidationReport`](data-model.md#validationreport) as JSON: for FILE, the one report; with no FILE, a list of them, one for each root analysis |
| `--offline` | Fetch nothing: use only the commits fetched before |

An analysis declared by `url` and `commit` is fetched into the cache, once.

Here the universe `baseline` has been edited to select `lasso`:

```console
$ astra validate
astra.yaml
  18:25 error UNKNOWN_OPTION `method` has no option `lasso`: its options are `ols`, `robust`
astra.yaml: invalid, 1 error(s), 0 warning(s)

1/1 file(s) failed validation: astra.yaml
$ astra validate astra.yaml --json
{
  "root": "astra.yaml",
  "valid": false,
  "diagnostics": [
    {
      "code": "UNKNOWN_OPTION",
      "level": "error",
      "message": "`method` has no option `lasso`: its options are `ols`, `robust`",
      "location": {
        "file": "astra.yaml",
        "pointer": "/universes/baseline/decisions/method",
        "line": 18,
        "column": 25
      },
      "related": []
    }
  ],
  "unchecked": []
}
```

With `--verify-evidence`, a quote that isn't verified is an error of the report, at its place
in `astra.yaml`, under one of three codes of astra-tools' own:

| Code | Meaning |
|---|---|
| `EVIDENCE_PAPER_MISSING` | The paper the evidence cites isn't in the paper cache |
| `EVIDENCE_PAPER_UNREADABLE` | The paper is in the cache, and its text can't be read |
| `EVIDENCE_QUOTE_NOT_FOUND` | The quote isn't in the paper, or isn't on the page its `location` gives (`page=6`) |

Evidence that cites an output has no paper to seek a quote in, and is counted as skipped.

## `astra info`

```text
astra info [-f FILE | --file FILE] [-d] [-i] [-o] [--json]
```

Shows the analysis in brief: its label and description, how many inputs, outputs, decisions,
universes and planned results it has, then its inputs, outputs, decisions and universes, each
universe with the option it selects for each decision it uses. Each other analysis of the stack
follows, the same way, under its key and its file.

The analysis is the `astra.yaml` in the current folder or the nearest folder above it that has
one; `--file` names it instead, by its `astra.yaml` or its folder. Exits 1 where there is no
analysis, or it breaks a `MUST`.

| Option | Meaning |
|---|---|
| `-f`, `--file FILE` | The analysis's `astra.yaml`, or its folder |
| `-d`, `--decisions` | Show only the decisions |
| `-i`, `--inputs` | Show only the inputs |
| `-o`, `--outputs` | Show only the outputs |
| `--json` | Print the [`ResolvedAnalysis`](data-model.md#resolvedanalysis) as JSON |

`-d`, `-i` and `-o` combine: `-d -i` shows the decisions and the inputs.

```console
$ astra info
Example
Spec version: 0.1.0

Inputs: 1 | Outputs: 1 | Decisions: 1 | Universes: 1
Planned results: 1

Inputs:
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ ID      ┃ Path             ┃ Description ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ catalog │ data/catalog.csv │             │
└─────────┴──────────────────┴─────────────┘

Outputs:
┏━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┓
┃ ID  ┃ Type   ┃ Format ┃ Description ┃
┡━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━┩
│ fit │ metric │ json   │             │
└─────┴────────┴────────┴─────────────┘

Decisions:
method:
└── Options:
    ├── ols:
    └── robust:


Universes:
  baseline: decisions.method = ols
```

## `astra view`

```text
astra view UNIVERSE [PATH]
```

Shows the analysis as it is in UNIVERSE, one of its universes: the option the universe selects
for each decision it uses, then each result planned in it, with its id, where its bytes go, what
each entry of its output's `inputs` reads there, through any switch, and its command as it runs.
Exits 2 where the analysis has no universe UNIVERSE.

```console
$ astra view baseline
universe baseline
  decisions.method = ols
fit#baseline  results/baseline/fit.json
  catalog reads inputs.catalog
  $ python fit.py data/catalog.csv ols results/baseline/fit.json
```

## `astra status`

```text
astra status [PATH] [--at REV] [--json]
```

Shows how each planned result stands, by the specification's check rules. For each one it
checks the record and the bytes:

- the record is `unchanged`, `stale` (something the result is made from has changed since the
  commit the record names) or `missing`;
- the bytes are `present` (the ones the record gives, at the result's place) or `absent`.

Each result is shown with its state, its bytes' and where its record goes, and under it each
rule it breaks. Then each evidence that cites an output gets the status of what it cites. Exits
0 when every planned result and evidence is `unchanged`, and 1 otherwise.

| Option | Meaning |
|---|---|
| `--at REV` | Check the analysis as it is at the commit REV names (a commit, a branch, a tag), with its records and bytes there. Exits 2 where REV names no commit |
| `--json` | Print the [`StatusReport`](data-model.md#statusreport) as JSON, which holds the resolved analysis too |

```console
$ astra status
fit#baseline  missing  absent  .astra/records/baseline/fit.json
  error MISSING_RECORD no record is at .astra/records/baseline/fit.json: build `fit#baseline`, and record it there
1 planned result(s), 0 unchanged, 0 stale, 1 missing; 1 absent
```

An input whose content is kept outside git, behind a stand-in, is compared by the hash the
stand-in gives. astra-tools recognises Git LFS pointers, git-annex links and DVC files, and
fetches none of them.

## `astra history`

```text
astra history timeline ADDR [PATH]
astra history lineage ADDR [PATH] [--used-by]
astra history find (--hash H | --environment IRI) [PATH]
astra history get ADDR@REV [PATH]
```

Reads a result's records over time, from git. ADDR is a result's address, as its record gives it
(`fit#baseline`, `summary`); `astra status` lists them. A record's versions are its file at each
commit along HEAD's history that changed it, in the repository that holds the analysis the
result belongs to. Exits 1 where what is asked for isn't in git, and 2 where ADDR names no
planned result or REV names no commit.

| Command | What it shows |
|---|---|
| `timeline ADDR` | Each version of the result's record, newest first: the commit that changed it, and the hash, size, commit, end and environment it gives |
| `lineage ADDR` | What the result was made from, as its record at HEAD gives it, down to the input files. With `--used-by`, the planned results whose records at HEAD list it instead |
| `find` | The versions of planned results' records whose bytes have the hash `--hash` gives (`sha256:<hex>`), or whose environment is the IRI `--environment` gives |
| `get ADDR@REV` | The bytes the result had at the commit REV names (a commit, a branch, a tag), checked against its record there, written to standard output |

## `astra spec`

```text
astra spec [TERM] [--full]
```

Describes the fields of ASTRA files, from the specification's LinkML schema. Without TERM, it
prints a summary of the concepts. With TERM, in any case, it prints that entry. `--full` prints
every entry, which is long.

## `astra schema`

```text
astra schema show (analysis | insights | provenance | types)
astra schema export [-o DIR | --output DIR]
```

The LinkML schemas of ASTRA files, as astra-spec ships them. `show` prints one to standard
output. `export` writes them all into DIR, `schemas/` by default.

## `astra guide`

```text
astra guide
```

Prints astra-spec's guide for agents, `llms.txt`, unchanged.

## `astra paper`

```text
astra paper add DOI [-v N | --version N] [--pdf FILE]
astra paper list
astra paper show DOI [-v N]
astra paper path DOI [-v N]
astra paper remove DOI [-v N]
astra paper fetch-metadata [DOI] [-v N] [--all]
astra paper verify-quote DOI (-q TEXT | --quote TEXT) [-v N] [-p N | --page N] [--json]
astra paper verify-quotes DOI [-v N]
```

Keeps the papers that evidence cites by DOI in the paper cache, and seeks quotes in them. A
paper is kept under its DOI as given, and its version where one is given: `-v 7` and no version
are two papers.

| Command | What it does |
|---|---|
| `add DOI` | Keeps the paper of DOI. An arXiv DOI (`10.48550/arXiv.<id>`) is downloaded from arXiv, at `--version` where given. No other paper is downloaded: `--pdf` keeps a PDF you have. A paper already kept is left as it is. Exits 1 where the paper can't be got |
| `list` | Lists the papers in the cache |
| `show DOI` | Shows a paper's title, authors, hash, source and path. Exits 1 where it isn't in the cache |
| `path DOI` | Prints the path of the paper's PDF, and nothing else. Exits 1 where it isn't in the cache |
| `remove DOI` | Removes the paper from the cache. Exits 1 where it isn't there |
| `fetch-metadata [DOI]` | Fetches the title and authors of a kept paper from doi.org; with `--all`, of every kept paper that lacks them |
| `verify-quote DOI` | Seeks one quote in the paper |
| `verify-quotes DOI` | Seeks several quotes in the paper, read from standard input |

### Verifying quotes

A quote is sought in the text of the paper's PDF. The match allows for what extracting a PDF's
text changes: line breaks, ligatures, a character read wrong. Each quote gets a
[`QuoteStatus`](data-model.md#quotestatus):

| `state` | Meaning |
|---|---|
| `found` | The quote is in the paper, on `page` |
| `elsewhere` | The quote is in the paper on `page`, and not on the page it was said to be on |
| `not_found` | The quote isn't in the paper |
| `no_paper` | The paper isn't in the cache |

Both commands exit 0 when every quote is `found`, 1 otherwise, and 2 where the paper's text
can't be read.

`verify-quote` takes the quote as `--quote`, and with `--page` the page it is to be on.
`--json` prints its status.

```console
$ astra paper add 10.9999/example --pdf paper.pdf
$ astra paper verify-quote 10.9999/example -q "reduce the influence of outliers" -p 2
✓ Found on page 2
$ astra paper verify-quote 10.9999/example -q "reduce the influence of outliers" -p 1 --json
{
  "state": "elsewhere",
  "page": 2
}
```

`verify-quotes` reads a JSON list from standard input, an item for each quote. An item has the
`quote` of an evidence item and, where it has one, its `location`, as `astra.yaml` writes them:

```json
[
  {"quote": {"exact": "reduce the influence of outliers"}, "location": {"value": "page=2"}},
  {"quote": {"exact": "a sentence the paper never says anywhere", "prefix": "and then "}}
]
```

It prints a JSON list of each quote's status, in the same order:

```json
[
  {
    "state": "found",
    "page": 2
  },
  {
    "state": "not_found"
  }
]
```

It exits 2, and prints nothing, where the input isn't such a list.
