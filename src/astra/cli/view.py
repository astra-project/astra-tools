"""`astra view U [PATH]`: the analysis as it is in one of its universes."""

from __future__ import annotations

from pathlib import Path

import click

from astra.cli import FAILED, environment, write_report


@click.command("view")
@click.argument("universe")
@click.argument("path", required=False, type=click.Path(file_okay=False, path_type=Path))
def command(universe: str, path: Path | None) -> None:
    """Show the analysis in PATH as it is in UNIVERSE, one of its universes.

    PATH is the analysis's folder, the current one by default. The option UNIVERSE selects for
    each decision it uses is shown, then each result planned in it: its id, where its bytes go,
    what each entry of its output's inputs reads there, through any switch, and its command as
    it runs. Exits 1 where the analysis breaks a MUST, which is shown as `astra validate` shows
    it, and 2 where it can't be read or has no universe UNIVERSE.
    """
    from astra import api

    with environment():
        try:
            analysis = api.resolve(path)
        except api.InvalidAnalysisError as error:
            write_report(error.report, False)
            raise click.exceptions.Exit(FAILED) from None
    own = {each.ref.rpartition(".")[2]: each for each in analysis.analyses[0].universes}
    if universe not in own:
        raise click.BadParameter(
            f"the analysis has no universe `{universe}`: its universes are "
            f"{', '.join(own) or 'none'}",
            param_hint="UNIVERSE",
        )
    from astra.cli.text.view import show

    show(analysis, own[universe])
