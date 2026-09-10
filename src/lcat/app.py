"""The Textual application shell."""

from __future__ import annotations

import os
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static

from lcat.loaders import CodeDoc, Document, ImageDoc, MarkdownDoc, TableDoc, WorkbookDoc
from lcat.save import SaveError, save
from lcat.views import (
    CodeView,
    HelpModal,
    ImageView,
    MarkdownView,
    RawEditor,
    TableView,
    WorkbookView,
)


class QuitModal(ModalScreen["str | None"]):
    """Asked before dropping unsaved edits. Dismisses save, discard or None."""

    BINDINGS = [
        Binding("s", "choose('save')", "save and quit"),
        Binding("q", "choose('discard')", "quit anyway"),
        Binding("escape", "choose('cancel')", "keep editing"),
    ]

    def compose(self):
        with Vertical(id="quit-dialog"):
            yield Static("[b]unsaved changes[/b]", id="quit-title")
            yield Static(
                "[b]s[/b] write the file and quit\n"
                "[b]q[/b] quit and lose the edits\n"
                "[b]esc[/b] keep editing",
                id="quit-body",
            )

    def action_choose(self, choice: str) -> None:
        self.dismiss(None if choice == "cancel" else choice)


Reloader = Callable[[], Document]
"""Re-reads the file the document came from, with the same options. Raises OSError,
ValueError or UnicodeError when it cannot."""

POLL_SECONDS = 1.0
"""How often the file is checked for changes while auto-reload is on."""


