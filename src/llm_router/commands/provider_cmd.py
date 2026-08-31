"""`llm-router provider` — inspect and manage providers."""

from typing import Optional

import typer

from ..config import CLI_CONTEXT_SETTINGS
from ._common import console, print_table

app = typer.Typer(
    name="provider",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command("list")
def provider_list():
    """List all registered providers."""
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Provider

    with session_scope() as session:
        cols = ["id", "name", "prefix", "base_url", "key?", "active"]
        data = [
            (p.id, p.name, p.prefix, p.base_url, "yes" if p.api_key else "no", p.active)
            for p in session.exec(select(Provider).order_by(Provider.name)).all()
        ]
    if not data:
        console.print(
            "[yellow]No providers registered. Run `llm-router scan`.[/yellow]"
        )
        return
    print_table("Providers", cols, data)


@app.command("add")
def provider_add(
    name: str = typer.Argument(..., help="Display name, e.g. 'openai'"),
    prefix: str = typer.Argument(..., help="Short key used in chains, e.g. 'openai'"),
    base_url: str = typer.Argument(
        ..., help="Base URL of the OpenAI-compatible endpoint"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="API key (cloud only)"
    ),
):
    """Manually add (or update) a provider by prefix."""
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Provider

    with session_scope() as session:
        existing = session.exec(
            select(Provider).where(Provider.prefix == prefix)
        ).first()
        if existing is None:
            existing = Provider(prefix=prefix)
            session.add(existing)
            verb = "Added"
        else:
            verb = "Updated"
        existing.name = name
        existing.base_url = base_url
        if api_key is not None:
            existing.api_key = api_key
        console.print(f"[green]{verb} provider '{prefix}'.[/green]")
