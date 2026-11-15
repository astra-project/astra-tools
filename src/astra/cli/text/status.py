"""The status report as text: each result, by its id, with its statuses and where its record
is, then why, as `line:col level CODE message`, each entry that reads a result that isn't
unchanged, and the environment its record names with the runner that recorded it, which is the
one to say what that environment holds; then the evidence, by the insight it backs, and each
input whose content isn't here. Bytes come with the tool that keeps them, where one does."""

from __future__ import annotations

from types import MappingProxyType

from rich.text import Text

from astra.cli.text import console, rule_line
from astra.model.resolved_analysis import ResolvedAnalysis
from astra.model.status_report import Bytes, StatusReport

_STYLES = MappingProxyType(
    {
        "unchanged": "green",
        "stale": "yellow",
        "missing": "red",
        "present": "green",
        "absent": "yellow",
    }
)


def show(analysis: ResolvedAnalysis, report: StatusReport) -> None:
    out = console()
    counts = dict.fromkeys(("unchanged", "stale", "missing", "absent"), 0)
    for result in analysis.results:
        status = report.statuses[result.id]
        line = Text(result.id, style="bold")
        line.append("  ")
        line.append(status.state, style=_STYLES[status.state])
        counts[status.state] += 1
        if status.bytes is not None:
            line.append("  ")
            line.append_text(_bytes(status.bytes))
            counts["absent"] += status.bytes.state == "absent"
        line.append("  " + ", ".join(place.record_path for place in result.places), style="dim")
        out.print(line)
        for broken in status.why:
            out.print(rule_line(broken.location, broken.level, broken.code, broken.message))
        read = {source.entry: source.result for source in result.inputs}
        for entry in status.stale_inputs:
            out.print(f"  `{entry}` reads `{read[entry]}`, which isn't what it was made from")
        if status.record is not None:
            run = status.record.generated_by
            made = f"  made in {run.environment.iri} by {run.runner.id} {run.runner.version}"
            out.print(Text(made, style="dim"))
    for evidence in report.evidence:
        line = Text(f"{evidence.insight} evidence {evidence.index}", style="bold")
        line.append("  ")
        line.append(evidence.state, style=_STYLES[evidence.state])
        out.print(line)
        for broken in evidence.why:
            out.print(rule_line(broken.location, broken.level, broken.code, broken.message))
    for ref, content in report.inputs.items():
        if content.state == "absent":  # an input whose content is here needs no word
            out.print(Text.assemble((ref, "bold"), "  ", _bytes(content)))
    out.print(
        f"{len(report.statuses)} result(s), {counts['unchanged']} unchanged, "
        f"{counts['stale']} stale, {counts['missing']} missing; {counts['absent']} absent"
    )


def _bytes(content: Bytes) -> Text:
    """Where some bytes are: `present` or `absent`, and the tool that keeps them."""
    shown = Text(content.state, style=_STYLES[content.state])
    if content.kept_by is not None:
        shown.append(f", kept by {content.kept_by}")
    return shown