class LcatApp(App[None]):
    """Render one document interactively."""

    CSS_PATH = "lcat.tcss"
    TITLE = "lcat"

    BINDINGS = [
        Binding("q", "try_quit", "quit"),
        Binding("question_mark", "help", "help"),
        Binding("ctrl+s", "save", "save"),
        Binding("r", "reload", "reload", show=False),
        Binding("R", "toggle_reload", "auto-reload"),
    ]

    dirty: reactive[bool] = reactive(False)
    """The document has edits that are not on disk yet."""

    def __init__(
        self,
        doc: Document,
        encoding: str = "utf-8",
        *,
        images: bool = True,
        reload: Reloader | None = None,
        auto_reload: bool = True,
    ) -> None:
        super().__init__()
        self.doc = doc
        self.encoding = encoding
        self.images = images
        """Render markdown images as pictures (--no-images turns this off)."""
        self.editing = False
        self._rendered_text = getattr(doc, "text", "")
        self._reload = reload
        self.auto_reload = auto_reload and reload is not None
        """Pick up changes to the file on disk as they happen (`R` toggles)."""
        self._disk_stamp = self._stat()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield from self._view_widgets()
        yield Footer()

    def _view_widgets(self) -> ComposeResult:
        """The view for `self.doc`, plus the hidden raw editor where there is text."""
        if isinstance(self.doc, MarkdownDoc):
            base = self.doc.path.parent if self.doc.path else None
            yield MarkdownView(
                self.doc.text,
                show_table_of_contents=False,
                base=base,
                images=self.images,
                id="view",
            )
            yield self._editor()
        elif isinstance(self.doc, TableDoc):
            yield TableView(self.doc.columns, self.doc.rows, id="view")
        elif isinstance(self.doc, WorkbookDoc):
            yield WorkbookView(self.doc, id="view")
        elif isinstance(self.doc, CodeDoc):
            yield CodeView(self.doc.text, self.doc.lexer, id="view")
            yield self._editor()
        elif isinstance(self.doc, ImageDoc):
            yield ImageView(self.doc.image, id="view")
        else:  # pragma: no cover - guarded by the CLI
            raise TypeError(f"cannot display {type(self.doc).__name__}")

    def _editor(self) -> RawEditor:
        """The raw-text editor for markdown and code, hidden until `i`."""
        editor = RawEditor(self._rendered_text, id="editor", show_line_numbers=True)
        editor.display = False
        return editor

    def on_mount(self) -> None:
        self._refresh_subtitle()
        self._focus_view()
        if self._reload is not None:
            self.set_interval(POLL_SECONDS, self._poll_disk)

    def _focus_view(self) -> None:
        view = self.query_one("#view")
        if view.can_focus:
            view.focus()

    # -- reloading -------------------------------------------------------

    def _stat(self) -> tuple[int, int] | None:
        """(mtime, size) of the file on disk, or None if it cannot be read right now."""
        path = self.doc.path
        if path is None:
            return None
        try:
            info = os.stat(path)
        except OSError:
            return None
        return info.st_mtime_ns, info.st_size

    async def _poll_disk(self) -> None:
        """Called on a timer: reload if the file changed and nothing would be lost."""
        if not self.auto_reload:
            return
        stamp = self._stat()
        if stamp is None or stamp == self._disk_stamp:
            return
        self._disk_stamp = stamp
        if self.editing or self.dirty:
            self.notify(
                "changed on disk; not reloading over unsaved edits (r discards them)",
                severity="warning",
                timeout=4,
            )
            return
        await self.reload_from_disk()

    async def reload_from_disk(self) -> None:
        """Re-read the file and show it, dropping any unsaved edits."""
        if self._reload is None:
            self.notify("nothing to reload: the input came from stdin", timeout=2)
            return
        try:
            doc = self._reload()
        except (OSError, ValueError, UnicodeError) as error:
            self.notify(f"reload failed: {error}", severity="error", timeout=5)
            return
        self._disk_stamp = self._stat()
        had_edits = self.dirty or self.editing
        await self._show(doc)
        self.notify("reloaded, edits discarded" if had_edits else "reloaded", timeout=2)

    async def _show(self, doc: Document) -> None:
        """Replace the document, updating the view in place when its kind is unchanged
        so the cursor and scroll position survive; otherwise swap the view out."""
        view = self.query_one("#view")
        previous = self.doc
        same_kind = type(doc) is type(previous)
        self.doc = doc
        self.editing = False
        self.dirty = False
        if same_kind and isinstance(doc, (MarkdownDoc, CodeDoc)):
            editor = self.query_one("#editor", RawEditor)
            editor.display = False
            editor.text = doc.text
            view.display = True
            self._rendered_text = doc.text
            if isinstance(view, MarkdownView):
                await view.document.update(doc.text)
            else:
                view.update_text(doc.text)
        elif same_kind and isinstance(doc, TableDoc):
            view.replace(doc.columns, doc.rows)
        elif same_kind and isinstance(doc, WorkbookDoc):
            # Keep looking at the same sheet, by name: a reload may reorder them.
            assert isinstance(previous, WorkbookDoc)  # same_kind
            name = previous.names[previous.index] if previous.names else None
            doc.index = doc.names.index(name) if name in doc.names else 0
            doc.formulas = previous.formulas and doc.read_formulas()
            view.show_workbook(doc)
        elif same_kind and isinstance(doc, ImageDoc):
            view.set_image(doc.image)
        else:
            await self.query("#view, #editor").remove()
            await self.mount_all(list(self._view_widgets()), before=self.query_one(Footer))
        self._focus_view()
        self._refresh_subtitle()

    def action_reload(self) -> None:
        self.run_worker(self.reload_from_disk(), exclusive=True, group="reload")

    def action_toggle_reload(self) -> None:
        if self._reload is None:
            self.notify("auto-reload needs a file: the input came from stdin", timeout=3)
            return
        self.auto_reload = not self.auto_reload
        if self.auto_reload:
            self._disk_stamp = self._stat()
        self._refresh_subtitle()
        self.notify(f"auto-reload {'on' if self.auto_reload else 'off'}", timeout=2)

    # -- title -----------------------------------------------------------

    @staticmethod
    def _shape(rows: int, cols: int, total: int | None) -> str:
        if total is not None:
            return f"first {rows:,} of {total:,} rows × {cols} cols"
        return f"{rows:,} rows × {cols} cols"

    def _describe(self) -> str:
        path = self.doc.path
        if isinstance(self.doc, TableDoc):
            rows, cols = self.doc.shape
            shape = self._shape(rows, cols, self.doc.total_rows)
            return f"{path.name} · {shape}" if path else shape
        if isinstance(self.doc, WorkbookDoc):
            sheet = self.doc.sheet
            rows, cols = sheet.shape
            parts = [sheet.name, self._shape(rows, cols, sheet.total_rows)]
            if self.doc.formulas:
                parts.append("formulas")
            about = " · ".join(parts)
            return f"{path.name} · {about}" if path else about
        if isinstance(self.doc, ImageDoc):
            width, height = self.doc.size
            about = f"{width}×{height} px · {self.doc.format}"
            return f"{path.name} · {about}" if path else about
        if path is not None:
            return path.name
        return "stdin"

    def _refresh_subtitle(self) -> None:
        parts = [self._describe()]
        if self.editing:
            parts.append("INSERT")
        if self.dirty:
            parts.append("modified")
        if self.auto_reload:
            parts.append("watching")
        self.sub_title = " · ".join(parts)

    def refresh_status(self) -> None:
        """Called by a view after it changes what is on screen (a workbook sheet)."""
        self._refresh_subtitle()

    def watch_dirty(self, dirty: bool) -> None:
        if self.is_running:
            self._refresh_subtitle()

    def mark_dirty(self) -> None:
        """Called by a view when it changes the document in place."""
        self.dirty = True

    # -- editing ---------------------------------------------------------

    def enter_edit_mode(self) -> None:
        """Swap the rendered view for the raw text of the document."""
        editor = self.query_one("#editor", RawEditor)
        self.query_one("#view").display = False
        editor.display = True
        editor.focus()
        self.editing = True
        self._refresh_subtitle()

    async def leave_edit_mode(self) -> None:
        """Back to the rendered view, keeping whatever was typed."""
        editor = self.query_one("#editor", RawEditor)
        view = self.query_one("#view")
        text = editor.text
        editor.display = False
        view.display = True
        view.focus()
        self.editing = False
        self._take_text(text)
        if text != self._rendered_text:
            self._rendered_text = text
            if isinstance(view, MarkdownView):
                await view.document.update(text)
            else:
                view.update_text(text)
        self._refresh_subtitle()

    def _take_text(self, text: str) -> None:
        if text != self.doc.text:
            self.doc.text = text
            self.dirty = True

    async def on_raw_editor_done(self, event: RawEditor.Done) -> None:
        event.stop()
        await self.leave_edit_mode()

    # -- actions ---------------------------------------------------------

    def action_save(self) -> None:
        if isinstance(self.doc, WorkbookDoc):
            self.notify("xlsx files are read-only", severity="warning", timeout=3)
            return
        if self.editing:
            self._take_text(self.query_one("#editor", RawEditor).text)
        if not self.dirty:
            self.notify("no changes to write", timeout=2)
            return
        try:
            path = save(self.doc, self.encoding)
        except SaveError as error:
            self.notify(str(error), severity="error", timeout=5)
            return
        except (OSError, UnicodeError) as error:
            self.notify(f"could not write: {error}", severity="error", timeout=5)
            return
        self.dirty = False
        self._disk_stamp = self._stat()  # our own write is not a change to pick up
        self.notify(f"wrote {path.name}", timeout=2)

    def action_try_quit(self) -> None:
        if not self.dirty:
            self.exit()
            return
        self.push_screen(QuitModal(), self._resolve_quit)

    def _resolve_quit(self, choice: str | None) -> None:
        if choice == "save":
            self.action_save()
            if self.dirty:  # the write failed; the notification says why
                return
        if choice is not None:
            self.exit()

    def action_help(self) -> None:
        view = self.query_one("#view")
        self.push_screen(HelpModal(list(getattr(view, "HELP", []))))
