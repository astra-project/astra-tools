"""`astra validate [FILE] [-e|--verify-evidence] [--skip-evidence] [--json] [--offline]`: the
validator's report, for one analysis or every root analysis under the current folder."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from astra.cli import FAILED, environment, read_stack, write_json

if TYPE_CHECKING:
    from astra._internal.analysis.stack import Stack
    from astra._internal.documents.document import Insight
    from astra.model.diagnostic import Diagnostic

SKIPPED = frozenset({"node_modules", "venv", "__pycache__", "results"})
"""Folders the search for analyses doesn't enter, beside hidden ones: vendored code, and the
results an analysis makes."""


@click.command("validate")
@click.argument("file", required=False, type=click.Path(exists=True, path_type=Path))
@click.option(
    "-e",
    "--verify-evidence",
    is_flag=True,
    help="Verify evidence quotes (in prior_insights and findings) exist in source papers "
    "(requires papers to be cached)",
)
@click.option(
    "--skip-evidence",
    is_flag=True,
    help="Skip evidence verification even if prior insights or findings are present",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
@click.option("--offline", is_flag=True, help="Fetch nothing: use only the commits fetched before.")
def command(
    file: Path | None, verify_evidence: bool, skip_evidence: bool, as_json: bool, offline: bool
) -> None:
    """Validate an ASTRA analysis, or the whole project.

    FILE is an analysis's astra.yaml, or its folder; each analysis it declares is validated
    with it. With no FILE, every root analysis under the current directory is validated: each
    astra.yaml no other one declares; hidden, vendored and results directories are skipped.
    Analyses from another repository are fetched into the cache, once each; with --offline,
    nothing is fetched.

    Evidence verification (--verify-evidence) checks that quotes in prior_insights and
    findings actually exist in the source papers, as `astra paper verify-quote` checks one.
    Papers must be cached first using 'astra paper add'. Evidence that cites an output, or
    has no quote, is reported as skipped.

    A quote that isn't verified is an error of the report, as a broken rule is, at its place
    in astra.yaml: EVIDENCE_PAPER_MISSING where its paper isn't in the cache,
    EVIDENCE_PAPER_UNREADABLE where the paper can't be read, and EVIDENCE_QUOTE_NOT_FOUND
    where the quote isn't in the paper, or isn't on the page its location gives (`page=6`).

    With --json, the report is printed as JSON, as `astra.api.validate` gives it: its root,
    whether it is valid, and its diagnostics. For FILE it is the one report; with no FILE, a
    list of them, one for each root analysis. The exit code is unchanged: 0 when every analysis
    is valid, 1 when one breaks a MUST or a quote isn't verified, and 2 when one can't be
    validated.
    """
    options = (verify_evidence and not skip_evidence, skip_evidence, as_json, offline)
    if file is not None:
        valid, document = _validate_one(_folder(file), *options)
        if as_json:
            write_json(document)
        if not valid:
            raise click.exceptions.Exit(FAILED)
        return
    top = Path.cwd()
    roots = _roots(top)
    if not roots:
        click.echo("Error: No astra.yaml found here.", err=as_json)
        raise click.exceptions.Exit(FAILED)
    failed: list[str] = []
    documents: list[dict[str, Any]] = []
    for index, folder in enumerate(roots):
        if index and not as_json:
            click.echo()
        valid, document = _validate_one(folder, *options)
        documents.append(document)
        if not valid:
            failed.append(str((folder / "astra.yaml").relative_to(top.resolve())))
    if as_json:
        write_json(documents)
    elif failed:
        click.echo()
        click.echo(f"{len(failed)}/{len(roots)} file(s) failed validation: {', '.join(failed)}")
    else:
        click.echo()
        click.echo(f"All {len(roots)} file(s) passed validation.")
    if failed:
        raise click.exceptions.Exit(FAILED)


def _folder(file: Path) -> Path:
    """The folder of the analysis FILE names: FILE itself, or the folder of its astra.yaml."""
    if file.is_dir():
        return file
    if file.name == "astra.yaml":
        return file.parent
    raise click.BadParameter(
        f"{file} is neither an astra.yaml nor a folder: universes are in astra.yaml since "
        "ASTRA 0.1, so there is no universe file to validate",
        param_hint="FILE",
    )


def _validate_one(
    folder: Path, verify_evidence: bool, skip_evidence: bool, as_json: bool, offline: bool
) -> tuple[bool, dict[str, Any]]:
    """Validate the analysis in `folder`, and print its report unless `as_json`. With
    `verify_evidence`, the report holds the evidence's diagnostics too. Gives whether it is
    valid, and the report as JSON."""
    from astra._internal.analysis.validate import validated
    from astra._internal.sources.reader import worktree
    from astra._internal.sources.remote import Remotes

    with environment():
        report, context = validated(*worktree(folder), Remotes(offline=offline))
    stack = context.stack if context is not None and report.valid and not skip_evidence else None
    summary: list[str] = []
    if stack is not None and verify_evidence:
        found, summary = _verify(stack)
        # Each is an error, so a quote that isn't verified leaves the report invalid.
        report = replace(
            report,
            valid=report.valid and not found,
            diagnostics=(*report.diagnostics, *found),
        )
    if not as_json:
        from astra.cli.text.validate import show

        show(report)
        for line in summary:
            click.echo(line)
        if stack is not None and not verify_evidence:
            _suggest(_insights(stack))
    return report.valid, report.to_json()


def _insights(stack: Stack) -> dict[str, dict[str, Insight]]:
    """The prior insights and findings of the root of `stack`."""
    analysis = stack.analysis(stack.root)
    found = {"prior_insights": analysis.prior_insights, "findings": analysis.findings}
    return {label: dict(insights) for label, insights in found.items() if insights}


def _suggest(insights: dict[str, dict[str, Insight]]) -> None:
    """Where the analysis has evidence, say how to verify its quotes."""
    counts = {
        label: (len(found), sum(len(insight.evidence) for insight in found.values()))
        for label, found in insights.items()
    }
    prior, prior_evidence = counts.get("prior_insights", (0, 0))
    findings, finding_evidence = counts.get("findings", (0, 0))
    if prior_evidence + finding_evidence:
        click.echo(
            f"\nNote: {prior} prior insight(s) ({prior_evidence} evidence) and "
            f"{findings} finding(s) ({finding_evidence} evidence) found."
        )
        click.echo("Run with --verify-evidence to verify quotes exist in papers.")


def _verify(stack: Stack) -> tuple[list[Diagnostic], list[str]]:
    """Seek the quotes of the root's evidence in the cached papers, as `astra.api.verify_quote`
    does. Gives an error for each that isn't found, at its place in the root's file, as a
    validation error is given: `EVIDENCE_PAPER_MISSING` at the `doi` of one whose paper isn't
    in the cache, `EVIDENCE_PAPER_UNREADABLE` where the paper's text can't be read, and
    `EVIDENCE_QUOTE_NOT_FOUND` at a `quote` that isn't in its paper, or isn't on the page its
    `location` gives. And gives the lines that sum up what was verified and skipped: evidence
    that cites an output has no paper, and evidence with no quote nothing to seek."""
    from astra import api
    from astra._internal.papers import library
    from astra.model.diagnostic import Diagnostic

    found: list[Diagnostic] = []
    summary: list[str] = []
    for label, insights in _insights(stack).items():
        verified = artifacts = unquoted = failed = 0
        for insight_id, insight in insights.items():
            for index, item in enumerate(insight.evidence):
                if item.doi is None:
                    artifacts += 1
                    continue
                if item.quote is None:
                    unquoted += 1
                    continue
                named = item.doi + ("" if item.version is None else f" version {item.version}")
                code, field = "EVIDENCE_QUOTE_NOT_FOUND", "quote"
                try:
                    status = api.verify_quote(
                        item.doi, item.quote, version=item.version, location=item.location
                    )
                except api.PaperError as error:
                    code, field, message = "EVIDENCE_PAPER_UNREADABLE", "doi", str(error)
                else:
                    if status.state == "found":
                        verified += 1
                        continue
                    if status.state == "no_paper":
                        add = f"astra paper add {item.doi}"
                        add += "" if item.version is None else f" --version {item.version}"
                        code, field = "EVIDENCE_PAPER_MISSING", "doi"
                        message = (
                            f"the paper of {named} isn't in the cache, so its quote isn't "
                            f"verified: run `{add}`"
                        )
                    elif status.state == "elsewhere":
                        message = (
                            f"the quote isn't found in the paper of {named} on page "
                            f"{library.page(item.location)}, where its location places it "
                            f"(it is on page {status.page})"
                        )
                    else:
                        message = (
                            f"the quote isn't found in the paper of {named}: copy it exactly "
                            "from the paper, and check the DOI and version"
                        )
                failed += 1
                at = stack.location(stack.root, (label, insight_id, "evidence", index, field))
                found.append(Diagnostic(code, "error", message, at))
        parts = [f"{verified}/{verified + artifacts + unquoted + failed} verified"]
        if artifacts:
            parts.append(f"{artifacts} SKIPPED (artifact)")
        if unquoted:
            parts.append(f"{unquoted} skipped")
        if failed:
            parts.append(f"{failed} failed")
        summary.append(f"Evidence ({label}): " + ", ".join(parts))
    found.sort(key=lambda d: (d.location.line or 0, d.location.column or 0))
    return found, summary


def _roots(top: Path) -> list[Path]:
    """The folder of each root analysis under `top`: each astra.yaml that no other one found
    declares, directly or not, a folder before those below it."""
    found: list[Path] = []
    for folder, children, files in os.walk(top):
        children[:] = sorted(c for c in children if not c.startswith(".") and c not in SKIPPED)
        if "astra.yaml" in files:
            found.append(Path(folder).resolve())
    declared: set[Path] = set()
    roots: list[Path] = []
    for root in found:
        if root in declared:
            continue
        roots.append(root)
        stack = read_stack(root)
        if stack is not None:
            declared |= _declared(stack, root)
    return roots


def _declared(stack: Stack, folder: Path) -> set[Path]:
    """The folders, in the working tree, of the analyses `stack`'s root declares, directly or
    not: they are validated with it."""
    top = folder
    for _ in Path(stack.root.folder).parts:  # the root's folder is a path from the tree's top
        top = top.parent
    return {
        (top / identity.folder).resolve()
        for identity in stack.analyses
        if identity.commit is None and identity != stack.root
    }
