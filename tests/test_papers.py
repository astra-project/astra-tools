"""The paper functions of `astra.api`: a paper looked up in the cache, one put there, and a
quote sought in one."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from astra import api
from astra.model import to_json
from tests.test_paper_cli import DOI, TEXT, pdf

QUOTE = api.TextQuoteSelector("reduce the influence of outliers")
OTHER = "Section one describes the telescope, its camera and the survey it carried out."


def test_a_paper_is_added_from_a_pdf_and_looked_up(tmp_path: Path) -> None:
    assert api.paper(DOI) is None
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    added = api.add_paper(DOI, version=2, pdf=source)
    assert api.paper(DOI, version=2) == added
    assert api.paper(DOI) is None  # the version is part of which paper it is
    assert (added.doi, added.version, added.title, added.authors) == (DOI, 2, None, ())
    assert Path(added.pdf_path).is_absolute()
    assert Path(added.pdf_path).read_bytes() == source.read_bytes()
    assert added.content_hash == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def test_a_paper_already_in_the_cache_is_given_as_it_is(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    added = api.add_paper(DOI, pdf=source)
    source.write_bytes(pdf(OTHER))
    assert api.add_paper(DOI, pdf=source) == added
    assert api.add_paper(DOI) == added  # nothing is downloaded for it either


def test_a_paper_that_cant_be_got_is_an_error(tmp_path: Path) -> None:
    """Only an arXiv paper is downloaded, and only a PDF is kept."""
    with pytest.raises(api.PaperError, match="Only arXiv papers"):
        api.add_paper(DOI)
    notes = tmp_path / "notes.txt"
    notes.write_text("not a PDF")
    with pytest.raises(api.PaperError, match="not a valid PDF"):
        api.add_paper(DOI, pdf=notes)
    with pytest.raises(OSError):
        api.add_paper(DOI, pdf=tmp_path / "nothere.pdf")
    assert api.paper(DOI) is None


def test_a_quote_is_found_on_its_page_elsewhere_or_not_at_all(tmp_path: Path) -> None:
    assert api.verify_quote(DOI, QUOTE) == api.QuoteStatus("no_paper")
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf(OTHER, TEXT))
    api.add_paper(DOI, pdf=source)
    assert api.verify_quote(DOI, QUOTE) == api.QuoteStatus("found", 2)
    on = api.FragmentSelector("page=2")
    assert api.verify_quote(DOI, QUOTE, location=on) == api.QuoteStatus("found", 2)
    off = api.FragmentSelector("page=1")
    assert api.verify_quote(DOI, QUOTE, location=off) == api.QuoteStatus("elsewhere", 2)
    # A location that isn't a PDF fragment identifier gives no page to hold the quote to.
    other = api.FragmentSelector("xywh=0,0,10,10", "http://www.w3.org/TR/media-frags/")
    assert api.verify_quote(DOI, QUOTE, location=other) == api.QuoteStatus("found", 2)
    never = api.TextQuoteSelector("a sentence the paper never says anywhere at all")
    assert api.verify_quote(DOI, never) == api.QuoteStatus("not_found")
    assert api.verify_quote(DOI, QUOTE, version=3) == api.QuoteStatus("no_paper")


def test_an_evidence_of_the_resolved_analysis_passes_field_by_field(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    api.add_paper(DOI, pdf=source)
    evidence = api.Evidence(doi=DOI, quote=QUOTE, location=api.FragmentSelector("page=1"))
    assert evidence.doi is not None and evidence.quote is not None
    status = api.verify_quote(
        evidence.doi, evidence.quote, version=evidence.version, location=evidence.location
    )
    assert status == api.QuoteStatus("found", 1)


def test_a_paper_whose_text_cant_be_read_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\nnothing a PDF reader can make a page of\n")
    api.add_paper(DOI, pdf=source)
    with pytest.raises(api.PaperError, match="can't be read"):
        api.verify_quote(DOI, QUOTE)


def test_they_write_as_json_by_the_models_rule(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(pdf(TEXT))
    added = api.add_paper(DOI, pdf=source)
    assert to_json(added) == {
        "doi": DOI,
        "pdf_path": added.pdf_path,
        "content_hash": added.content_hash,
        "retrieved": added.retrieved,
        "authors": [],
        "source_url": added.source_url,
    }
    assert to_json(api.QuoteStatus("not_found")) == {"state": "not_found"}
    assert to_json(api.QuoteStatus("found", 3)) == {"state": "found", "page": 3}
