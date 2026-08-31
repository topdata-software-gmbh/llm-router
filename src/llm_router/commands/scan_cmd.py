"""`llm-router scan` — re-run detection and persist the catalog."""

import typer

from ..config import CLI_CONTEXT_SETTINGS
from ..core.detect import scan as detect_scan
from ._common import console, print_table

app = typer.Typer(
    name="scan",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect but do not persist"),
):
    """Scan the environment (env keys, local ports, ollama) for providers/models."""
    result = detect_scan()
    console.print(
        f"[bold]Detected {len(result.providers)} provider(s), "
        f"{len(result.models)} model(s).[/bold]"
    )
    if result.providers:
        print_table(
            "Providers",
            ["name", "prefix", "base_url", "key?"],
            [
                (p.name, p.prefix, p.base_url, "yes" if p.api_key else "no")
                for p in result.providers
            ],
        )
    if result.models:
        print_table(
            "Models",
            ["provider", "model"],
            [(m.provider, m.model) for m in result.models],
        )
    if dry_run:
        return
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Model, Provider

    with session_scope() as session:
        existing = {p.prefix for p in session.exec(select(Provider)).all()}
        added = 0
        for prov in result.providers:
            if prov.prefix in existing:
                continue
            session.add(
                Provider(
                    name=prov.name,
                    prefix=prov.prefix,
                    base_url=prov.base_url,
                    api_key=prov.api_key,
                )
            )
            existing.add(prov.prefix)
            added += 1
        ollama = session.exec(
            select(Provider).where(Provider.prefix == "ollama")
        ).first()
        if ollama is not None:
            known = {
                m.model
                for m in session.exec(
                    select(Model).where(Model.provider_id == ollama.id)
                ).all()
            }
            for dm in result.models:
                if dm.model in known:
                    continue
                session.add(Model(provider_id=ollama.id, model=dm.model))
                known.add(dm.model)
        console.print(f"[green]Persisted {added} new provider(s).[/green]")
