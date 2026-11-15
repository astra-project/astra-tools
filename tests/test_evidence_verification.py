"""Integration tests for evidence verification using a real arXiv paper.

Uses arXiv:1603.01599 "High Resolution Weak Lensing Mass-Mapping Combining
Shear and Flexion" by Lanusse et al.

These tests require network access and optional dependencies:
    pip install httpx pypdf

Run with: pytest tests/test_evidence_verification.py -v
"""

import shutil
import tempfile
from pathlib import Path

import pytest

# Check for optional dependencies
httpx = pytest.importorskip("httpx", reason="httpx required: pip install httpx")
pypdf = pytest.importorskip("pypdf", reason="pypdf required: pip install pypdf")

# Mark all tests as requiring network and verify deps
pytestmark = [
    pytest.mark.network,
    pytest.mark.slow,
]


# Test paper details
ARXIV_ID = "1603.01599"
DOI = f"10.48550/arXiv.{ARXIV_ID}"
VERSION = 1  # Use a specific version for reproducibility

# Real quote from the paper abstract
VALID_QUOTE = (
    "Including flexion allows us to supplement the shear on small scales "
    "in order to increase the sensitivity to substructures and the overall "
    "resolution of the convergence map."
)

# A fabricated quote that doesn't exist in the paper
FAKE_QUOTE = (
    "This paper proves that deep learning is always better than "
    "traditional methods for all scientific applications."
)


@pytest.fixture(scope="module")
def temp_cache_dir():
    """Create a temporary cache directory for tests."""
    cache_dir = Path(tempfile.mkdtemp(prefix="astra_test_cache_"))
    yield cache_dir
    # Cleanup after all tests in module
    shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def paper_cache(temp_cache_dir):
    """Create a paper cache using temp directory."""
    from astra._internal.papers.cache import PaperCache

    return PaperCache(cache_dir=temp_cache_dir / "papers")


@pytest.fixture(scope="module")
def downloaded_paper(paper_cache):
    """Download the test paper once for all tests."""
    from astra._internal.papers.download import download_paper

    # Check if already in cache
    if paper_cache.has(DOI, VERSION):
        return paper_cache.get(DOI, VERSION)

    # Download the paper
    result = download_paper(DOI, VERSION)
    assert result.success, f"Failed to download paper: {result.error}"
    assert result.content is not None

    # Add to cache
    paper = paper_cache.add(
        doi=DOI,
        pdf_content=result.content,
        version=VERSION,
        source_url=result.url,
    )
    return paper


class TestPaperDownload:
    """Tests for paper downloading and caching."""

    def test_download_arxiv_paper(self, downloaded_paper):
        """Test that we can download an arXiv paper."""
        assert downloaded_paper is not None
        assert downloaded_paper.pdf_path.exists()
        assert downloaded_paper.metadata.doi == DOI
        assert downloaded_paper.metadata.version == VERSION
        assert len(downloaded_paper.metadata.sha256) == 64  # SHA-256 hex

    def test_paper_is_cached(self, paper_cache, downloaded_paper):
        """Test that downloaded paper is in cache."""
        assert paper_cache.has(DOI, VERSION)
        cached = paper_cache.get(DOI, VERSION)
        assert cached is not None
        assert cached.pdf_path == downloaded_paper.pdf_path

    def test_cache_returns_same_path(self, paper_cache):
        """Test that cache returns consistent paths."""
        path1 = paper_cache.get_path(DOI, VERSION)
        path2 = paper_cache.get_path(DOI, VERSION)
        assert path1 == path2


class TestPDFExtraction:
    """Tests for PDF text extraction."""

    def test_extract_text_from_pdf(self, downloaded_paper):
        """Test that we can extract text from the PDF."""
        from astra._internal.papers.pdf import extract_text_from_pdf

        pdf = extract_text_from_pdf(downloaded_paper.pdf_path)
        assert pdf.num_pages > 0
        assert len(pdf.pages) == pdf.num_pages
        assert pdf.sha256 == downloaded_paper.metadata.sha256

    def test_find_valid_quote(self, downloaded_paper):
        """Test that we can find a real quote in the paper."""
        from astra._internal.papers.pdf import extract_text_from_pdf

        pdf = extract_text_from_pdf(downloaded_paper.pdf_path)
        found_pages = pdf.find_quote(VALID_QUOTE)
        assert len(found_pages) > 0, f"Quote not found in paper: {VALID_QUOTE[:50]}..."

    def test_fake_quote_not_found(self, downloaded_paper):
        """Test that a fake quote is not found."""
        from astra._internal.papers.pdf import extract_text_from_pdf

        pdf = extract_text_from_pdf(downloaded_paper.pdf_path)
        found_pages = pdf.find_quote(FAKE_QUOTE)
        assert len(found_pages) == 0, "Fake quote should not be found"


class TestQuoteVerification:
    """`api.verify_quote` on the real paper, put in the test's own paper cache."""

    @pytest.fixture
    def kept(self, downloaded_paper):
        from astra import api

        return api.add_paper(DOI, version=VERSION, pdf=downloaded_paper.pdf_path)

    def test_a_quote_of_the_paper_is_found(self, kept):
        from astra import api

        status = api.verify_quote(DOI, api.TextQuoteSelector(VALID_QUOTE), version=VERSION)
        assert status.state == "found" and status.page is not None

    def test_a_fabricated_quote_isnt(self, kept):
        from astra import api

        status = api.verify_quote(DOI, api.TextQuoteSelector(FAKE_QUOTE), version=VERSION)
        assert status == api.QuoteStatus("not_found")

    def test_a_paper_that_isnt_cached_has_no_paper(self):
        from astra import api

        status = api.verify_quote("10.48550/arXiv.9999.99999", api.TextQuoteSelector("test"))
        assert status == api.QuoteStatus("no_paper")


