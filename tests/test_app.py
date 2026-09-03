from textual.coordinate import Coordinate
from textual.widgets import DataTable

from lcat.app import LcatApp
from lcat.loaders import load
from lcat.views import CellModal, HelpModal, TableView

CSV = "id,name,score\n3,Charlie,10\n1,alpha,200\n2,Bravo,30\n"


def table_app():
    return LcatApp(load(CSV, "csv"))


async def test_table_loads_and_cursor_moves():
    app = table_app()
    async with app.run_test() as pilot:
        table = app.query_one(DataTable)
        assert table.row_count == 3
        assert table.cursor_coordinate == Coordinate(0, 0)
        await pilot.press("right", "down")
        assert table.cursor_coordinate == Coordinate(1, 1)
        await pilot.press("l", "j")
        assert table.cursor_coordinate == Coordinate(2, 2)
        await pilot.press("g")
        assert table.cursor_coordinate.row == 0
        await pilot.press("G")
        assert table.cursor_coordinate.row == 2


async def test_search_moves_cursor_to_match():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("slash")
        assert view.search_input.display
        await pilot.press("b", "r", "a", "v")
        await pilot.press("enter")
        assert app.query_one(DataTable).cursor_coordinate == Coordinate(2, 1)
        assert not view.search_input.display


async def test_search_is_case_insensitive_and_cycles():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.press("a")  # matches several cells
        await pilot.press("enter")
        view = app.query_one(TableView)
        assert len(view._matches) > 1
        first = app.query_one(DataTable).cursor_coordinate
        await pilot.press("n")
        assert app.query_one(DataTable).cursor_coordinate != first
        await pilot.press("N")
        assert app.query_one(DataTable).cursor_coordinate == first


async def test_escape_cancels_search():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("slash")
        await pilot.press("escape")
        assert not view.search_input.display
        assert app.query_one(DataTable).has_focus


async def test_sort_cycles_ascending_descending_original():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("s")  # ascending by id
        assert [row[0] for row in view.view_rows] == ["1", "2", "3"]
        await pilot.press("s")  # descending
        assert [row[0] for row in view.view_rows] == ["3", "2", "1"]
        await pilot.press("s")  # original
        assert [row[0] for row in view.view_rows] == ["3", "1", "2"]


async def test_sort_is_numeric_not_lexicographic():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("right", "right", "s")  # score column
        assert [row[2] for row in view.view_rows] == ["10", "30", "200"]


async def test_enter_opens_and_escape_closes_cell_modal():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, CellModal)
        await pilot.press("escape")
        assert not isinstance(app.screen, CellModal)


async def test_help_modal():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpModal)


async def test_copy_cell_uses_clipboard():
    app = table_app()
    copied = []
    async with app.run_test() as pilot:
        app.copy_to_clipboard = copied.append
        await pilot.press("right", "y")
        assert copied == ["Charlie"]
        await pilot.press("Y")
        assert copied[-1] == "3\tCharlie\t10"


async def test_markdown_view_scrolls():
    text = "# Title\n\n" + "\n\n".join(f"paragraph {i}" for i in range(200))
    app = LcatApp(load(text, "md"))
    async with app.run_test() as pilot:
        view = app.query_one("#view")
        assert view.scroll_offset.y == 0
        await pilot.press("G")
        await pilot.pause()
        assert view.scroll_offset.y > 0
        await pilot.press("g")
        await pilot.pause()
        assert view.scroll_offset.y == 0


async def test_code_view_for_non_tabular_json():
    app = LcatApp(load('[[1, 2], {"a": 1}]', "json"))
    async with app.run_test():
        assert app.query_one("#view").__class__.__name__ == "CodeView"


async def test_large_table_streams_every_row():
    from lcat.views import FIRST_CHUNK

    total = FIRST_CHUNK * 2 + 25
    csv = "n,label\n" + "".join(f"{i},row-{i}\n" for i in range(total))
    app = LcatApp(load(csv, "csv"))
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        table = app.query_one(DataTable)
        assert table.row_count > 0  # something on screen before loading finishes
        while view._loading:
            await pilot.pause()
        assert table.row_count == total
        await pilot.press("G")
        assert view.cell_value(table.cursor_coordinate) == str(total - 1)


async def test_max_rows_is_reflected_in_the_subtitle():
    csv = "n\n" + "".join(f"{i}\n" for i in range(20))
    doc = load(csv, "csv").head(5)
    app = LcatApp(doc)
    async with app.run_test():
        assert "first 5 of 20 rows" in app.sub_title


