"""`llm-router key` — manage API keys for router authentication.

Keys are managed exclusively via this local CLI with direct database access.
There is NO API endpoint for key management (security design).
"""

from typing import Optional

import typer
from rich.table import Table

from ..config import CLI_CONTEXT_SETTINGS
from ._common import console, get_session

app = typer.Typer(
    name="key",
    help="Manage API keys for router authentication.",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command("generate")
def key_generate(
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Optional label for the key"
    ),
):
    """Generate a new API key.

    The raw key is shown ONCE and cannot be retrieved later.
    Store it securely (e.g., in ~/.config/tt or environment variables).
    """
    from ..core.api_key import create_api_key

    with get_session() as session:
        api_key = create_api_key(session, name=name)

    console.print("\n[green]✓ API key created successfully![/green]\n")
    console.print("[bold]Save this key now - it will NOT be shown again:[/bold]\n")
    console.print(f"  [cyan]{api_key.key}[/cyan]\n")
    console.print(f"  Key ID:    {api_key.id}")
    if api_key.name:
        console.print(f"  Name:      {api_key.name}")
    console.print()


@app.command("list")
def key_list():
    """List all registered API keys (with their full plaintext values)."""
    from ..core.api_key import list_api_keys

    with get_session() as session:
        keys = list_api_keys(session)

    if not keys:
        console.print("[yellow]No API keys registered.[/yellow]")
        console.print("Generate one with: llm-router key generate")
        return

    table = Table(title="API Keys")
    table.add_column("ID", style="dim")
    table.add_column("Key", style="cyan")
    table.add_column("Name")
    table.add_column("Active")
    table.add_column("Created", style="dim")
    table.add_column("Last Used", style="dim")

    for key in keys:
        active_style = "green" if key.active else "red"
        active_text = "✓" if key.active else "✗"
        if key.last_used_at:
            last_used = key.last_used_at.strftime("%Y-%m-%d %H:%M")
        else:
            last_used = "never"

        table.add_row(
            str(key.id),
            key.key,
            key.name or "-",
            f"[{active_style}]{active_text}[/{active_style}]",
            key.created_at.strftime("%Y-%m-%d %H:%M"),
            last_used,
        )

    console.print(table)


@app.command("revoke")
def key_revoke(
    key_id: int = typer.Argument(..., help="ID of the key to revoke"),
    no_interaction: bool = typer.Option(
        False, "--no-interaction", "-n", help="Skip confirmation prompt"
    ),
):
    """Revoke an API key (sets it inactive, can be re-enabled)."""
    from ..core.api_key import revoke_api_key

    if not no_interaction:
        from ..utils import confirm

        if not confirm(f"Revoke API key {key_id}?", default=False):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    with get_session() as session:
        success = revoke_api_key(session, key_id)

    if success:
        console.print(f"[green]✓ API key {key_id} revoked.[/green]")
    else:
        console.print(f"[red]✗ API key {key_id} not found.[/red]")
        raise typer.Exit(1)


@app.command("delete")
def key_delete(
    key_id: int = typer.Argument(..., help="ID of the key to permanently delete"),
    no_interaction: bool = typer.Option(
        False, "--no-interaction", "-n", help="Skip confirmation prompt"
    ),
):
    """Permanently delete an API key from the database.

    This is irreversible. Use `revoke` to temporarily disable a key.
    """
    from ..core.api_key import delete_api_key

    if not no_interaction:
        from ..utils import confirm

        if not confirm(
            f"PERMANENTLY delete API key {key_id}?\nThis cannot be undone.",
            default=False,
        ):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    with get_session() as session:
        success = delete_api_key(session, key_id)

    if success:
        console.print(f"[green]✓ API key {key_id} deleted.[/green]")
    else:
        console.print(f"[red]✗ API key {key_id} not found.[/red]")
        raise typer.Exit(1)
