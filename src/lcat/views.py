"""The interactive views: markdown, table and code."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys

from rich.syntax import Syntax
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, MarkdownViewer, Static

CELL_WIDTH = 60
"""Cells wider than this are truncated for display; `enter` shows the full value."""

FIRST_CHUNK = 500
"""Rows in the first batch, sized to fill a screen quickly."""

CHUNK = 2000
"""Rows added per batch. DataTable measures every cell it is given, so a big file is
streamed in to keep the first screenful fast and the app responsive while it fills."""


def copy_text(app, text: str) -> None:
    """Copy to the clipboard, preferring pbcopy on macOS over OSC 52."""
    app.copy_to_clipboard(text)
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=False)
        except OSError:
            pass


def _truncate(value: str) -> str:
    value = value.replace("\t", " ").replace("\n", " ").replace("\r", "")
    if len(value) > CELL_WIDTH:
        return value[: CELL_WIDTH - 1] + "…"
    return value


def _sort_key(value: str):
    text = value.strip()
    if not text:
        return (2, 0.0, "")
    try:
        return (0, float(text.replace(",", "").replace("%", "")), "")
    except ValueError:
        return (1, 0.0, text.casefold())


class CellModal(ModalScreen[None]):
    """Full, untruncated value of a single cell."""

    BINDINGS = [
        Binding("escape,enter,q", "dismiss", "close"),
    ]

    def __init__(self, column: str, value: str, position: str) -> None:
        super().__init__()
        self._column = column
        self._value = value
        self._position = position

    def compose(self):
        with Vertical(id="cell-dialog"):
            yield Static(f"[b]{self._column}[/b]  [dim]{self._position}[/dim]", id="cell-title")
            with VerticalScroll(id="cell-body"):
                yield Static(self._value or "[dim](empty)[/dim]", id="cell-value")
            yield Static("[dim]esc to close[/dim]", id="cell-hint")


class HelpModal(ModalScreen[None]):
    """Key reference for the active view."""

    BINDINGS = [
        Binding("escape,enter,q,question_mark", "dismiss", "close"),
    ]

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._rows = rows

    def compose(self):
        lines = "\n".join(f"[b]{key:<18}[/b] {desc}" for key, desc in self._rows)
        with Vertical(id="help-dialog"):
            yield Static("[b]lcat keys[/b]", id="help-title")
            with VerticalScroll(id="help-body"):
                yield Static(lines)
            yield Static("[dim]esc to close[/dim]", id="cell-hint")


class MarkdownView(MarkdownViewer, can_focus=True, can_focus_children=True):
    """MarkdownViewer plus vim-style scrolling and a toggleable contents sidebar."""

    BINDINGS = [
        Binding("j", "scroll_down", "down", show=False),
        Binding("k", "scroll_up", "up", show=False),
        Binding("ctrl+d", "page_down", "page down", show=False),
        Binding("ctrl+u", "page_up", "page up", show=False),
        Binding("g", "scroll_home", "top", show=False),
        Binding("G", "scroll_end", "bottom", show=False),
        Binding("t", "toggle_contents", "contents"),
    ]

    HELP = [
        ("up down j k", "scroll a line"),
        ("pgup pgdn ctrl+u ctrl+d", "scroll a page"),
        ("g G home end", "top / bottom"),
        ("t", "toggle the table of contents"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def action_toggle_contents(self) -> None:
        self.show_table_of_contents = not self.show_table_of_contents
        if not self.show_table_of_contents:
            self.focus()


class CodeView(VerticalScroll):
    """Syntax-highlighted text, for JSON that isn't tabular."""

    BINDINGS = [
        Binding("j", "scroll_down", "down", show=False),
        Binding("k", "scroll_up", "up", show=False),
        Binding("ctrl+d", "page_down", "page down", show=False),
        Binding("ctrl+u", "page_up", "page up", show=False),
        Binding("g", "scroll_home", "top", show=False),
        Binding("G", "scroll_end", "bottom", show=False),
    ]

    HELP = [
        ("up down j k", "scroll a line"),
        ("pgup pgdn ctrl+u ctrl+d", "scroll a page"),
        ("g G home end", "top / bottom"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def __init__(self, text: str, lexer: str = "text", id: str | None = None) -> None:
        super().__init__(id=id)
        self._text = text
        self._lexer = lexer

    def compose(self):
        yield Static(
            Syntax(
                self._text,
                self._lexer,
                theme="ansi_dark",
                background_color="default",
                line_numbers=True,
            ),
            id="code",
        )


class TableView(Vertical):
    """A DataTable with cell navigation, search, sorting and copying."""

    BINDINGS = [
        Binding("h", "cursor_left", "left", show=False),
        Binding("l", "cursor_right", "right", show=False),
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("g", "first_row", "top", show=False),
        Binding("G", "last_row", "bottom", show=False),
        Binding("circumflex_accent", "first_column", "first col", show=False),
        Binding("dollar_sign", "last_column", "last col", show=False),
        Binding("slash", "search", "search"),
        Binding("n", "next_match", "next", show=False),
        Binding("N", "prev_match", "prev", show=False),
        Binding("s", "sort", "sort"),
        Binding("y", "copy_cell", "copy cell"),
        Binding("Y", "copy_row", "copy row", show=False),
        Binding("escape", "cancel_search", "cancel", show=False),
    ]

    HELP = [
        ("arrows h j k l", "move the cell cursor"),
        ("pgup pgdn", "scroll a page"),
        ("g G", "first / last row"),
        ("^ $", "first / last column"),
        ("enter", "show the full cell value"),
        ("/", "search cells"),
        ("n N", "next / previous match"),
        ("s", "sort by this column (asc, desc, original)"),
        ("y Y", "copy the cell / the row"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def __init__(
        self, columns: list[str], rows: list[list[str]], id: str | None = None
    ) -> None:
        super().__init__(id=id)
        self.columns = columns
        self.source_rows = rows
        self.view_rows = list(rows)
        self._matches: list[Coordinate] = []
        self._match_index = 0
        self._query = ""
        self._sort_column: int | None = None
        self._sort_state = 0  # 0 original, 1 ascending, 2 descending
        self._loading = False

    def compose(self):
        yield DataTable(id="table", cursor_type="cell", zebra_stripes=True, fixed_columns=1)
        yield Static("", id="status")
        search = Input(placeholder="search cells…", id="search")
        search.display = False
        yield search

    def on_mount(self) -> None:
        table = self.table
        table.add_columns(*self.columns)
        table.focus()
        self._populate()

    def _populate(self) -> None:
        """(Re)fill the table from `view_rows`, streaming if there are many rows."""
        rows = self._display(self.view_rows)
        table = self.table
        table.clear()
        if len(rows) <= FIRST_CHUNK:
            table.add_rows(rows)
            self._loading = False
            self._update_status()
            return
        self._loading = True
        self.run_worker(self._stream_rows(rows), group="load", exclusive=True)

    async def _stream_rows(self, rows: list[list[str]]) -> None:
        table = self.table
        total = len(rows)
        start = 0
        size = FIRST_CHUNK  # a small first batch, so something is on screen at once
        while start < total:
            table.add_rows(rows[start : start + size])
            start += size
            size = CHUNK
            self._update_status(f"loading {min(start, total):,}/{total:,}")
            await asyncio.sleep(0.001)
        self._loading = False
        self._update_status()

    # -- helpers ---------------------------------------------------------

    @property
    def table(self) -> DataTable:
        return self.query_one("#table", DataTable)

    @property
    def search_input(self) -> Input:
        return self.query_one("#search", Input)

    def _display(self, rows: list[list[str]]) -> list[list[str]]:
        return [[_truncate(cell) for cell in row] for row in rows]

    def cell_value(self, coordinate: Coordinate) -> str:
        try:
            return self.view_rows[coordinate.row][coordinate.column]
        except IndexError:
            return ""

    def _update_status(self, note: str = "") -> None:
        if not self.view_rows:
            self.query_one("#status", Static).update("[dim]no rows[/dim]")
            return
        coordinate = self.table.cursor_coordinate
        column = (
            self.columns[coordinate.column]
            if 0 <= coordinate.column < len(self.columns)
            else "?"
        )
        sort_flag = {1: " ↑", 2: " ↓"}.get(
            self._sort_state if self._sort_column == coordinate.column else 0, ""
        )
        parts = [
            f"row {coordinate.row + 1}/{len(self.view_rows)}",
            f"{column}{sort_flag} ({coordinate.column + 1}/{len(self.columns)})",
        ]
        if note:
            parts.append(note)
        self.query_one("#status", Static).update("[dim] · [/dim]".join(parts))

    # -- events ----------------------------------------------------------

    def on_data_table_cell_highlighted(self, _: DataTable.CellHighlighted) -> None:
        self._update_status()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        coordinate = event.coordinate
        if not self.view_rows:
            return
        column = self.columns[coordinate.column]
        position = f"row {coordinate.row + 1}, column {coordinate.column + 1}"
        self.app.push_screen(CellModal(column, self.cell_value(coordinate), position))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._run_search(event.value, announce=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search":
            return
        self._run_search(event.value, announce=True)
        self._hide_search()

    # -- actions ---------------------------------------------------------

    def action_cursor_left(self) -> None:
        self.table.action_cursor_left()

    def action_cursor_right(self) -> None:
        self.table.action_cursor_right()

    def action_cursor_up(self) -> None:
        self.table.action_cursor_up()

    def action_cursor_down(self) -> None:
        self.table.action_cursor_down()

    def action_first_row(self) -> None:
        self.table.move_cursor(row=0)

    def action_last_row(self) -> None:
        self.table.move_cursor(row=max(len(self.view_rows) - 1, 0))

    def action_first_column(self) -> None:
        self.table.move_cursor(column=0)

    def action_last_column(self) -> None:
        self.table.move_cursor(column=max(len(self.columns) - 1, 0))

    def action_search(self) -> None:
        search = self.search_input
        search.display = True
        search.value = self._query
        search.focus()

    def action_cancel_search(self) -> None:
        if self.search_input.display:
            self._hide_search()

    def action_next_match(self) -> None:
        self._step_match(1)

    def action_prev_match(self) -> None:
        self._step_match(-1)

    def action_sort(self) -> None:
        if not self.view_rows:
            return
        coordinate = self.table.cursor_coordinate
        column = coordinate.column
        if column == self._sort_column:
            self._sort_state = (self._sort_state + 1) % 3
        else:
            self._sort_column, self._sort_state = column, 1

        table = self.table
        if self._sort_state == 0:
            self.view_rows = list(self.source_rows)
            self._sort_column = None
            self._populate()
        else:
            reverse = self._sort_state == 2
            # DataTable.sort only reshuffles row positions, so it stays cheap on big
            # files. It sorts from the original insertion order and is stable, which is
            # exactly what sorting source_rows with the same key gives us.
            self.view_rows = sorted(
                self.source_rows,
                key=lambda row: _sort_key(row[column]),
                reverse=reverse,
            )
            table.sort(table.ordered_columns[column].key, key=_sort_key, reverse=reverse)

        table.move_cursor(row=0, column=column)
        if self._query:
            self._run_search(self._query, announce=False)
        self._update_status()

    def action_copy_cell(self) -> None:
        value = self.cell_value(self.table.cursor_coordinate)
        copy_text(self.app, value)
        self.notify(f"copied {len(value)} chars", timeout=2)

    def action_copy_row(self) -> None:
        row = self.table.cursor_coordinate.row
        if not (0 <= row < len(self.view_rows)):
            return
        text = "\t".join(self.view_rows[row])
        copy_text(self.app, text)
        self.notify(f"copied row {row + 1}", timeout=2)

    # -- search ----------------------------------------------------------

    def _hide_search(self) -> None:
        search = self.search_input
        search.display = False
        self.table.focus()

    def _run_search(self, query: str, *, announce: bool) -> None:
        self._query = query
        needle = query.casefold()
        if not needle:
            self._matches = []
            self._update_status()
            return

        self._matches = [
            Coordinate(r, c)
            for r, row in enumerate(self.view_rows)
            for c, cell in enumerate(row)
            if needle in cell.casefold()
        ]
        if not self._matches:
            self._update_status("no match")
            if announce:
                self.notify(f"no match for {query!r}", severity="warning", timeout=2)
            return

        self._match_index = 0
        self._goto_match()

    def _step_match(self, delta: int) -> None:
        if not self._matches:
            if self._query:
                self.notify("no matches", severity="warning", timeout=2)
            return
        self._match_index = (self._match_index + delta) % len(self._matches)
        self._goto_match()

    def _goto_match(self) -> None:
        coordinate = self._matches[self._match_index]
        self.table.move_cursor(row=coordinate.row, column=coordinate.column)
        self._update_status(f"match {self._match_index + 1}/{len(self._matches)}")
