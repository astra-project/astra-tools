"""An analysis in brief, as text, from its resolved model: its label and description, then its
inputs, outputs, decisions and universes, or only the parts asked for; and, after it, each
other analysis of its stack, the same way."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from astra.cli.text import console
from astra.model.resolved_analysis import Analysis, ResolvedAnalysis


def show(resolved: ResolvedAnalysis, only: set[str] | None = None) -> None:
    """Each analysis of `resolved`, the driving one first, with every part, or only the parts
    `only` names."""
    out = console()
    driving, *others = resolved.analyses
    out.print(f"[bold]{escape(driving.label or 'Unknown')}[/bold]")
    out.print(f"Spec version: {escape(resolved.spec_version)}")
    _analysis(out, driving, only, (_layout(resolved), f"Planned results: {len(resolved.results)}"))
    for each in others:
        out.print()
        out.print(
            f"[bold magenta]Analysis: {escape(each.key)}[/bold magenta]"
            f"  [dim]{escape(_file(each))}[/dim]"
        )
        if each.label:
            out.print(f"[bold]{escape(each.label)}[/bold]")
        _analysis(out, each, only)


def _file(analysis: Analysis) -> str:
    """An analysis's `astra.yaml` and, for one read at a commit, the commit and the repository
    it came from."""
    file = "astra.yaml" if analysis.folder == "." else f"{analysis.folder}/astra.yaml"
    if analysis.commit is None:
        return file
    source = analysis.commit.repository
    return f"{file} at {analysis.commit.id}" + ("" if source is None else f" from {source}")


def _layout(resolved: ResolvedAnalysis) -> str:
    """One line on the analyses the driving one declares, with the folders of those read in its
    working tree."""
    driving, by_key = resolved.analyses[0], {each.key: each for each in resolved.analyses}
    declared = [by_key[key] for key in driving.declares.values()]
    if not declared:
        return ""
    folders = sorted(f"{each.folder}/" for each in declared if each.commit is None)
    noun = "sub-analysis" if len(declared) == 1 else "sub-analyses"
    if len(folders) == len(declared):
        return f"Layout: {len(declared)} {noun} in {', '.join(folders)}"
    if folders:
        return f"Layout: {len(declared)} {noun} ({len(folders)} in {', '.join(folders)})"
    return f"Layout: {len(declared)} {noun}"


def _id(ref: str) -> str:
    """The id a ref ends with."""
    return ref.rpartition(".")[2]


def _analysis(
    out: Console, analysis: Analysis, only: set[str] | None, more: tuple[str, ...] = ()
) -> None:
    """One analysis: its description and counts, with the lines of `more` after them, then its
    parts."""
    if analysis.description and analysis.description.strip():
        out.print()
        out.print(escape(analysis.description.strip()))
    out.print(
        f"\n[dim]Inputs: {len(analysis.inputs)} | Outputs: {len(analysis.outputs)} | "
        f"Decisions: {len(analysis.decisions)} | Universes: {len(analysis.universes)}[/dim]"
    )
    for line in more:
        if line:
            out.print(f"[dim]{escape(line)}[/dim]")

    def asked(part: str) -> bool:
        return only is None or part in only

    if asked("inputs"):
        out.print("\n[bold]Inputs:[/bold]")
        table = Table(show_header=True)
        for column in ("ID", "Path", "Description"):
            table.add_column(column)
        for input_ in analysis.inputs:
            table.add_row(_id(input_.ref), escape(input_.path), escape(input_.description or ""))
        out.print(table)
    if asked("outputs"):
        out.print("\n[bold]Outputs:[/bold]")
        table = Table(show_header=True)
        for column in ("ID", "Type", "Format", "Description"):
            table.add_column(column)
        for output in analysis.outputs:
            table.add_row(
                _id(output.ref), output.type, output.format, escape(output.description or "")
            )
        out.print(table)
    if asked("decisions"):
        out.print("\n[bold]Decisions:[/bold]")
        _decisions(out, analysis)
    if only is None and analysis.universes:
        out.print("\n[bold]Universes:[/bold]")
        for universe in analysis.universes:
            selected = ", ".join(f"{d} = {option}" for d, option in universe.selection.items())
            line = f"  [cyan]{_id(universe.ref)}[/cyan]"
            out.print(line + escape(f": {selected}") if selected else line)


def _decisions(out: Console, analysis: Analysis) -> None:
    """Each decision of `analysis`, as a tree of its rationale and options."""
    for decision in analysis.decisions:
        tree = Tree(f"[cyan]{_id(decision.ref)}[/cyan]: {escape(decision.label or '')}")
        if decision.tags:
            tree.add(f"[dim]Tags:[/dim] {escape(', '.join(decision.tags))}")
        if decision.rationale:
            tree.add(f"[dim]Rationale:[/dim] {escape(decision.rationale)}")
        options = tree.add("[dim]Options:[/dim]")
        for option in decision.options:
            text = f"{option.id}: {escape(option.label or '')}"
            if option.excluded is not None:
                text += f" [yellow](excluded: {escape(option.excluded)})[/yellow]"
            if option.description:
                text += f" - [dim]{escape(option.description)}[/dim]"
            options.add(text)
        out.print(tree)
        out.print()
