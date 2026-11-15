"""`astra status [PATH] [--at REV] [--json]`: each planned result's status, and the
evidence's."""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli import FAILED, environment, write_json, write_report


@click.command("status")
@click.argument("path", required=False, type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--at",
    "at",
    metavar="REV",
    help="Check the analysis as it is at the commit REV names, with its records and bytes there.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def command(path: Path | None, at: str | None, as_json: bool) -> None:
    """Check the records and bytes of the planned results of the analysis in PATH.

    PATH is the analysis's folder, the current one by default. Each planned result is shown
    with its record's status, unchanged, stale or missing, and its bytes', present or absent,
    and why; then each evidence with the status of what it cites. With --json, the report holds
    the analysis as it resolved too. Exits 0 when every planned result and evidence is
    unchanged, 1 when one isn't or the analysis breaks a MUST, which is shown as
    `astra validate` shows it, and 2 where it can't be read or REV names no commit.
    """
    from astra import api

    with environment():
        try:
            report = api.status(path, at=at)
        except api.InvalidAnalysisError as error:
            write_report(error.report, as_json)
            raise click.exceptions.Exit(FAILED) from None
        except api.RequestError as error:
            raise click.BadParameter(str(error), param_hint="--at") from None
    if as_json:
        write_json(report.to_json())
    else:
        from astra.cli.text.status import show

        show(report)
    states = [status.state for status in report.statuses.values()]
    states += [evidence.state for evidence in report.evidence]
    if any(state != "unchanged" for state in states):
        raise click.exceptions.Exit(FAILED)
