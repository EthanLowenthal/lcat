"""The Textual application shell."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from lcat.loaders import CodeDoc, Document, MarkdownDoc, TableDoc
from lcat.views import CodeView, HelpModal, MarkdownView, TableView


class LcatApp(App[None]):
    """Render one document interactively."""

    CSS_PATH = "lcat.tcss"
    TITLE = "lcat"

    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("question_mark", "help", "help"),
    ]

    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        if isinstance(self.doc, MarkdownDoc):
            yield MarkdownView(self.doc.text, show_table_of_contents=False, id="view")
        elif isinstance(self.doc, TableDoc):
            yield TableView(self.doc.columns, self.doc.rows, id="view")
        elif isinstance(self.doc, CodeDoc):
            yield CodeView(self.doc.text, self.doc.lexer, id="view")
        else:  # pragma: no cover - guarded by the CLI
            raise TypeError(f"cannot display {type(self.doc).__name__}")
        yield Footer()

    def on_mount(self) -> None:
        path = self.doc.path
        if isinstance(self.doc, TableDoc):
            rows, cols = self.doc.shape
            if self.doc.total_rows is not None:
                shape = f"first {rows:,} of {self.doc.total_rows:,} rows × {cols} cols"
            else:
                shape = f"{rows:,} rows × {cols} cols"
            self.sub_title = f"{path.name} · {shape}" if path else shape
        elif path is not None:
            self.sub_title = path.name
        else:
            self.sub_title = "stdin"
        view = self.query_one("#view")
        if view.can_focus:
            view.focus()

    def action_help(self) -> None:
        view = self.query_one("#view")
        self.push_screen(HelpModal(list(getattr(view, "HELP", []))))
