"""`astra paper add|list|show|path|remove|fetch-metadata|verify-quotes|verify-quote`: the
papers that evidence cites by DOI, kept in the paper cache, and quotes sought in them."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from astra.model.paper import QuoteStatus
    from astra.model.resolved_analysis import FragmentSelector, TextQuoteSelector


@click.group("paper")
def command() -> None:
    """Paper management commands for evidence verification."""
    pass


@command.command("add")
@click.argument("doi")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
@click.option(
    "--pdf",
    type=click.Path(exists=True, path_type=Path),
    help="Use local PDF instead of downloading",
)
def paper_add(doi: str, version: int | None, pdf: Path | None) -> None:
    """Add a paper to the cache by DOI.

    An arXiv paper is downloaded from arXiv: give its DOI in the format
    10.48550/arXiv.2008.03833. No other paper is downloaded: give its PDF
    with --pdf.

    \b
    Examples:
        astra paper add 10.48550/arXiv.2008.03833
        astra paper add 10.48550/arXiv.1706.03762 --version 7
        astra paper add 10.1234/example --pdf ./local_paper.pdf
    """
    from astra import api
    from astra.cli import FAILED, environment
    from astra.cli.text import console as _console

    console = _console()
    with environment():
        paper = api.paper(doi, version=version)
        if paper is not None:
            console.print(f"[yellow]Paper already cached:[/yellow] {doi}")
        else:
            if pdf is None:
                console.print(f"Downloading paper: [cyan]{doi}[/cyan]")
            try:
                paper = api.add_paper(doi, version=version, pdf=pdf)
            except api.PaperError as error:
                console.print(f"[red]Error:[/red] {error}")
                raise click.exceptions.Exit(FAILED) from None
            console.print("[green]✓[/green] Paper added to cache")
    if paper.version:
        console.print(f"  Version: {paper.version}")
    if paper.title:
        console.print(f"  Title: {paper.title}")
    console.print(f"  Path: {paper.pdf_path}")
    console.print(f"  SHA-256: {paper.content_hash.removeprefix('sha256:')}")


@command.command("list")
def paper_list() -> None:
    """List all cached papers."""
    from astra.cli.text import Table
    from astra.cli.text import console as _console

    console = _console()
    from astra._internal.papers.cache import PaperCache

    cache = PaperCache()
    papers = cache.list_papers()

    if not papers:
        console.print("[dim]No papers cached[/dim]")
        return

    table = Table(show_header=True, expand=True)
    table.add_column("DOI", no_wrap=True)
    table.add_column("Ver", no_wrap=True)
    table.add_column("Title", ratio=2)
    table.add_column("Retrieved", no_wrap=True)

    for paper in papers:
        meta = paper.metadata
        version_str = str(meta.version) if meta.version else "-"
        title = meta.title or "[dim](unknown)[/dim]"
        retrieved = meta.retrieved_at[:10] if meta.retrieved_at else "-"
        table.add_row(meta.doi, version_str, title, retrieved)

    console.print(table)
    console.print(f"\n[dim]{len(papers)} paper(s) cached[/dim]")


@command.command("show")
@click.argument("doi")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
def paper_show(doi: str, version: int | None) -> None:
    """Show details of a cached paper."""
    from astra.cli.text import console as _console

    console = _console()
    from astra._internal.papers.cache import PaperCache

    cache = PaperCache()
    paper = cache.get(doi, version)

    if not paper:
        console.print(f"[red]Error:[/red] Paper not found in cache: {doi}")
        if version:
            console.print(f"  (version {version})")
        console.print("\nUse [cyan]astra paper add[/cyan] to download the paper first.")
        raise SystemExit(1)

    meta = paper.metadata
    console.print(f"\n[bold]DOI:[/bold] {meta.doi}")
    if meta.version:
        console.print(f"[bold]Version:[/bold] {meta.version}")
    if meta.title:
        console.print(f"[bold]Title:[/bold] {meta.title}")
    if meta.authors:
        console.print(f"[bold]Authors:[/bold] {', '.join(meta.authors)}")
    console.print(f"[bold]SHA-256:[/bold] {meta.sha256}")
    console.print(f"[bold]Retrieved:[/bold] {meta.retrieved_at}")
    if meta.source_url:
        console.print(f"[bold]Source:[/bold] {meta.source_url}")
    console.print(f"[bold]Path:[/bold] {paper.pdf_path}")


@command.command("path")
@click.argument("doi")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
def paper_path(doi: str, version: int | None) -> None:
    """Print the path to a cached paper's PDF.

    Useful for piping to other tools or agents that need to read the PDF.
    """
    from astra.cli.text import console as _console

    console = _console()
    from astra._internal.papers.cache import PaperCache

    cache = PaperCache()
    path = cache.get_path(doi, version)

    if not path:
        console.print(f"[red]Error:[/red] Paper not found: {doi}")
        raise SystemExit(1)

    # Print just the path (no formatting) for easy piping
    print(path)


@command.command("remove")
@click.argument("doi")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
def paper_remove(doi: str, version: int | None) -> None:
    """Remove a paper from the cache."""
    from astra.cli.text import console as _console

    console = _console()
    from astra._internal.papers.cache import PaperCache

    cache = PaperCache()

    if not cache.has(doi, version):
        console.print(f"[red]Error:[/red] Paper not found: {doi}")
        raise SystemExit(1)

    cache.remove(doi, version)
    console.print("[green]✓[/green] Paper removed from cache")


@command.command("fetch-metadata")
@click.argument("doi", required=False)
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
@click.option("--all", "fetch_all", is_flag=True, help="Fetch metadata for all cached papers")
def paper_fetch_metadata(doi: str | None, version: int | None, fetch_all: bool) -> None:
    """Fetch metadata (title, authors) for cached papers.

    Uses DOI content negotiation to retrieve metadata from DOI.org.

    Examples:

        astra paper fetch-metadata 10.48550/arXiv.1706.03762

        astra paper fetch-metadata --all
    """
    from astra.cli.text import console as _console

    console = _console()
    from astra._internal.papers.cache import PaperCache
    from astra._internal.papers.download import fetch_doi_metadata

    cache = PaperCache()

    if fetch_all:
        papers = cache.list_papers()
        if not papers:
            console.print("[dim]No papers cached[/dim]")
            return

        updated = 0
        for paper in papers:
            meta = paper.metadata
            if meta.title and meta.authors:
                continue

            console.print(f"Fetching metadata for {meta.doi}...", end=" ")
            doi_meta = fetch_doi_metadata(meta.doi)

            if doi_meta.title or doi_meta.authors:
                cache.update_metadata(
                    meta.doi,
                    meta.version,
                    title=doi_meta.title,
                    authors=doi_meta.authors,
                )
                console.print(f"[green]✓[/green] {doi_meta.title or '(no title)'}")
                updated += 1
            else:
                console.print("[yellow]⚠[/yellow] No metadata found")

        console.print(f"\n[dim]Updated {updated} paper(s)[/dim]")
        return

    if not doi:
        console.print("[red]Error:[/red] Provide a DOI or use --all")
        raise SystemExit(1)

    if not cache.has(doi, version):
        console.print(f"[red]Error:[/red] Paper not found in cache: {doi}")
        raise SystemExit(1)

    console.print(f"Fetching metadata for {doi}...")
    doi_meta = fetch_doi_metadata(doi)

    if not doi_meta.title and not doi_meta.authors:
        console.print("[yellow]⚠[/yellow] No metadata found for this DOI")
        raise SystemExit(1)

    cache.update_metadata(doi, version, title=doi_meta.title, authors=doi_meta.authors)

    console.print("[green]✓[/green] Metadata updated:")
    if doi_meta.title:
        console.print(f"  Title: {doi_meta.title}")
    if doi_meta.authors:
        console.print(f"  Authors: {', '.join(doi_meta.authors)}")


@command.command("verify-quotes")
@click.argument("doi")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
def paper_verify_quotes(doi: str, version: int | None) -> None:
    """Verify several quotes from a cached paper in one go.

    Reads a JSON list from stdin, an item for each quote: the `quote` of an evidence item and,
    where it has one, its `location`, as astra.yaml writes them.

    \b
        [{"quote": {"exact": "...", "prefix": "...", "suffix": "..."},
          "location": {"value": "page=6"}}]

    Prints a JSON list of each quote's status, in the same order, as `astra.api.verify_quote`
    gives it: its `state` (found, elsewhere, not_found or no_paper) and, where the quote is in
    the paper, the `page` it is on.

    \b
    Exit codes:
      0 - Every quote is found
      1 - One isn't found, or isn't on the page its location gives, or the paper isn't cached
      2 - The input isn't such a list, or the paper's text can't be read
    """
    from astra import api
    from astra.cli import FAILED, fail, write_json
    from astra.model import to_json

    try:
        quotes = [
            (
                api.TextQuoteSelector(**item["quote"]),
                api.FragmentSelector(**item["location"]) if "location" in item else None,
            )
            for item in json.loads(sys.stdin.read())
        ]
    except (ValueError, TypeError, KeyError) as error:
        fail(f"the input isn't a JSON list of quotes, each with a `quote`: {error}")
    statuses = tuple(_status(doi, quote, version, location) for quote, location in quotes)
    write_json(to_json(statuses))
    if any(status.state != "found" for status in statuses):
        raise click.exceptions.Exit(FAILED)


@command.command("verify-quote")
@click.argument("doi")
@click.option("--quote", "-q", required=True, help="Exact quote text to verify")
@click.option("--version", "-v", type=int, help="Paper version (for arXiv papers)")
@click.option("--page", "-p", type=int, help="The page the quote is on, counted from 1")
@click.option("--json", "as_json", is_flag=True, help="Print the status as JSON.")
def paper_verify_quote(
    doi: str, quote: str, version: int | None, page: int | None, as_json: bool
) -> None:
    """Verify a quote exists in a cached paper.

    Seeks the quote in the paper's text, allowing for what extracting a PDF's text changes.
    With --page, the quote is to be on that page. With --json, the status is printed as
    `astra.api.verify_quote` gives it: its `state` (found, elsewhere, not_found or no_paper)
    and, where the quote is in the paper, the `page` it is on.

    \b
    Exit codes:
      0 - The quote is found
      1 - It isn't found, or isn't on --page, or the paper isn't cached
      2 - The paper's text can't be read
    """
    from astra import api
    from astra.cli import FAILED, write_json
    from astra.model import to_json

    location = None if page is None else api.FragmentSelector(f"page={page}")
    status = _status(doi, api.TextQuoteSelector(quote), version, location)
    if as_json:
        write_json(to_json(status))
    else:
        from astra.cli.text import console

        shown = {
            "found": f"[green]✓ Found[/green] on page {status.page}",
            "elsewhere": f"[red]✗ Not on page {page}[/red]: the quote is on page {status.page}",
            "not_found": "[red]✗ Not found[/red] in the paper",
            "no_paper": f"[red]✗ No paper[/red]: run [cyan]astra paper add {doi}[/cyan] first",
        }
        console().print(shown[status.state])
    if status.state != "found":
        raise click.exceptions.Exit(FAILED)


def _status(
    doi: str, quote: TextQuoteSelector, version: int | None, location: FragmentSelector | None
) -> QuoteStatus:
    """The status of `quote` in the cached paper of `doi`; stops with exit 2 where the paper's
    text can't be read or the cache can't be used."""
    from astra import api
    from astra.cli import environment, fail

    with environment():
        try:
            return api.verify_quote(doi, quote, version=version, location=location)
        except api.PaperError as error:
            fail(str(error))
