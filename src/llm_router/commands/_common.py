"""Shared CLI helpers: session management and output formatting."""

from typing import List

from rich.console import Console
from sqlmodel import Session

from ..db import engine

console = Console()


def get_session() -> Session:
    return Session(engine)


def print_table(title: str, columns: List[str], rows: List[tuple]) -> None:
    from rich.table import Table

    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)
