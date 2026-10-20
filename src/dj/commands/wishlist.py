"""`dj wishlist ...`: what the DJ still has to buy (R-803). Writes text files only.

Offline: reads the newest plan and the pulled inbox of a link, never Spotify, never rekordbox.
"""

from __future__ import annotations

import json
from datetime import date

import typer

from dj import intake, libfolder, shopping

EXIT_ERROR = 1

wishlist_app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
    help="Tracks you don't own yet, with where to buy them. Writes text files only: "
         "never rekordbox, never Spotify.",
)  # fmt: skip


@wishlist_app.command()
def shop(
    link: str = typer.Argument(..., help="A link from links.yaml (its spotify or crate value)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """wishlist/<crate>.shopping.md from the MISSING tracks of the link's newest plan.

    Run `dj plan <link>` first. Beatport and Bandcamp search links, label when Spotify sends
    one. The file is generated: every run rewrites it. In a library folder the run appends a
    line to log.md.
    """
    paths = intake.default_paths()
    try:
        lnk = intake.resolve_link(link, paths)
        result = shopping.shop(
            paths.root, plans=paths.plans, inbox=paths.inbox / f"{lnk.slug}.json",
            wishlist=paths.wishlist, crate=lnk.crate, spotify=lnk.spotify, slug=lnk.slug,
            library=paths.library, today=date.today(),
        )  # fmt: skip
    except (intake.IntakeError, shopping.ShoppingError, libfolder.LibraryFolderError, OSError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)

    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    labels = ", ".join(f"{x['label']} ({x['tracks']})" for x in result["labels"]) or "none from Spotify"
    typer.echo(f"{result['missing']} missing  ({lnk.spotify} -> {lnk.crate})")
    if result["stale_plan"]:
        typer.echo("OUT OF DATE: pulled after the newest plan. Run `dj plan` for this link, then this again.")
    typer.echo(f"top labels: {labels}")
    typer.echo(f"shopping list: {result['file']}")
    if result["log"]:
        typer.echo(f"log.md: {result['log']}")
