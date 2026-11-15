# astra-tools

astra-tools is the validator, resolver and checker of [ASTRA](https://astra-spec.org/) 0.1
analyses. It comes as a command line, `astra`, and as a Python module, `astra.api`.

It answers three questions of an analysis, from its files and git alone:

| Question | Command | Function | Answer |
|---|---|---|---|
| Is it valid? | [`astra validate`](cli.md#astra-validate) | [`validate`](api.md#validate) | [`ValidationReport`](data-model.md#validationreport) |
| What does it mean? | [`astra info`](cli.md#astra-info), [`astra view`](cli.md#astra-view) | [`resolve`](api.md#resolve) | [`ResolvedAnalysis`](data-model.md#resolvedanalysis) |
| Do its results' records still hold? | [`astra status`](cli.md#astra-status) | [`status`](api.md#status) | [`StatusReport`](data-model.md#statusreport) |

Each answer is plain data that writes as JSON, and a command's `--json` prints exactly what the
function returns.

astra-tools runs no recipe. A runner, such as
[lightcone-cli](https://github.com/LightconeResearch/lightcone-cli), decides what to build, in
what order and where, builds it, and writes each result's record with
[`write_records`](api.md#write_records). The [specification](https://astra-spec.org/0.1/) says
what an analysis means and what each rule asks.

## Install

astra-tools needs Python 3.11 or later, and git, which it runs to read repositories.

```bash
uv tool install astra-tools   # or: pip install astra-tools
astra --version
```

While astra-tools for ASTRA 0.1 has only release candidates, uv and pip skip them. Ask for them
with `uv tool install --prerelease allow astra-tools`, or `pip install --pre astra-tools`.

To run it once without installing it, name the version:

```bash
uvx astra-tools@<version> validate
```

It reads ASTRA 0.1 files, those whose `spec_version` is `0.1.x`. Files written for ASTRA 0.0.x
need the 0.2 line of astra-tools (`astra-tools<0.3`).

## Where to look

| Page | What it holds |
|---|---|
| [CLI reference](cli.md) | Every `astra` command: its arguments, options, output and exit codes |
| [Python API](api.md) | The functions of `astra.api`, and what they raise |
| [Data model](data-model.md) | Every class the functions return, field by field, and how each writes as JSON |

## A first look

```console
$ astra init my-analysis
✓ created astra.yaml
✓ created .gitignore
✓ created .git
✓ Converged ASTRA analysis scaffold: my-analysis
$ astra validate my-analysis
astra.yaml: valid, 0 error(s), 0 warning(s)
```

The same from Python:

```python
from astra import api

report = api.validate("my-analysis")
assert report.valid
analysis = api.resolve("my-analysis")
```
