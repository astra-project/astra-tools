"""The `astra paper` commands: a paper kept from a local PDF is listed, shown and found by its
path, and quotes are sought in it, one given as an option or several as JSON on stdin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from astra import api
from astra._internal.sources import cache
from astra.cli import main
from astra.model import to_json
from tests.conftest import MINIMAL, analysis, git_init

DOI = "10.9999/example"
TEXT = "Robust estimators reduce the influence of outliers on fitted relations."


def pdf(*texts: str) -> bytes:
    """A PDF with one page for each of `texts`, whose text it is."""
    count = len(texts)
    kids = b" ".join(b"%d 0 R" % (4 + 2 * n) for n in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, count),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for n, text in enumerate(texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * n)
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    data = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    data += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return data


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A folder for the test's files; its paper cache is the test's own cache, empty."""
    return tmp_path


def astra(*args: str, stdin: str | None = None) -> Result:
    return CliRunner().invoke(main, list(args), input=stdin)


def test_a_paper_added_from_a_pdf_is_listed_shown_and_found(home: Path) -> None:
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "list").stdout.strip() == "No papers cached"
    added = astra("paper", "add", DOI, "-v", "2", "--pdf", str(source))
    assert added.exit_code == 0 and "Paper added to cache" in added.stdout
    assert (
        "already cached"
        in astra("paper", "add", DOI, "--version", "2", "--pdf", str(source)).stdout
    )
    path = astra("paper", "path", DOI, "-v", "2")
    assert path.exit_code == 0
    kept = Path(path.stdout.strip())
    assert kept.suffix == ".pdf" and kept.read_bytes() == source.read_bytes()
    assert DOI in astra("paper", "list").stdout
    shown = astra("paper", "show", DOI, "--version", "2")
    assert shown.exit_code == 0 and "SHA-256:" in shown.stdout
    assert astra("paper", "remove", DOI, "-v", "2").exit_code == 0
    assert astra("paper", "path", DOI, "-v", "2").exit_code == 1
    assert astra("paper", "show", DOI).exit_code == 1


def test_a_paper_that_cant_be_added_is_an_error_as_the_api_gives_it(home: Path) -> None:
    """`paper add` is `api.add_paper`: what isn't a PDF, and a paper that isn't downloaded,
    each exit 1 with the reason, and keep nothing."""
    notes = home / "notes.txt"
    notes.write_text("not a PDF")
    refused = astra("paper", "add", DOI, "--pdf", str(notes))
    assert refused.exit_code == 1 and "not a valid PDF" in refused.stdout
    missing = astra("paper", "add", DOI)
    assert missing.exit_code == 1 and "Only arXiv papers" in missing.stdout
    assert astra("paper", "list").stdout.strip() == "No papers cached"


def test_verify_quotes_reads_evidence_items_on_stdin_and_writes_each_status(home: Path) -> None:
    """Each item has the `quote` and `location` of an evidence item, and each status is what
    `api.verify_quote` gives, in the same order."""
    source = home / "paper.pdf"
    source.write_bytes(pdf("An unrelated first page of introduction.", TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    exact = "reduce the influence of outliers"
    quotes: list[dict[str, dict[str, str]]] = [
        {"quote": {"exact": exact}, "location": {"value": "page=2"}}
    ]
    result = astra("paper", "verify-quotes", DOI, stdin=json.dumps(quotes))
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"state": "found", "page": 2}]
    quotes += [
        {"quote": {"exact": "a sentence the paper never says anywhere at all"}},
        {"quote": {"exact": exact, "prefix": "estimators "}, "location": {"value": "page=1"}},
    ]
    result = astra("paper", "verify-quotes", DOI, stdin=json.dumps(quotes))
    assert result.exit_code == 1
    assert json.loads(result.stdout) == [
        {"state": "found", "page": 2},
        {"state": "not_found"},
        {"state": "elsewhere", "page": 2},
    ]
    status = api.verify_quote(
        DOI, api.TextQuoteSelector(exact), location=api.FragmentSelector("page=2")
    )
    assert json.loads(result.stdout)[0] == to_json(status)
    assert astra("paper", "verify-quotes", DOI, stdin="[]").stdout.strip() == "[]"


