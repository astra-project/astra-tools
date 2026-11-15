"""What `astra.api` offers of the paper cache: a paper looked up, a paper added, a quote sought
in one."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import TYPE_CHECKING

from astra._internal.papers.cache import CachedPaper, PaperCache
from astra.errors import PaperError
from astra.model.paper import Paper, QuoteStatus
from astra.model.resolved_analysis import FragmentSelector, TextQuoteSelector

if TYPE_CHECKING:
    from astra._internal.papers.pdf import PDFDocument

PDF = (None, "http://tools.ietf.org/rfc/rfc3778")
"""The `conforms_to` of a PDF fragment identifier: none, or the IRI Web Annotation gives it."""


def page(location: FragmentSelector | None) -> int | None:
    """The page, counted from 1, that the first `page=` of a PDF fragment identifier gives, its
    parameters joined with `&`; None where the location gives none or follows another syntax,
    and the quote is then sought in the whole text."""
    if location is None or location.conforms_to not in PDF:
        return None
    for parameter in location.value.split("&"):
        name, _, value = parameter.partition("=")
        if name == "page" and value.isascii() and value.isdigit():
            return int(value)
    return None


def paper(doi: str, version: int | None = None) -> Paper | None:
    """The paper of `doi` in the cache, at `version` where one is given; None where it isn't
    there."""
    cached = PaperCache().get(doi, version)
    return None if cached is None else _paper(cached)


def add_paper(
    doi: str, version: int | None = None, pdf: str | os.PathLike[str] | None = None
) -> Paper:
    """Put the paper of `doi` in the cache and give it: the PDF at `pdf`, or, with none, the one
    arXiv has for an arXiv DOI. One already there is given as it is. Raises PaperError where no
    PDF can be got or the file isn't a PDF, and OSError where `pdf` can't be read."""
    cache = PaperCache()
    cached = cache.get(doi, version)
    if cached is not None:
        return _paper(cached)
    try:
        if pdf is not None:
            return _paper(cache.add_from_file(doi, Path(pdf), version=version))
        from astra._internal.papers.download import download_paper

        got = download_paper(doi, version)
        if not got.success or got.content is None:
            raise PaperError(got.error or f"no PDF was got for {doi}")
        return _paper(
            cache.add(
                doi=doi,
                pdf_content=got.content,
                version=version,
                title=got.title,
                authors=got.authors,
                source_url=got.url,
            )
        )
    except ValueError as error:  # what the cache raises for bytes that aren't a PDF
        raise PaperError(str(error)) from None


def verify_quote(
    doi: str,
    quote: TextQuoteSelector,
    version: int | None = None,
    location: FragmentSelector | None = None,
) -> QuoteStatus:
    """Whether `quote` is in the cached paper of `doi`, and on the page `location` gives where
    it gives one. The match allows for what extracting a PDF's text changes, and a `prefix` or
    `suffix` tells one passage from another like it. Raises PaperError where the PDF's text
    can't be read."""
    cached = PaperCache().get(doi, version)
    if cached is None:
        return QuoteStatus("no_paper")
    file = cached.pdf_path.stat()
    try:
        pdf = _text(cached.pdf_path, file.st_size, file.st_mtime_ns)
    except Exception as error:  # a damaged PDF fails in as many ways as pypdf has parsers
        raise PaperError(f"the paper of {doi} in the cache can't be read: {error}") from error
    expected = page(location)
    found = pdf.find_quote(quote.exact, page=expected, prefix=quote.prefix, suffix=quote.suffix)
    if not found:
        return QuoteStatus("not_found")
    return QuoteStatus("found" if expected in (None, found[0]) else "elsewhere", found[0])


@functools.lru_cache(maxsize=8)
def _text(pdf: Path, size: int, mtime_ns: int) -> PDFDocument:
    """The text of the PDF at `pdf`, as it is with that size and modification time: read once
    in a process, however many quotes are sought in it."""
    from astra._internal.papers.pdf import extract_text_from_pdf

    return extract_text_from_pdf(pdf)


def _paper(cached: CachedPaper) -> Paper:
    metadata = cached.metadata
    return Paper(
        metadata.doi,
        str(cached.pdf_path.resolve()),
        f"sha256:{metadata.sha256}",
        metadata.retrieved_at,
        metadata.version,
        metadata.title,
        tuple(metadata.authors or ()),
        metadata.source_url,
    )
