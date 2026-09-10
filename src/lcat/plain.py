"""Static, pipe-friendly rendering for when stdout is not a terminal."""

from __future__ import annotations

import os
import shutil
import sys

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table

from lcat.images import natural_cells
from lcat.loaders import (
    CodeDoc,
    Document,
    ImageDoc,
    MarkdownDoc,
    SheetDoc,
    TableDoc,
    WorkbookDoc,
)


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

    if isinstance(doc, ImageDoc):
        _render_image(doc, console)
        return

    if isinstance(doc, TableDoc):
        _render_table(doc.columns, doc.rows, doc.total_rows, console)
        return

    if isinstance(doc, WorkbookDoc):
        # Every sheet, one after another: a pipe has no keys to switch between them.
        for index, sheet in enumerate(doc.sheets):
            if index:
                console.print()
            _render_sheet(sheet, console)
        return

    raise TypeError(f"cannot render {type(doc).__name__}")


def _render_sheet(sheet: SheetDoc, console: Console) -> None:
    # A sheet name is arbitrary text; printed as markup, a "[" in one would break it.
    console.print(sheet.name, style="bold")
    _render_table(sheet.columns, sheet.rows, sheet.total_rows, console)


def _render_table(
    columns: list[str],
    rows: list[list[str]],
    total_rows: int | None,
    console: Console,
) -> None:
    if not columns:
        console.print("[dim](empty table)[/dim]")
        return
    table = Table(box=box.SIMPLE, header_style="bold", pad_edge=False)
    for name in columns:
        table.add_column(name, overflow="fold")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    if total_rows is not None:
        console.print(f"[dim]... {total_rows - len(rows):,} more rows[/dim]")


def _render_image(doc: ImageDoc, console: Console) -> None:
    """Inline pixels on a terminal (`lcat -p photo.png`), a one-line summary in a pipe."""
    width, height = doc.size
    name = doc.path.name if doc.path else "stdin"
    if not sys.stdout.isatty():
        console.print(f"{name}: {doc.format} image, {width}×{height} px")
        return

    # Importing textual_image asks the terminal which graphics protocol it speaks.
    from textual_image.renderable import Image

    cells_wide, _ = natural_cells(width, height)
    console.print(Image(doc.image, width=min(cells_wide, console.width), height="auto"))
