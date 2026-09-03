"""`llm-router assignment` — manage purpose -> chain mappings."""

import typer
from typing_extensions import Annotated

from ..config import CLI_CONTEXT_SETTINGS
from ._common import console, print_table

app = typer.Typer(
    name="assignment",
    help="Manage purpose-to-chain assignments.",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command("list")
def assignment_list(
    owner: Annotated[str | None, typer.Option(help="Filter by owner namespace")] = None,
):
    """List assignments, optionally filtered by owner."""
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Assignment

    with session_scope() as session:
        q = select(Assignment)
        if owner:
            q = q.where(Assignment.owner == owner)
        cols = ["key", "owner", "chain", "active"]
        data = [
            (a.key, a.owner, a.chain, a.active)
            for a in session.exec(q.order_by(Assignment.owner, Assignment.key)).all()
        ]
    if not data:
        console.print("[yellow]No assignments.[/yellow]")
        return
    print_table("Assignments", cols, data)


@app.command("set")
def assignment_set(
    purpose: Annotated[
        str, typer.Argument(help="Purpose key, e.g. 'git-digest:digest'")
    ],
    owner: Annotated[str, typer.Argument(help="Owner namespace, e.g. 'git-digest'")],
    chain: Annotated[
        str,
        typer.Argument(
            help="Ordered chain, comma-separated 'provider/model', primary first",
        ),
    ],
    description: Annotated[
        str | None, typer.Option(help="Optional description")
    ] = None,
):
    """Set (upsert) an assignment's ordered chain of provider/model entries."""
    import json

    entries = [e.strip() for e in chain.split(",") if e.strip()]
    if not entries:
        console.print(
            "[red]Chain must contain at least one provider/model entry.[/red]"
        )
        raise typer.Exit(1)
    from sqlmodel import select

    from ..db import session_scope
    from ..models import Assignment

    with session_scope() as session:
        existing = session.exec(
            select(Assignment).where(Assignment.key == purpose)
        ).first()
        if existing is None:
            existing = Assignment(key=purpose)
            session.add(existing)
            verb = "Created"
        else:
            verb = "Updated"
        existing.owner = owner
        existing.description = description
        existing.chain = json.dumps(entries)
        console.print(f"[green]{verb} assignment {purpose!r} -> {entries}[/green]")
