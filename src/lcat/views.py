"""The interactive views: markdown, table, code and image."""

from __future__ import annotations

import ast
import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.syntax import Syntax
from textual import events
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical, VerticalScroll
from textual.content import Content, Span
from textual.coordinate import Coordinate
from textual.message import Message
from textual.screen import ModalScreen
from textual.style import Style
from textual.widget import Widget
from textual.widgets import DataTable, Input, Markdown, MarkdownViewer, Static, TextArea
from textual.widgets.markdown import MarkdownBlock, MarkdownTableOfContents
from textual_image.widget import Image as TerminalImage

from lcat.images import browser_url, local_path, natural_cells

if TYPE_CHECKING:  # pragma: no cover
    from markdown_it.token import Token
    from PIL.Image import Image as PILImage

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


class RawEditor(TextArea):
    """A TextArea that leaves insert mode on escape instead of moving focus.

    TextArea consumes escape itself, before bindings are consulted, so the key has
    to be intercepted here rather than bound.
    """

    class Done(Message):
        """Escape was pressed: the editor's text is ready to be committed."""

        def __init__(self, editor: RawEditor) -> None:
            super().__init__()
            self.editor = editor

        @property
        def control(self) -> RawEditor:
            return self.editor

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Done(self))
            return
        await super()._on_key(event)


class CellModal(ModalScreen["tuple[str, bool] | None"]):
    """Full, untruncated value of a single cell, editable with `i`.

    Dismisses with None when nothing was edited, or (text, save_file) when it was.
    """

    BINDINGS = [
        Binding("escape,enter,q", "close", "close"),
        Binding("ctrl+s", "save_cell", "save", show=False),
    ]

    def __init__(
        self, column: str, value: str, position: str, *, editable: bool = False
    ) -> None:
        super().__init__()
        self._column = column
        self._value = value
        self._position = position
        self._editable = editable

    def compose(self):
        with Vertical(id="cell-dialog"):
            title = f"[b]{self._column}[/b]  [dim]{self._position}[/dim]"
            if self._editable:
                title += "  [dim]· editing[/dim]"
            yield Static(title, id="cell-title")
            if self._editable:
                yield RawEditor(self._value, id="cell-editor", soft_wrap=True)
            else:
                with VerticalScroll(id="cell-body"):
                    yield Static(self._value or "[dim](empty)[/dim]", id="cell-value")
            hint = (
                "esc to keep the edit · ctrl+s to keep it and write the file"
                if self._editable
                else "esc to close"
            )
            yield Static(f"[dim]{hint}[/dim]", id="cell-hint")

    def on_mount(self) -> None:
        if self._editable:
            self.query_one(RawEditor).focus()

    @property
    def _text(self) -> str:
        return self.query_one(RawEditor).text

    def action_close(self) -> None:
        self.dismiss(None)

    def action_save_cell(self) -> None:
        if self._editable:
            self.dismiss((self._text, True))

    def on_raw_editor_done(self, event: RawEditor.Done) -> None:
        event.stop()
        self.dismiss((event.editor.text, False))


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


# -- markdown: hyperlinks and inline images ----------------------------------

_LINK_ACTION = re.compile(r"^link\((.*)\)$", re.DOTALL)
"""The `@click` action Textual attaches to a markdown link: `link('href')`."""

_IMAGE_RUN_FILLER = {"softbreak", "hardbreak"}


def _href_from_action(action: object) -> str | None:
    if not isinstance(action, str):
        return None
    match = _LINK_ACTION.match(action)
    if match is None:
        return None
    try:
        href = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return None
    return href if isinstance(href, str) else None


