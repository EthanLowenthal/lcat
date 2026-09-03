"""The Textual application shell."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static

from lcat.loaders import CodeDoc, Document, MarkdownDoc, TableDoc
from lcat.save import SaveError, save
from lcat.views import CodeView, HelpModal, MarkdownView, RawEditor, TableView


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


class LcatApp(App[None]):
    """Render one document interactively."""

    CSS_PATH = "lcat.tcss"
    TITLE = "lcat"

    BINDINGS = [
        Binding("q", "try_quit", "quit"),
        Binding("question_mark", "help", "help"),
        Binding("ctrl+s", "save", "save"),
    ]

    dirty: reactive[bool] = reactive(False)
    """The document has edits that are not on disk yet."""

    def __init__(self, doc: Document, encoding: str = "utf-8") -> None:
        super().__init__()
        self.doc = doc
        self.encoding = encoding
        self.editing = False
        self._rendered_text = getattr(doc, "text", "")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        if isinstance(self.doc, MarkdownDoc):
            yield MarkdownView(self.doc.text, show_table_of_contents=False, id="view")
            yield self._editor()
        elif isinstance(self.doc, TableDoc):
            yield TableView(self.doc.columns, self.doc.rows, id="view")
        elif isinstance(self.doc, CodeDoc):
            yield CodeView(self.doc.text, self.doc.lexer, id="view")
            yield self._editor()
        else:  # pragma: no cover - guarded by the CLI
            raise TypeError(f"cannot display {type(self.doc).__name__}")
        yield Footer()

    def _editor(self) -> RawEditor:
        """The raw-text editor for markdown and code, hidden until `i`."""
        editor = RawEditor(self._rendered_text, id="editor", show_line_numbers=True)
        editor.display = False
        return editor

    def on_mount(self) -> None:
        self._refresh_subtitle()
        view = self.query_one("#view")
        if view.can_focus:
            view.focus()

    # -- title -----------------------------------------------------------

    def _describe(self) -> str:
        path = self.doc.path
        if isinstance(self.doc, TableDoc):
            rows, cols = self.doc.shape
            if self.doc.total_rows is not None:
                shape = f"first {rows:,} of {self.doc.total_rows:,} rows × {cols} cols"
            else:
                shape = f"{rows:,} rows × {cols} cols"
            return f"{path.name} · {shape}" if path else shape
        if path is not None:
            return path.name
        return "stdin"

    def _refresh_subtitle(self) -> None:
        parts = [self._describe()]
        if self.editing:
            parts.append("INSERT")
        if self.dirty:
            parts.append("modified")
        self.sub_title = " · ".join(parts)

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
