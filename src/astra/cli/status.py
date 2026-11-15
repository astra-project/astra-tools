"""`astra status [PATH] [--json]`: each result's status, and the evidence's."""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli import FAILED, environment, write_json, write_report


@click.command("status")
@click.argument("path", required=False, type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def command(path: Path | None, as_json: bool) -> None:
    """Show how the results of the analysis in PATH stand.

    PATH is the analysis's folder, the current one by default. Each result is shown with its
    record's status, unchanged, stale or missing, and its bytes', present or absent, and why;
    then each evidence with the status of what it cites, and each input whose content isn't
    here. The records and bytes are those in the working tree.

    Bytes a large-file tool keeps are shown with the tool, and nothing is fetched. A result
    reads the same whether or not its own bytes are fetched, and so does one whose input isn't,
    with git-annex or Git LFS. An input kept by DVC must be pulled, or its results read stale.

    With --json, the report is printed as `astra.api.status` gives it. Exits 0 when every
    result and evidence is unchanged, 1 when one isn't or the analysis breaks a MUST, which is
    shown as `astra validate` shows it, and 2 where it can't be read.
    """
    from astra import api
    from astra._internal.analysis.resolve import read
    from astra._internal.results.status import status
    from astra._internal.sources.remote import Remotes

    # One reading gives both: the text names each result's record from the analysis.
    with environment():
        try:
            resolved = read(path, remotes := Remotes())
        except api.InvalidAnalysisError as error:
            write_report(error.report, as_json)
            raise click.exceptions.Exit(FAILED) from None
        report = status(resolved, remotes)
    if as_json:
        write_json(report.to_json())
    else:
        from astra.cli.text.status import show

        show(resolved.analysis, report)
    states = [each.state for each in report.statuses.values()]
    states += [evidence.state for evidence in report.evidence]
    if any(state != "unchanged" for state in states):
        raise click.exceptions.Exit(FAILED)