def hyperlinked(content: Content, base: Path) -> Content:
    """Give every clickable link in `content` a real hyperlink too.

    Textual only wires links up for its own mouse handling. Adding `Style.link`
    makes it emit an OSC 8 hyperlink as well, so terminals that understand those
    (iTerm2, kitty, WezTerm, recent gnome-terminal...) let you cmd/ctrl-click
    straight through to the browser. Terminals that don't simply ignore it.
    """
    spans: list[Span] = []
    changed = False
    for span in content.spans:
        style = span.style
        if isinstance(style, Style) and style.link is None:
            url = browser_url(_href_from_action(style.meta.get("@click")) or "", base)
            if url:
                style = style + Style(link=url)
                changed = True
        spans.append(Span(span.start, span.end, style))
    return Content(content.plain, spans=spans) if changed else content


def image_run(token: Token) -> list[tuple[str, str]]:
    """The (src, alt) pairs of an inline token that is nothing but images.

    A paragraph made only of images (one per line is common) is rendered as
    pictures; anything with prose around the image keeps Textual's text form.
    """
    if not token.children:
        return []
    images: list[tuple[str, str]] = []
    for child in token.children:
        if child.type == "image":
            alt = child.content or str(child.attrs.get("alt", ""))
            images.append((str(child.attrs.get("src", "")), alt))
        elif child.type in _IMAGE_RUN_FILLER:
            continue
        elif child.type == "text" and not child.content.strip():
            continue
        else:
            return []
    return images


def markdown_image(path: Path, alt: str = "") -> Widget:
    """An image widget for a markdown document, drawn no larger than its own pixels.

    textual-image's widget class is chosen at import time for the terminal, and
    subclassing it needs its renderable, so it is configured here instead.
    """
    widget = TerminalImage(path, classes="markdown-image")
    widget.tooltip = alt or None
    width, height = natural_cells(widget._image_width, widget._image_height)
    widget.styles.max_width = width
    widget.styles.max_height = height
    return widget


def _image_widget(src: str, alt: str, base: Path) -> Widget | None:
    """A widget for a local, readable image, else None (URLs, missing files)."""
    path = local_path(src, base)
    if path is None or not path.is_file():
        return None
    try:
        return markdown_image(path, alt)
    except (OSError, ValueError):  # PIL could not read it
        return None


class _Hyperlinks:
    """Mixin for MarkdownBlock subclasses: link text carries a terminal hyperlink."""

    _markdown: Markdown

    def _token_to_content(self, token: Token) -> Content:
        content = super()._token_to_content(token)  # type: ignore[misc]
        base = getattr(self._markdown, "base", None) or Path.cwd()
        return hyperlinked(content, base)


def _with_hyperlinks(block: type[MarkdownBlock]) -> type[MarkdownBlock]:
    return type(block.__name__, (_Hyperlinks, block), {})


class LcatParagraph(_Hyperlinks, Markdown.BLOCKS["paragraph_open"]):  # type: ignore[misc]
    """A paragraph that shows local images as pictures when the terminal can."""

    def build_from_token(self, token: Token) -> None:
        markdown = self._markdown
        if getattr(markdown, "images", False):
            images = image_run(token)
            widgets = [_image_widget(src, alt, markdown.base) for src, alt in images]
            if widgets and all(widgets):
                self._inline_token = token
                self._blocks.extend(widgets)  # type: ignore[arg-type]
                self.set_content(Content(""))
                return
        super().build_from_token(token)


