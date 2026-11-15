"""An analysis in one of its universes, as text: the option the universe selects for each
decision it uses, then each result planned in it, with where its bytes go, what each entry of
its output's `inputs` reads and its command as it runs."""

from __future__ import annotations

from rich.text import Text

from astra.cli.text import console
from astra.model.resolved_analysis import ResolvedAnalysis, Universe


def show(analysis: ResolvedAnalysis, universe: Universe) -> None:
    out = console()
    out.print(Text(f"universe {universe.ref.rpartition('.')[2]}", style="bold"))
    for decision, option in universe.selection.items():
        out.print(f"  {decision} = {option}")
    for result in analysis.results:
        if result.universe != universe.ref:
            continue
        out.print(Text.assemble((result.id, "bold"), f"  {result.places[0].file_path}"))
        for source in result.inputs:
            out.print(f"  {source.entry} reads {source.input or source.result}")
        if result.command is not None:
            out.print(Text(f"  $ {result.command}", style="dim"))
