"""Papers: a work that evidence cites by its DOI, kept as a PDF in the paper cache, and whether
a quote is in one.

The paper cache is a folder of this machine, outside every repository, and matching a quote
against a PDF's text is astra-tools' own: the specification has no rule on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Paper:
    """A paper in the cache."""

    doi: str
    pdf_path: str  # its PDF, as an absolute path
    content_hash: str  # of the PDF's bytes, as a record gives a hash: `sha256:<hex>`
    retrieved: str  # when it was put in the cache, in UTC
    version: int | None = None  # the version of an arXiv paper
    title: str | None = None
    authors: tuple[str, ...] = ()
    source_url: str | None = None  # where the PDF was got from


@dataclass(frozen=True)
class QuoteStatus:
    """Whether a quote is in the paper it is said to be in."""

    state: Literal["found", "elsewhere", "not_found", "no_paper"]  # `elsewhere`: in the paper,
    # but not on the page its location gives; `no_paper`: the paper isn't in the cache
    page: int | None = None  # the page it is on, from 1, where it is in the paper
