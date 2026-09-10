"""llm-router Typer CLI entry point.

Run ``llm-router --help`` (or ``-h``) for the available subcommands:
``scan``, ``provider``, ``assignment``, ``catalog``, ``resolve``.
"""

import typer

from .commands import assignment_cmd, catalog_cmd, provider_cmd, scan_cmd
from .config import CLI_CONTEXT_SETTINGS

app = typer.Typer(
    name="llm-router",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)

app.add_typer(scan_cmd.app, name="scan")
app.add_typer(provider_cmd.app, name="provider")
app.add_typer(assignment_cmd.app, name="assignment")
app.add_typer(catalog_cmd.app, name="catalog")


@app.command()
def resolve(purpose: str):
    """Resolve a purpose to its ordered provider/model connection chain.

    Example: llm-router resolve git-digest:digest
    """
    from .commands._common import get_session
    from .core.resolve import ResolveError, resolve_purpose

    with get_session() as session:
        try:
            chain = resolve_purpose(session, purpose)
        except ResolveError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
    if chain is None:
        typer.echo(
            f"No assignment for purpose {purpose!r}. "
            f"Run `llm-router assignment set {purpose} <owner> <chain>`.",
            err=True,
        )
        raise typer.Exit(1)
    for entry in chain:
        typer.echo(
            f"{entry['provider']}/{entry['model']}  "
            f"[{entry['base_url']}] key={'yes' if entry['api_key'] else 'no'}"
        )


if __name__ == "__main__":
    app()
