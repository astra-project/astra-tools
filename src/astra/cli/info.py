"""`astra info [-f FILE] [-d] [-i] [-o] [--json]`: an analysis in brief."""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli import FAILED, environment, find_analysis, write_json, write_report


@click.command("info")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    help="Analysis file (default: astra.yaml in current/parent dir)",
)
@click.option("--decisions", "-d", is_flag=True, help="Show decision details")
@click.option("--inputs", "-i", is_flag=True, help="Show input details")
@click.option("--outputs", "-o", is_flag=True, help="Show output details")
@click.option("--json", "as_json", is_flag=True, help="Print the information as JSON.")
def command(file: Path | None, decisions: bool, inputs: bool, outputs: bool, as_json: bool) -> None:
    """Show information about an analysis.

    Its label and description, then its inputs, outputs, decisions and universes, each
    universe with the option it selects for each decision it uses; with -d, -i or -o, only
    the parts asked for. Each other analysis of its stack follows, the same way: the ones it
    declares, directly or not, in its working tree or at a commit. With --json, the analysis is
    printed as it resolves, as `astra.api.resolve` gives it.

    Only a valid analysis resolves: one that breaks a MUST is shown as `astra validate` shows
    it. Exits 1 where there is no analysis or it breaks a MUST, and 2 where it can't be read.
    """
    found = find_analysis() if file is None else file
    if found is None:
        click.echo("Error: No astra.yaml found in current directory or parents.", err=True)
        click.echo("Use --file to specify the analysis file.", err=True)
        raise click.exceptions.Exit(FAILED)
    from astra import api

    with environment():
        try:
            analysis = api.resolve(found if found.is_dir() else found.parent)
        except api.InvalidAnalysisError as error:
            write_report(error.report, as_json)
            raise click.exceptions.Exit(FAILED) from None
    if as_json:
        write_json(analysis.to_json())
        return
    asked = {
        name
        for name, wanted in (("decisions", decisions), ("inputs", inputs), ("outputs", outputs))
        if wanted
    }
    from astra.cli.text.info import show

    show(analysis, asked or None)