class LcatMarkdown(Markdown):
    """Textual's Markdown with terminal hyperlinks and rendered local images."""

    BLOCKS = {name: _with_hyperlinks(block) for name, block in Markdown.BLOCKS.items()}
    BLOCKS["paragraph_open"] = LcatParagraph

    def __init__(self, *, base: Path, images: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.base = base
        """Directory relative image sources and links are resolved against."""
        self.images = images


class MarkdownView(MarkdownViewer, can_focus=True, can_focus_children=True):
    """MarkdownViewer plus vim-style scrolling, a contents sidebar, images and links."""

    BINDINGS = [
        Binding("j", "scroll_down", "down", show=False),
        Binding("k", "scroll_up", "up", show=False),
        Binding("ctrl+d", "page_down", "page down", show=False),
        Binding("ctrl+u", "page_up", "page up", show=False),
        Binding("g", "scroll_home", "top", show=False),
        Binding("G", "scroll_end", "bottom", show=False),
        Binding("t", "toggle_contents", "contents"),
        Binding("i", "edit", "edit"),
    ]

    HELP = [
        ("up down j k", "scroll a line"),
        ("pgup pgdn ctrl+u ctrl+d", "scroll a page"),
        ("g G home end", "top / bottom"),
        ("t", "toggle the table of contents"),
        ("click a link", "open it in the browser"),
        ("i", "edit the raw text (esc to render it again)"),
        ("ctrl+s", "write the file"),
        ("r R", "reload from disk / toggle auto-reload"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def __init__(
        self,
        markdown: str | None = None,
        *,
        base: Path | None = None,
        images: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(markdown, **kwargs)
        self.base = base or Path.cwd()
        self.images = images

    def compose(self):
        markdown = LcatMarkdown(
            base=self.base,
            images=self.images,
            parser_factory=self._parser_factory,
            open_links=False,
        )
        markdown.can_focus = True
        yield markdown
        yield MarkdownTableOfContents(markdown)

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        """Open links outside instead of navigating the viewer to another file."""
        message.stop()
        # Textual runs the private handler of every base class too; this skips
        # MarkdownViewer's, which would try to load the target as a markdown file.
        message.prevent_default()
        href = message.href
        if href.startswith("#"):
            if not self.document.goto_anchor(href[1:]):
                self.notify(f"no heading {href}", severity="warning", timeout=2)
            return
        url = browser_url(href, self.base)
        if url is None:
            return
        self.app.open_url(url)
        self.notify(f"opened {href}", timeout=2)

    def action_edit(self) -> None:
        self.app.enter_edit_mode()

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
        Binding("i", "edit", "edit"),
    ]

    HELP = [
        ("up down j k", "scroll a line"),
        ("pgup pgdn ctrl+u ctrl+d", "scroll a page"),
        ("g G home end", "top / bottom"),
        ("i", "edit the raw text (esc to leave insert mode)"),
        ("ctrl+s", "write the file"),
        ("r R", "reload from disk / toggle auto-reload"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def __init__(self, text: str, lexer: str = "text", id: str | None = None) -> None:
        super().__init__(id=id)
        self._text = text
        self._lexer = lexer

    def compose(self):
        yield Static(self._syntax(), id="code")

    def _syntax(self) -> Syntax:
        return Syntax(
            self._text,
            self._lexer,
            theme="ansi_dark",
            background_color="default",
            line_numbers=True,
        )

    def action_edit(self) -> None:
        self.app.enter_edit_mode()

    def update_text(self, text: str) -> None:
        self._text = text
        self.query_one("#code", Static).update(self._syntax())


class ImageView(ScrollableContainer):
    """One image, fitted to the window; `z` toggles a 1:1 view that scrolls."""

    BINDINGS = [
        Binding("j", "scroll_down", "down", show=False),
        Binding("k", "scroll_up", "up", show=False),
        Binding("h", "scroll_left", "left", show=False),
        Binding("l", "scroll_right", "right", show=False),
        Binding("ctrl+d", "page_down", "page down", show=False),
        Binding("ctrl+u", "page_up", "page up", show=False),
        Binding("g", "scroll_home", "top", show=False),
        Binding("G", "scroll_end", "bottom", show=False),
        Binding("z", "toggle_zoom", "zoom"),
    ]

    HELP = [
        ("z", "toggle fit-to-window / actual size"),
        ("arrows h j k l", "scroll (at actual size)"),
        ("pgup pgdn ctrl+u ctrl+d", "scroll a page"),
        ("g G home end", "top / bottom"),
        ("r R", "reload from disk / toggle auto-reload"),
        ("?", "this help"),
        ("q", "quit"),
    ]

    def __init__(self, image: PILImage, id: str | None = None) -> None:
        super().__init__(id=id)
        self._image = image
        self.fit = True
        """Scale down to fit the window (never up); False shows one pixel per pixel."""

    def compose(self):
        yield TerminalImage(self._image, id="image")

    def on_mount(self) -> None:
        self._apply_zoom()

    @property
    def image_widget(self) -> Widget:
        return self.query_one("#image")

    def _apply_zoom(self) -> None:
        styles = self.image_widget.styles
        width, height = natural_cells(self._image.width, self._image.height)
        if self.fit:
            styles.max_width = width
            styles.max_height = height
            styles.width = "auto"
            styles.height = "auto"
        else:
            styles.max_width = None
            styles.max_height = None
            styles.width = width
            styles.height = height

    def set_image(self, image: PILImage) -> None:
        """Show another image, keeping the zoom mode."""
        self._image = image
        self.image_widget.image = image  # type: ignore[attr-defined]
        self._apply_zoom()

    def action_toggle_zoom(self) -> None:
        self.fit = not self.fit
        self._apply_zoom()
        self.scroll_home(animate=False)
        self.notify("fit to window" if self.fit else "actual size", timeout=2)


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
        Binding("i", "edit_cell", "edit"),
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
        ("i", "edit this cell (esc keeps the edit)"),
        ("ctrl+s", "write the file"),
        ("r R", "reload from disk / toggle auto-reload"),
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

    def replace(self, columns: list[str], rows: list[list[str]]) -> None:
        """Show new data, keeping the cursor where it was (clamped) and the search."""
        table = self.table
        cursor = table.cursor_coordinate
        self.columns = columns
        self.source_rows = rows
        self.view_rows = list(rows)
        self._sort_column, self._sort_state = None, 0
        table.clear(columns=True)
        table.add_columns(*columns)
        self._populate()
        if self._query:
            self._matches = self._find_matches(self._query)
            self._match_index = 0
        if rows and columns:
            table.move_cursor(
                row=min(cursor.row, len(rows) - 1),
                column=min(cursor.column, len(columns) - 1),
            )
        self._update_status()

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
        if not self.view_rows:
            return
        self._open_cell(event.coordinate, editable=False)

    def _open_cell(self, coordinate: Coordinate, *, editable: bool) -> None:
        column = self.columns[coordinate.column]
        position = f"row {coordinate.row + 1}, column {coordinate.column + 1}"
        modal = CellModal(
            column, self.cell_value(coordinate), position, editable=editable
        )
        self.app.push_screen(
            modal, lambda result: self._commit_cell(coordinate, result)
        )

    def _commit_cell(self, coordinate: Coordinate, result) -> None:
        """Apply an edited value from the cell modal."""
        if result is None:
            return
        value, write_file = result
        if value != self.cell_value(coordinate):
            # view_rows and source_rows share their row lists, so this edits both:
            # the table keeps whatever sort order is on screen, the document keeps
            # the file's own order.
            self.view_rows[coordinate.row][coordinate.column] = value
            self.table.update_cell_at(coordinate, _truncate(value), update_width=True)
            self.app.mark_dirty()
            if self._query:
                self._matches = self._find_matches(self._query)
            self._update_status("edited")
        if write_file:
            self.app.action_save()

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

    def action_edit_cell(self) -> None:
        if not self.view_rows:
            return
        self._open_cell(self.table.cursor_coordinate, editable=True)

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
        if not query:
            self._matches = []
            self._update_status()
            return

        self._matches = self._find_matches(query)
        if not self._matches:
            self._update_status("no match")
            if announce:
                self.notify(f"no match for {query!r}", severity="warning", timeout=2)
            return

        self._match_index = 0
        self._goto_match()

    def _find_matches(self, query: str) -> list[Coordinate]:
        needle = query.casefold()
        return [
            Coordinate(r, c)
            for r, row in enumerate(self.view_rows)
            for c, cell in enumerate(row)
            if needle in cell.casefold()
        ]

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
