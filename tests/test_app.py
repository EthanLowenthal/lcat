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
