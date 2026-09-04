import io
from pathlib import Path

from PIL import Image as PILImage
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from lcat.app import LcatApp
from lcat.loaders import load, load_image
from lcat.views import CodeView, ImageView, TableView

CSV = "id,name\n1,alpha\n2,bravo\n3,charlie\n"


def reloading_app(path: Path, mode: str, **kwargs) -> LcatApp:
    """An app wired up the way the CLI does it: re-read `path` in the same mode."""

    def reload():
        data = path.read_bytes()
        if mode == "img":
            return load_image(data, path)
        return load(data.decode(), mode, path)

    return LcatApp(reload(), reload=reload, **kwargs)


def notes(app: LcatApp) -> list[str]:
    seen: list[str] = []
    app.notify = lambda message, **kwargs: seen.append(message)
    return seen


async def test_markdown_reloads_when_the_file_changes(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md")
    async with app.run_test() as pilot:
        assert app.auto_reload and "watching" in app.sub_title
        path.write_text("# Two, longer\n")
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.text == "# Two, longer\n"
        assert app.query_one("#editor").text == "# Two, longer\n"
        assert "Two" in app.query_one("#view").document.source


async def test_table_reload_keeps_the_cursor_and_search(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    app = reloading_app(path, "csv")
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("slash", "a", "enter")  # search for "a": lands on alpha
        await pilot.press("down", "down")  # then wander off to charlie
        path.write_text(CSV + "4,delta\n")
        await app._poll_disk()
        await pilot.pause()
        assert len(view.view_rows) == 4
        assert app.query_one(DataTable).row_count == 4
        assert app.query_one(DataTable).cursor_coordinate == Coordinate(2, 1)
        assert len(view._matches) == 4  # alpha, bravo, charlie, delta
        assert "4 rows" in app.sub_title


async def test_table_reload_clamps_the_cursor_when_rows_vanish(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    app = reloading_app(path, "csv")
    async with app.run_test() as pilot:
        await pilot.press("G")
        path.write_text("id,name\n1,alpha\n")
        await app._poll_disk()
        await pilot.pause()
        assert app.query_one(DataTable).cursor_coordinate == Coordinate(0, 0)


async def test_reload_swaps_the_view_when_the_document_kind_changes(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('[{"a": 1}, {"a": 2}]')
    app = reloading_app(path, "json")
    async with app.run_test() as pilot:
        assert isinstance(app.query_one("#view"), TableView)
        path.write_text('[[1, 2], {"a": 1}, "mixed"]')
        await app._poll_disk()
        await pilot.pause()
        view = app.query_one("#view")
        assert isinstance(view, CodeView)
        assert view.has_focus
        assert app.query_one("#editor")  # the code view brings its editor along
        assert "data.json" in app.sub_title


async def test_image_reload(tmp_path):
    path = tmp_path / "pic.png"

    def write(width):
        buffer = io.BytesIO()
        PILImage.new("RGB", (width, 20), "blue").save(buffer, "PNG")
        path.write_bytes(buffer.getvalue())

    write(40)
    app = reloading_app(path, "img")
    async with app.run_test() as pilot:
        view = app.query_one(ImageView)
        before = view.image_widget.size.width
        write(400)
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.size == (400, 20)
        assert view.image_widget.size.width > before
        assert "400×20" in app.sub_title


async def test_toggle_turns_auto_reload_off_and_on(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md")
    async with app.run_test() as pilot:
        await pilot.press("R")
        assert not app.auto_reload and "watching" not in app.sub_title
        path.write_text("# Two, longer\n")
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.text == "# One\n"
        # back on: the change that happened meanwhile is not replayed
        await pilot.press("R")
        assert app.auto_reload
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.text == "# One\n"
        path.write_text("# Three, longer still\n")
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.text == "# Three, longer still\n"


async def test_no_reload_flag_starts_off(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md", auto_reload=False)
    async with app.run_test():
        assert not app.auto_reload


async def test_r_reloads_now_even_with_auto_reload_off(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md", auto_reload=False)
    async with app.run_test() as pilot:
        path.write_text("# Two\n")
        await pilot.press("r")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.doc.text == "# Two\n"


async def test_unsaved_edits_are_not_overwritten_by_auto_reload(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md")
    seen = notes(app)
    async with app.run_test() as pilot:
        await pilot.press("i", "x", "escape")
        await pilot.pause()
        assert app.dirty
        path.write_text("# Two, longer\n")
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.text == "x# One\n"
        assert app.dirty
        assert any("unsaved" in note for note in seen)
        # a manual reload is explicit, so it wins
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.doc.text == "# Two, longer\n"
        assert not app.dirty
        assert any("discarded" in note for note in seen)


async def test_our_own_save_is_not_treated_as_a_change(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# One\n")
    app = reloading_app(path, "md")
    seen = notes(app)
    async with app.run_test() as pilot:
        await pilot.press("i", "x", "escape")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert path.read_text() == "x# One\n"
        await app._poll_disk()
        await pilot.pause()
        assert "reloaded" not in seen


async def test_reload_failure_keeps_the_old_document(tmp_path):
    path = tmp_path / "pic.png"
    buffer = io.BytesIO()
    PILImage.new("RGB", (40, 20), "blue").save(buffer, "PNG")
    path.write_bytes(buffer.getvalue())
    app = reloading_app(path, "img")
    seen = notes(app)
    async with app.run_test() as pilot:
        path.write_bytes(b"half-written garbage")
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.size == (40, 20)
        assert any("reload failed" in note for note in seen)


async def test_stdin_has_nothing_to_reload():
    app = LcatApp(load(CSV, "csv"))
    seen = notes(app)
    async with app.run_test() as pilot:
        assert not app.auto_reload
        await pilot.press("R")
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(seen) == 2 and all("stdin" in note for note in seen)