def test_verify_quote_prints_one_status(home: Path) -> None:
    source = home / "paper.pdf"
    source.write_bytes(pdf("An unrelated first page of introduction.", TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    one = astra("paper", "verify-quote", DOI, "-q", "influence of outliers", "--json")
    assert one.exit_code == 0 and json.loads(one.stdout) == {"state": "found", "page": 2}
    shown = astra("paper", "verify-quote", DOI, "-q", "influence of outliers", "--page", "2")
    assert shown.exit_code == 0 and "Found on page 2" in shown.stdout
    off = astra("paper", "verify-quote", DOI, "-q", "influence of outliers", "-p", "1", "--json")
    assert off.exit_code == 1 and json.loads(off.stdout) == {"state": "elsewhere", "page": 2}
    shown = astra("paper", "verify-quote", DOI, "-q", "influence of outliers", "-p", "1")
    assert shown.exit_code == 1 and "Not on page 1: the quote is on page 2" in shown.stdout
    never = astra("paper", "verify-quote", DOI, "-q", "a sentence the paper never says", "--json")
    assert never.exit_code == 1 and json.loads(never.stdout) == {"state": "not_found"}


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not valid json{",
        json.dumps({"quotes": [{"text": "a quote"}]}),
        json.dumps([{"text": "a quote"}]),
        json.dumps([{"quote": {"text": "a quote"}}]),
        json.dumps([{"quote": {"exact": "a quote"}, "location": {"page": 2}}]),
    ],
)
def test_verify_quotes_takes_only_a_list_of_quotes(home: Path, stdin: str) -> None:
    result = astra("paper", "verify-quotes", DOI, stdin=stdin)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "the input isn't a JSON list of quotes" in result.stderr


def test_a_quote_of_a_paper_that_isnt_cached_has_no_paper(home: Path) -> None:
    quotes = json.dumps([{"quote": {"exact": "some quote"}}])
    result = astra("paper", "verify-quotes", "10.9999/test", "--version", "1", stdin=quotes)
    assert result.exit_code == 1
    assert json.loads(result.stdout) == [{"state": "no_paper"}]
    one = astra("paper", "verify-quote", "10.9999/test", "-q", "some quote")
    assert one.exit_code == 1 and "astra paper add 10.9999/test" in one.stdout


def test_a_paper_whose_text_cant_be_read_exits_2(home: Path) -> None:
    source = home / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\nnothing a PDF reader can make a page of\n")
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    result = astra("paper", "verify-quote", DOI, "-q", "some quote", "--json")
    assert result.exit_code == 2
    assert result.stdout == "" and "can't be read" in result.stderr


def test_the_papers_are_kept_in_the_astra_cache(home: Path) -> None:
    """Under `ASTRA_CACHE_DIR`, with what else astra-tools keeps, not in the home folder."""
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    kept = Path(astra("paper", "path", DOI).stdout.strip())
    assert kept.is_relative_to(cache.root() / "papers")
    quotes = json.dumps([{"quote": {"exact": "influence of outliers"}}])
    assert astra("paper", "verify-quotes", DOI, stdin=quotes).exit_code == 0
    assert (cache.root() / "text_cache").is_dir()


def test_only_an_arxiv_paper_is_downloaded(home: Path) -> None:
    """Any other paper is added from a PDF the user has: nothing is asked of another service."""
    result = astra("paper", "add", DOI)
    assert result.exit_code == 1
    assert "Only arXiv papers" in result.stdout and "--pdf" in result.stdout


INSIGHT = """\
prior_insights:
  robust:
    claim: Robust estimators help.
    evidence:
      - doi: "10.9999/example"
        quote:
          exact: "{quote}"
"""


def test_validate_reports_evidence_as_it_reports_rules(home: Path) -> None:
    """A quote that isn't verified is an error of the report, with its code and place: its
    paper not in the cache, then the quote not in the paper."""
    folder = analysis(
        git_init(home / "repo"), MINIMAL + INSIGHT.format(quote="influence of outliers")
    )
    missing = astra("validate", str(folder), "-e")
    assert missing.exit_code == 1
    lines = missing.stdout.splitlines()
    assert lines[0] == "astra.yaml"
    assert lines[1].startswith("  12:14 error EVIDENCE_PAPER_MISSING the paper of 10.9999/example")
    assert "run `astra paper add 10.9999/example`" in lines[1]
    assert "astra.yaml: invalid, 1 error(s), 0 warning(s)" in missing.stdout
    assert "Evidence (prior_insights): 0/1 verified, 1 failed" in missing.stdout
    assert astra("validate", str(folder)).exit_code == 0  # without -e, nothing is verified

    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    found = astra("validate", str(folder), "-e")
    assert found.exit_code == 0
    assert "Evidence (prior_insights): 1/1 verified" in found.stdout

    folder = analysis(folder, MINIMAL + INSIGHT.format(quote="a sentence the paper never says"))
    result = astra("validate", str(folder), "-e", "--json")
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["valid"] is False
    (diagnostic,) = report["diagnostics"]
    assert (diagnostic["code"], diagnostic["level"]) == ("EVIDENCE_QUOTE_NOT_FOUND", "error")
    assert diagnostic["location"]["pointer"] == "/prior_insights/robust/evidence/0/quote"
    assert "evidence" not in report


def test_a_wrong_quote_fails_every_time_it_is_verified(home: Path) -> None:
    """Each run seeks the quote again: nothing remembers an earlier answer."""
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    text = MINIMAL + INSIGHT.format(quote="a sentence the paper never says")
    folder = analysis(git_init(home / "repo"), text)
    assert [astra("validate", str(folder), "-e").exit_code for _ in range(3)] == [1, 1, 1]


def test_a_quote_is_sought_on_the_page_its_location_gives(home: Path) -> None:
    """With `location: {value: page=N}`, the quote is on page N or isn't found; with no
    location, it is found on any page."""
    source = home / "paper.pdf"
    source.write_bytes(pdf("An unrelated first page of introduction.", TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    text = MINIMAL + INSIGHT.format(quote="influence of outliers")
    folder = analysis(git_init(home / "repo"), text)
    assert astra("validate", str(folder), "-e").exit_code == 0
    analysis(folder, text + "        location: {value: page=2}\n")
    assert astra("validate", str(folder), "-e").exit_code == 0
    analysis(folder, text + "        location: {value: page=1}\n")
    wrong = astra("validate", str(folder), "-e")
    assert wrong.exit_code == 1
    assert "EVIDENCE_QUOTE_NOT_FOUND" in wrong.stdout
    assert "on page 1, where its location places it (it is on page 2)" in wrong.stdout
    analysis(folder, text + "        location: {value: page=9}\n")
    beyond = astra("validate", str(folder), "-e")
    assert beyond.exit_code == 1
    assert "on page 9, where its location places it (it is on page 2)" in beyond.stdout
    analysis(folder, text + "        location: {value: page=2}\n")
    assert astra("validate", str(folder), "-e").exit_code == 0  # not the cached failure


def test_validate_seeks_quotes_as_the_api_does(home: Path) -> None:
    """`astra validate -e` and `api.verify_quote` are one check: each evidence's fields go
    to the function as they are written, and its answer is the report's."""
    source = home / "paper.pdf"
    source.write_bytes(pdf("An unrelated first page of introduction.", TEXT))
    api.add_paper(DOI, pdf=source)
    quote = api.TextQuoteSelector("influence of outliers")
    for location, state in (("page=2", "found"), ("page=1", "elsewhere")):
        text = MINIMAL + INSIGHT.format(quote=quote.exact)
        folder = analysis(
            git_init(home / state), text + f"        location: {{value: {location}}}\n"
        )
        status = api.verify_quote(DOI, quote, location=api.FragmentSelector(location))
        assert status.state == state
        assert (astra("validate", str(folder), "-e").exit_code == 0) == (state == "found")


FINDINGS = """\
findings:
  best:
    claim: The result is best.
    evidence:
      - artifact: result
      - doi: "10.9999/example"
        quote:
          exact: "influence of outliers"
      - doi: "10.9999/example"
"""


def test_validate_verifies_findings_and_skips_what_has_no_quote_to_seek(home: Path) -> None:
    """Findings are verified as prior insights are. Evidence that cites an output has no
    paper, and evidence with no quote nothing to seek: each is counted, and neither fails."""
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    api.add_paper(DOI, pdf=source)
    folder = analysis(git_init(home / "repo"), MINIMAL + FINDINGS)
    result = astra("validate", str(folder), "-e")
    assert result.exit_code == 0, result.output
    assert "Evidence (findings): 1/3 verified, 1 SKIPPED (artifact), 1 skipped" in result.stdout
    hinted = astra("validate", str(folder))
    assert "Run with --verify-evidence to verify quotes exist in papers." in hinted.stdout
    assert "--verify-evidence" not in astra("validate", str(folder), "--skip-evidence").stdout
    assert json.loads(astra("validate", str(folder), "-e", "--json").stdout)["diagnostics"] == []


def test_validate_reports_a_paper_whose_text_cant_be_read(home: Path) -> None:
    source = home / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\nnothing a PDF reader can make a page of\n")
    api.add_paper(DOI, pdf=source)
    folder = analysis(git_init(home / "repo"), MINIMAL + INSIGHT.format(quote="some quote"))
    result = astra("validate", str(folder), "-e", "--json")
    assert result.exit_code == 1
    (diagnostic,) = json.loads(result.stdout)["diagnostics"]
    assert diagnostic["code"] == "EVIDENCE_PAPER_UNREADABLE"
    assert diagnostic["location"]["pointer"] == "/prior_insights/robust/evidence/0/doi"


def test_validate_stops_as_any_command_does_where_the_cache_cant_be_used(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paper cache that can't be used is a broken environment, not a bug in astra-tools."""
    folder = analysis(git_init(home / "repo"), MINIMAL + INSIGHT.format(quote="some quote"))
    monkeypatch.setenv("ASTRA_CACHE_DIR", "relative/cache")
    result = astra("validate", str(folder), "-e")
    assert result.exit_code == 2
    assert result.stderr.startswith("astra: ASTRA_CACHE_DIR is the relative path")
    assert "This is a bug" not in result.stderr
