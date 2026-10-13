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
from lcat.xlsx_style import CellStyle, StyledCell
from lcat.loaders import (
    CodeDoc,
    Document,
    ImageDoc,
    MarkdownDoc,
    PdfDoc,
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


CANVAS = "#1a1a1a on #ffffff"
"""A coloured sheet is drawn on its own sheet of paper, so the workbook's colours mean
what they mean in Excel rather than fighting the terminal's theme."""

HEADER = "bold #1a1a1a on #e8e8e8"


def render(doc: Document, console: Console | None = None) -> None:
    console = console or Console(width=_width())

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

    if isinstance(doc, PdfDoc):
        _render_pdf(doc, console)
        return

    raise TypeError(f"cannot render {type(doc).__name__}")


def _render_sheet(sheet: SheetDoc, console: Console) -> None:
    # A sheet name is arbitrary text; printed as markup, a "[" in one would break it.
    console.print(sheet.name, style="bold")
    _render_table(
        sheet.columns,
        sheet.rows,
        sheet.total_rows,
        console,
        styles=sheet.styles,
        column_styles=sheet.column_styles,
        widths=sheet.widths,
        canvas=sheet.colored,
    )


def _render_table(
    columns: list[str],
    rows: list[list[str]],
    total_rows: int | None,
    console: Console,
    *,
    styles: list[list[CellStyle]] | None = None,
    column_styles: list[CellStyle] | None = None,
    widths: list[int | None] | None = None,
    canvas: bool = False,
) -> None:
    """Print one table. Without the keyword arguments this is the plain CSV/JSON table;
    with them it is a worksheet, drawn the way the workbook asks."""
    if not columns:
        console.print("[dim](empty table)[/dim]")
        return
    table = Table(
        box=box.SIMPLE,
        header_style=HEADER if canvas else "bold",
        border_style=CANVAS if canvas else None,
        style=CANVAS if canvas else "",
        # row_styles composes *under* each cell's own style, so an unstyled cell picks
        # up the paper and a filled one keeps its fill.
        row_styles=[CANVAS] if canvas else None,
        pad_edge=False,
    )
    for index, name in enumerate(columns):
        header = name
        if column_styles and index < len(column_styles):
            header = StyledCell(name, column_styles[index])
        width = widths[index] if widths and index < len(widths) else None
        table.add_column(header, overflow="fold", width=width)
    if styles is None:
        for row in rows:
            table.add_row(*row)
    else:
        for row, row_styles in zip(rows, styles):
            table.add_row(
                *(StyledCell(cell, style) for cell, style in zip(row, row_styles))
            )
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


def _render_pdf(doc: PdfDoc, console: Console) -> None:
    """The text of every page, with a rule between pages. Pictures of pages would be
    no use to a pipe, and on a terminal the text is what `cat` would give you."""
    for index in range(doc.page_count):
        if index:
            console.rule(f"page {index + 1}", style="dim")
        text = doc.page_text(index)
        if text:
            console.print(text, markup=False, highlight=False)
        else:
            console.print("(no text on this page)", style="dim")