async def test_i_opens_the_raw_text_and_escape_renders_it_again():
    app = LcatApp(load("# Title\n", "md"))
    async with app.run_test() as pilot:
        view = app.query_one("#view")
        await pilot.press("i")
        editor = app.query_one("#editor")
        assert editor.display and not view.display
        assert editor.has_focus
        assert app.editing and "INSERT" in app.sub_title
        await pilot.press("x")
        await pilot.press("escape")
        await pilot.pause()
        assert not editor.display and view.display
        assert not app.editing
        assert app.doc.text == "x# Title\n"
        assert app.dirty and "modified" in app.sub_title


async def test_leaving_the_editor_unchanged_leaves_the_document_clean():
    app = LcatApp(load("# Title\n", "md"))
    async with app.run_test() as pilot:
        await pilot.press("i")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.dirty
        assert app.doc.text == "# Title\n"


async def test_code_view_is_editable_too():
    app = LcatApp(load('[[1, 2], {"a": 1}]', "json"))
    async with app.run_test() as pilot:
        await pilot.press("i")
        editor = app.query_one("#editor")
        editor.text = "[]"
        await pilot.press("escape")
        await pilot.pause()
        assert app.doc.text == "[]"
        assert app.dirty


async def test_i_edits_a_cell_and_escape_keeps_the_edit():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("right", "i")
        assert isinstance(app.screen, CellModal)
        await pilot.press("X")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CellModal)
        assert view.view_rows[0][1] == "XCharlie"
        assert view.source_rows[0][1] == "XCharlie"
        assert app.query_one(DataTable).get_cell_at(Coordinate(0, 1)) == "XCharlie"
        assert app.dirty


async def test_editing_a_cell_follows_the_row_through_a_sort():
    app = table_app()
    async with app.run_test() as pilot:
        view = app.query_one(TableView)
        await pilot.press("s")  # ascending by id: the "1,alpha,200" row is first
        await pilot.press("right", "i")
        app.screen.query_one("#cell-editor").text = "omega"
        await pilot.press("escape")
        await pilot.pause()
        assert view.view_rows[0][1] == "omega"
        assert view.source_rows[1][1] == "omega"  # its place in the file is unchanged


async def test_escape_on_an_unedited_cell_changes_nothing():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("i")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.dirty


async def test_ctrl_s_writes_the_file(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    app = LcatApp(load(CSV, "csv", path))
    async with app.run_test() as pilot:
        await pilot.press("right", "i")
        app.screen.query_one("#cell-editor").text = "Charles"
        await pilot.press("escape")
        await pilot.pause()
        assert app.dirty
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert path.read_text() == CSV.replace("Charlie", "Charles")
        assert not app.dirty
        assert "modified" not in app.sub_title


async def test_ctrl_s_inside_the_cell_editor_commits_then_writes(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    app = LcatApp(load(CSV, "csv", path))
    async with app.run_test() as pilot:
        await pilot.press("right", "i")
        app.screen.query_one("#cell-editor").text = "Charles"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert path.read_text() == CSV.replace("Charlie", "Charles")
        assert not app.dirty


async def test_ctrl_s_writes_markdown_from_inside_the_editor(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n")
    app = LcatApp(load("# Title\n", "md", path))
    async with app.run_test() as pilot:
        await pilot.press("i")
        app.query_one("#editor").text = "# Other\n"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert path.read_text() == "# Other\n"
        assert app.editing  # still in insert mode, the write does not interrupt


async def test_saving_stdin_reports_that_there_is_no_file():
    app = LcatApp(load(CSV, "csv"))
    notes = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: notes.append(message)
        await pilot.press("i")
        app.screen.query_one("#cell-editor").text = "Charles"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert any("stdin" in note for note in notes)
        assert app.dirty


async def test_quitting_with_unsaved_edits_asks_first():
    from lcat.app import QuitModal

    app = LcatApp(load(CSV, "csv"))
    async with app.run_test() as pilot:
        await pilot.press("i")
        await pilot.press("X")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("q")
        assert isinstance(app.screen, QuitModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, QuitModal)
        assert app.is_running


async def test_a_clean_document_quits_straight_away():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running


async def test_keys_that_are_shortcuts_outside_the_editor_are_typed_inside_it():
    app = LcatApp(load("# Title\n", "md"))
    async with app.run_test() as pilot:
        await pilot.press("i")
        await pilot.press("q", "t", "question_mark")
        assert app.is_running
        assert app.query_one("#editor").text == "qt?# Title\n"


async def test_enter_inserts_a_newline_in_a_cell_instead_of_closing():
    app = table_app()
    async with app.run_test() as pilot:
        await pilot.press("right", "i")
        await pilot.press("enter")
        assert isinstance(app.screen, CellModal)
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one(TableView).view_rows[0][1] == "\nCharlie"
