"""The check report as text: each planned result, by its id, with its statuses and where its
record is, then why, as `line:col level CODE message`, each entry that reads a result that
isn't unchanged, and the environment its record names with the runner that recorded it, which is
the one to say what that environment holds; then the evidence, by the insight it backs."""

from __future__ import annotations

from types import MappingProxyType

from rich.text import Text

from astra.cli.text import console, rule_line
from astra.model.check_report import CheckReport

_STYLES = MappingProxyType(
    {
        "unchanged": "green",
        "stale": "yellow",
        "missing": "red",
        "present": "green",
        "absent": "yellow",
    }
)


def show(report: CheckReport) -> None:
    out = console()
    counts = dict.fromkeys(("unchanged", "stale", "missing", "absent"), 0)
    for result in report.analysis.results:
        status = report.statuses[result.id]
        line = Text(result.id, style="bold")
        line.append("  ")
        line.append(status.state, style=_STYLES[status.state])
        counts[status.state] += 1
        if status.bytes is not None:
            line.append("  ")
            line.append(status.bytes, style=_STYLES[status.bytes])
            counts["absent"] += status.bytes == "absent"
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
    out.print(
        f"{len(report.statuses)} planned result(s), {counts['unchanged']} unchanged, "
        f"{counts['stale']} stale, {counts['missing']} missing; {counts['absent']} absent"
    )