class TestRapidFuzzMatching:
    """Tests for RapidFuzz-based fuzzy matching."""

    def test_exact_match(self):
        """Test that exact matches are found."""
        from astra._internal.papers.pdf import PDFDocument

        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["This is an exact quote from the paper."],
            num_pages=1,
            sha256="test",
        )
        found = pdf.find_quote("This is an exact quote from the paper.")
        assert 1 in found

    def test_case_insensitive_match(self):
        """Test that matching is case-insensitive."""
        from astra._internal.papers.pdf import PDFDocument

        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["The Model achieves GREAT results."],
            num_pages=1,
            sha256="test",
        )
        found = pdf.find_quote("the model achieves great results")
        assert 1 in found

    def test_fuzzy_match_with_typos(self):
        """Test that fuzzy matching handles minor typos/OCR errors."""
        from astra._internal.papers.pdf import PDFDocument

        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["The rnodel achieves great resu1ts."],  # OCR errors: rn->m, 1->l
            num_pages=1,
            sha256="test",
        )
        found = pdf.find_quote("The model achieves great results.", min_score=70.0)
        assert 1 in found

    def test_fuzzy_match_with_inline_citations(self):
        """Test that fuzzy matching handles inline citations in PDF text."""
        from astra._internal.papers.pdf import PDFDocument

        # PDF has citations that user's quote doesn't include
        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["The model [29] achieves great results [1, 2]."],
            num_pages=1,
            sha256="test",
        )
        found = pdf.find_quote("The model achieves great results.", min_score=70.0)
        assert 1 in found

    def test_fuzzy_match_unicode_variations(self):
        """Test that fuzzy matching handles Unicode character variations."""
        from astra._internal.papers.pdf import PDFDocument

        # PDF has different Unicode characters
        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["The value is ∼100 with α = 0.5"],  # Unicode tilde and alpha
            num_pages=1,
            sha256="test",
        )
        # User might write ASCII approximations
        found = pdf.find_quote("The value is ~100 with alpha = 0.5", min_score=60.0)
        assert 1 in found

    def test_quote_not_found(self):
        """Test that non-existent quotes are not found."""
        from astra._internal.papers.pdf import PDFDocument

        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=["This paper discusses machine learning algorithms for image classification."],
            num_pages=1,
            sha256="test",
        )
        # Completely different content should not match
        found = pdf.find_quote(
            "Quantum entanglement enables faster-than-light communication.",
            min_score=70.0,
        )
        assert len(found) == 0


class TestPrefixSuffixContext:
    """Tests for W3C TextQuoteSelector prefix/suffix disambiguation."""

    @pytest.mark.xfail(
        reason="stale on main: find_quote returns at the first page found", strict=True
    )
    def test_prefix_suffix_disambiguation(self):
        """Test that prefix/suffix help disambiguate repeated quotes.

        In practice, prefix/suffix provide unique context like section headers,
        figure references, or distinctive surrounding text.
        """
        from astra._internal.papers.pdf import PDFDocument

        # Same quote appears twice with very different context
        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=[
                "As shown in Figure 3, the neural network achieves high accuracy. "
                "This validates our hypothesis about deep learning.",
                "According to Table 7, the random forest achieves high accuracy. "
                "This confirms the baseline performance.",
            ],
            num_pages=2,
            sha256="test",
        )

        # Without prefix/suffix, both pages match the common phrase
        found = pdf.find_quote("achieves high accuracy")
        assert len(found) == 2

        # With prefix, only page 1 matches (neural network context)
        found = pdf.find_quote(
            "achieves high accuracy",
            prefix="As shown in Figure 3, the neural network",
        )
        assert 1 in found
        assert 2 not in found

    def test_suffix_context(self):
        """Test that suffix helps narrow down matches."""
        from astra._internal.papers.pdf import PDFDocument

        pdf = PDFDocument(
            path=None,  # type: ignore
            pages=[
                "The algorithm converges rapidly. Theorem 4.2 provides the convergence guarantee.",
                "The algorithm converges rapidly. Empirical results support this observation.",
            ],
            num_pages=2,
            sha256="test",
        )

        # With suffix specifying the theorem reference, only page 1 matches
        found = pdf.find_quote(
            "The algorithm converges rapidly.",
            suffix="Theorem 4.2 provides the convergence guarantee.",
        )
        assert 1 in found
        assert 2 not in found


class TestPageHint:
    """A page hint says where the search starts, never what is found."""

    @staticmethod
    def document():
        from astra._internal.papers.pdf import PDFDocument

        pages = ["" for _ in range(10)]
        pages[4] = "This is the quote we are looking for."
        return PDFDocument(path=None, pages=pages, num_pages=10, sha256="test")  # type: ignore

    def test_a_wrong_page_hint_still_finds_the_quote(self):
        found = self.document().find_quote("This is the quote we are looking for", page=1)
        assert found == [5]

    def test_no_page_hint(self):
        assert self.document().find_quote("This is the quote we are looking for") == [5]
