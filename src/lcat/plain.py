"""Static, pipe-friendly rendering for when stdout is not a terminal."""

from __future__ import annotations

import os
import shutil

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table

from lcat.loaders import CodeDoc, Document, MarkdownDoc, TableDoc


def _width() -> int:
    env = os.environ.get("COLUMNS")
    if env and env.isdigit():
        return int(env)
    size = shutil.get_terminal_size(fallback=(0, 0))
    return size.columns or 100


def render(doc: Document) -> None:
    console = Console(width=_width())

    if isinstance(doc, MarkdownDoc):
        console.print(Markdown(doc.text))
        return

    if isinstance(doc, CodeDoc):
        console.print(
            Syntax(doc.text, doc.lexer, theme="ansi_dark", background_color="default")
        )
        return

    if isinstance(doc, TableDoc):
        if not doc.columns:
            console.print("[dim](empty table)[/dim]")
            return
        table = Table(box=box.SIMPLE, header_style="bold", pad_edge=False)
        for name in doc.columns:
            table.add_column(name, overflow="fold")
        for row in doc.rows:
            table.add_row(*row)
        console.print(table)
        if doc.total_rows is not None:
            hidden = doc.total_rows - len(doc.rows)
            console.print(f"[dim]... {hidden:,} more rows[/dim]")
        return

    raise TypeError(f"cannot render {type(doc).__name__}")
