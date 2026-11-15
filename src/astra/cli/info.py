"""`astra info [-f FILE] [-d] [-i] [-o] [--json]`: an analysis in brief."""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli import FAILED, environment, find_analysis, read_stack, write_json, write_report


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

    Its label and description, then its inputs, outputs, decisions and universes; with -d, -i
    or -o, only those asked for. Each other analysis of its stack follows, the same way: the
    ones it declares, directly or not, in its working tree or at a commit. It checks nothing:
    `astra validate` does. With --json, the analysis is printed as it resolves, as
    `astra.api.resolve` gives it: every analysis of the stack with what it declares, each
    universe's selection and the planned results. Only a valid analysis resolves: one that
    breaks a MUST is shown as `astra validate --json` shows it. Exits 1 where there is no
    analysis, no stack to show or, with --json, the analysis breaks a MUST.
    """
    found = find_analysis() if file is None else file
    if found is None:
        click.echo("Error: No astra.yaml found in current directory or parents.", err=True)
        click.echo("Use --file to specify the analysis file.", err=True)
        raise click.exceptions.Exit(FAILED)
    folder = found if found.is_dir() else found.parent
    if as_json:
        from astra import api

        with environment():
            try:
                write_json(api.resolve(folder).to_json())
            except api.InvalidAnalysisError as error:
                write_report(error.report, True)
                raise click.exceptions.Exit(FAILED) from None
        return
    stack = read_stack(folder)
    if stack is None:
        click.echo(
            "astra: the analysis's astra.yaml isn't a valid document, or isn't in a git "
            f"repository, so there is no stack to show: `astra validate {folder}` says why",
            err=True,
        )
        raise click.exceptions.Exit(FAILED)
    asked = {
        name
        for name, wanted in (("decisions", decisions), ("inputs", inputs), ("outputs", outputs))
        if wanted
    }
    from astra.cli.text.info import show

    show(stack, asked or None)
