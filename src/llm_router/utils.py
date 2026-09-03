"""Shared utilities for the llm-router CLI."""

import sys

from InquirerPy import get_style, inquirer

INQUIRER_CONFIRM_STYLE = get_style(
    {
        "question": "#ffffff bold",
        "pointer": "#FF9D00 bold",
        "highlighted": "#000000 bg:#FF9D00 bold",
        "instruction": "#808080",
        "text": "#ffffff",
    }
)

CONFIRM_CHOICES = [
    {"name": " Yes ", "value": True},
    {"name": " No  ", "value": False},
]


def confirm(message: str, default: bool = True) -> bool:
    """Ask a Yes/No question with a gum-style button UI.

    Falls back to `default` when no TTY is available (piped/CI input).
    """
    if not sys.stdin.isatty():
        return default
    return inquirer.select(
        message=message,
        choices=CONFIRM_CHOICES,
        default=" Yes " if default else " No  ",
        style=INQUIRER_CONFIRM_STYLE,
        qmark="",
        amark="",
    ).execute()
