"""`llm-router catalog` — inspect the full detected/hand-added catalog."""

from typing import Optional

import typer

from ..config import CLI_CONTEXT_SETTINGS
from ._common import console, print_table

app = typer.Typer(
    name="catalog",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command("list")
def catalog_list(
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Filter models by provider name"
    ),
):
    """List the full provider + model catalog."""
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Model, Provider

    with session_scope() as session:
        provider_rows = [
            (p.name, p.prefix, p.base_url, "yes" if p.api_key else "no", p.active)
            for p in session.exec(select(Provider).order_by(Provider.name)).all()
        ]
        model_rows = [
            (m.model, p.name, p.prefix)
            for m, p in session.exec(
                select(Model, Provider)
                .join(Provider, Model.provider_id == Provider.id)
                .order_by(Provider.name, Model.model)
            ).all()
            if provider is None or p.name == provider
        ]

    print_table(
        "Providers",
        ["name", "prefix", "base_url", "key?", "active"],
        provider_rows,
    )

    if model_rows:
        print_table(
            "Models",
            ["model", "provider", "prefix"],
            model_rows,
        )
    else:
        console.print("[yellow]No models in catalog.[/yellow]")
