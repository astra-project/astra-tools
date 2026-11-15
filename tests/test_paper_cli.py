"""The `astra paper` commands, as astra-tools 0.2 had them: a paper kept from a local PDF is
listed, shown, found by its path, and its quotes verified from JSON on stdin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from astra._internal.sources import cache
from astra.cli import main
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


def test_verify_quotes_reads_json_on_stdin_and_writes_json(home: Path) -> None:
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    quotes = {"quotes": [{"text": "reduce the influence of outliers", "page": 1}]}
    result = astra("paper", "verify-quotes", DOI, stdin=json.dumps(quotes))
    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["summary"] == {"total": 1, "verified": 1, "not_found": 0, "errors": 0}
    assert (output["results"][0]["status"], output["results"][0]["found_pages"]) == (
        "verified",
        [1],
    )
    quotes["quotes"].append({"text": "a sentence the paper never says anywhere at all"})
    result = astra("paper", "verify-quotes", DOI, stdin=json.dumps(quotes))
    assert result.exit_code == 1
    assert json.loads(result.stdout)["summary"]["not_found"] == 1
    one = astra("paper", "verify-quote", DOI, "-q", "influence of outliers", "--json")
    assert one.exit_code == 0 and json.loads(one.stdout)["status"] == "verified"


def test_verify_quotes_no_input(home: Path) -> None:
    result = astra("paper", "verify-quotes", "10.1234/test", stdin="")
    assert result.exit_code == 2
    assert "No input" in json.loads(result.stdout)["error"]


def test_verify_quotes_invalid_json(home: Path) -> None:
    result = astra("paper", "verify-quotes", "10.1234/test", stdin="not valid json{")
    assert result.exit_code == 2
    assert "Invalid JSON" in json.loads(result.stdout)["error"]


def test_verify_quotes_paper_not_cached(home: Path) -> None:
    quotes = json.dumps({"quotes": [{"text": "some quote"}]})
    result = astra("paper", "verify-quotes", "10.9999/test", "--version", "1", stdin=quotes)
    assert result.exit_code == 2
    output = json.loads(result.stdout)
    assert (output["doi"], output["version"]) == ("10.9999/test", 1)
    assert "not in cache" in output["error"] and "summary" in output


def test_the_papers_are_kept_in_the_astra_cache(home: Path) -> None:
    """Under `ASTRA_CACHE_DIR`, with what else astra-tools keeps, not in the home folder."""
    source = home / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    assert astra("paper", "add", DOI, "--pdf", str(source)).exit_code == 0
    kept = Path(astra("paper", "path", DOI).stdout.strip())
    assert kept.is_relative_to(cache.root() / "papers")
    quotes = json.dumps({"quotes": [{"text": "influence of outliers"}]})
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
    """A failure isn't taken from the verification cache as a success."""
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
    assert beyond.exit_code == 1 and "the PDF has 2 page(s)" in beyond.stdout
    analysis(folder, text + "        location: {value: page=2}\n")
    assert astra("validate", str(folder), "-e").exit_code == 0  # not the cached failure
