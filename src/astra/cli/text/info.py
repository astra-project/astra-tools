"""An analysis in brief, as text: its label and description, then its inputs, outputs,
decisions and universes, or only the parts asked for; and, after it, each other analysis of
its stack, the same way."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from astra._internal.analysis.stack import Identity, Member, Stack
from astra._internal.documents import document
from astra.cli.text import console, file_named


def show(stack: Stack, only: set[str] | None = None) -> None:
    """Each analysis of `stack`, the root first, with every part, or only the parts `only`
    names."""
    out = console()
    names = _names(stack)
    for member in stack.analyses.values():
        root = member.identity == stack.root
        if not root:
            file = file_named(stack.location(member.identity, ()))
            out.print()
            out.print(
                f"[bold magenta]Analysis: {escape(names[member.identity])}[/bold magenta]"
                f"  [dim]{escape(file)}[/dim]"
            )
        if member.analysis is None:
            out.print("  not a valid document: `astra validate` says why")
            continue
        _analysis(out, member, member.analysis, only, _layout(member) if root else "")


def _names(stack: Stack) -> dict[Identity, str]:
    """Each analysis of the stack but the root, with the address it is first reached by from
    the root: the ids of the declarations that lead to it, joined by `.`."""
    names: dict[Identity, str] = {}
    reached = [(stack.root, "")]
    while reached:
        owner, prefix = reached.pop(0)
        for id_, declaration in stack.analyses[owner].declarations.items():
            target = declaration.reached
            if target is None or target == stack.root or target in names:
                continue
            names[target] = f"{prefix}{id_}"
            reached.append((target, f"{prefix}{id_}."))
    return names


def _analysis(
    out: Console, member: Member, analysis: document.Analysis, only: set[str] | None, layout: str
) -> None:
    """One analysis: its label, description and counts, then its parts."""
    out.print(f"[bold]{escape(analysis.label or 'Unknown')}[/bold]")
    out.print(f"Spec version: {escape(analysis.spec_version)}")
    if analysis.description and analysis.description.strip():
        out.print()
        out.print(escape(analysis.description.strip()))
    out.print(
        f"\n[dim]Inputs: {len(analysis.inputs)} | Outputs: {len(analysis.outputs)} | "
        f"Decisions: {len(analysis.decisions)} | Universes: {len(analysis.universes)}[/dim]"
    )
    if layout:
        out.print(f"[dim]Layout: {escape(layout)}[/dim]")

    def asked(part: str) -> bool:
        return only is None or part in only

    if asked("inputs"):
        out.print("\n[bold]Inputs:[/bold]")
        table = Table(show_header=True)
        for column in ("ID", "Path", "Description"):
            table.add_column(column)
        for id_, input_ in analysis.inputs.items():
            table.add_row(id_, escape(input_.path), escape(input_.description or ""))
        out.print(table)
    if asked("outputs"):
        out.print("\n[bold]Outputs:[/bold]")
        table = Table(show_header=True)
        for column in ("ID", "Type", "Recipe", "Description"):
            table.add_column(column)
        for id_, output in analysis.outputs.items():
            table.add_row(id_, *_output(output), escape(output.description or ""))
        out.print(table)
    if asked("decisions"):
        out.print("\n[bold]Decisions:[/bold]")
        _decisions(out, analysis)
    if only is None and analysis.universes:
        out.print("\n[bold]Universes:[/bold]")
        for id_, universe in analysis.universes.items():
            out.print(f"  [cyan]{id_}[/cyan]{escape(_universe(universe))}")


def _layout(member: Member) -> str:
    """One line on the analyses the root declares, with the folders of those in its tree."""
    declarations = member.declarations
    if not declarations:
        return ""
    folders = sorted(
        f"./{declaration.folder}/"
        for declaration in declarations.values()
        if declaration.declared.path is not None and declaration.folder
    )
    noun = "sub-analysis" if len(declarations) == 1 else "sub-analyses"
    if len(folders) == len(declarations):
        return f"{len(declarations)} {noun} in {', '.join(folders)}"
    if folders:
        return f"{len(declarations)} {noun} ({len(folders)} in {', '.join(folders)})"
    return f"{len(declarations)} {noun}"


def _output(output: document.Output) -> tuple[str, str]:
    """An output's type and its recipe's command; a switch's decision and cases."""
    if output.is_switch:
        cases = ", ".join(f"{option}: {target}" for option, target in output.cases.items())
        return "switch", escape(f"on {output.switch} ({cases})")
    command = "[dim]-[/dim]" if output.recipe is None else escape(output.recipe.command)
    return escape(output.type or ""), command


def _universe(universe: document.Universe) -> str:
    if universe.is_import:
        return f": imports {universe.analysis}.{universe.universe}"
    if universe.derived_from is not None:
        return f": derived from {universe.derived_from}"
    return ""


def _decisions(out: Console, analysis: document.Analysis) -> None:
    """Each decision of `analysis`, as a tree of its rationale and options."""
    for id_, decision in analysis.decisions.items():
        tree = Tree(f"[cyan]{id_}[/cyan]: {escape(decision.label or '')}")
        if decision.tags:
            tree.add(f"[dim]Tags:[/dim] {escape(', '.join(decision.tags))}")
        if decision.rationale:
            tree.add(f"[dim]Rationale:[/dim] {escape(decision.rationale)}")
        options = tree.add("[dim]Options:[/dim]")
        for option_id, option in decision.options.items():
            text = f"{option_id}: {escape(option.label or '')}"
            if option.excluded is not None:
                text += f" [yellow](excluded: {escape(option.excluded)})[/yellow]"
            if option.description:
                text += f" - [dim]{escape(option.description)}[/dim]"
            options.add(text)
        out.print(tree)
        out.print()
