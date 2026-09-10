import contextlib
import io
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from lcat.app import LcatApp
from lcat.detect import is_xlsx, mode_from_extension, resolve_mode
from lcat.loaders import WorkbookDoc, load, load_xlsx
from lcat.plain import render
from lcat.save import SaveError, serialize
from lcat.views import WorkbookView


def workbook_bytes(sheets: dict[str, list[list]]) -> bytes:
    """An xlsx holding `sheets`, as file bytes."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


SHEETS = {
    "Sales": [["region", "units"], ["North", 120], ["South", 84]],
    "Notes": [["field", "value"], ["owner", "planning"]],
}


def sample() -> bytes:
    return workbook_bytes(SHEETS)


# -- detection -------------------------------------------------------------


def test_extension_mapping():
    assert mode_from_extension(Path("book.xlsx")) == "xlsx"
    assert mode_from_extension(Path("book.XLSM")) == "xlsx"


def test_is_xlsx_recognises_a_workbook_and_not_other_zips():
    assert is_xlsx(sample())
    assert not is_xlsx(b"PK\x03\x04" + b"just a zip of something else")
    assert not is_xlsx(b"region,units\nNorth,120\n")


def test_resolve_mode_sniffs_a_workbook_without_an_extension():
    raw = sample()[:8192]
    assert resolve_mode(Path("book"), "auto", raw.decode("utf-8", "replace"), raw) == "xlsx"
    assert resolve_mode(None, "auto", raw.decode("utf-8", "replace"), raw) == "xlsx"


# -- loading ---------------------------------------------------------------


def test_sheets_are_loaded_in_order_with_headers():
    doc = load_xlsx(sample())
    assert isinstance(doc, WorkbookDoc)
    assert doc.names == ["Sales", "Notes"]
    assert doc.sheet.name == "Sales"
    assert doc.sheet.columns == ["region", "units"]
    assert doc.sheet.rows == [["North", "120"], ["South", "84"]]
    assert doc.sheet.shape == (2, 2)


def test_values_are_flattened_to_single_line_strings():
    doc = load_xlsx(
        workbook_bytes(
            {
                "S": [
                    ["when", "at", "flag", "empty", "num"],
                    [date(2026, 3, 4), datetime(2026, 3, 4, 9, 30), True, None, 22.0],
                ]
            }
        )
    )
    assert doc.sheet.rows == [["2026-03-04", "2026-03-04 09:30:00", "TRUE", "", "22"]]


def test_trailing_blank_rows_and_columns_are_dropped():
    doc = load_xlsx(
        workbook_bytes({"S": [["a", "b", None, None], ["1", "2"], [None, None]]})
    )
    assert doc.sheet.columns == ["a", "b"]
    assert doc.sheet.rows == [["1", "2"]]


def test_gaps_inside_the_sheet_are_kept_and_unnamed_columns_get_letters():
    doc = load_xlsx(workbook_bytes({"S": [["a", None, "c"], ["1", None, "3"]]}))
    assert doc.sheet.columns == ["a", "B", "c"]
    assert doc.sheet.rows == [["1", "", "3"]]


def test_no_header_names_columns_by_spreadsheet_letter():
    doc = load_xlsx(sample(), has_header=False)
    assert doc.sheet.columns == ["A", "B"]
    assert doc.sheet.rows[0] == ["region", "units"]


def test_max_rows_trims_every_sheet_and_remembers_the_count():
    doc = load_xlsx(sample(), max_rows=1)
    assert doc.sheet.rows == [["North", "120"]]
    assert doc.sheet.total_rows == 2


def test_an_empty_sheet_loads_as_an_empty_table():
    doc = load_xlsx(workbook_bytes({"Blank": []}))
    assert doc.sheets[0].columns == []
    assert doc.sheets[0].rows == []


def test_formulas_are_read_on_demand():
    doc = load_xlsx(workbook_bytes({"S": [["a", "double"], [2, "=A2*2"]]}))
    # Nothing has computed the formula, so the value reading of the cell is empty.
    assert doc.sheet.rows == [["2", ""]]
    assert doc.read_formulas()
    doc.formulas = True
    assert doc.sheet.rows == [["2", "=A2*2"]]


def test_formulas_need_the_source_bytes():
    doc = load_xlsx(sample())
    doc.source = None
    assert not doc.read_formulas()


def test_a_file_that_is_not_a_workbook_is_rejected():
    with pytest.raises(ValueError, match="not a readable xlsx"):
        load_xlsx(b"PK\x03\x04 not really a workbook")


def test_load_points_at_the_bytes_loader():
    with pytest.raises(ValueError, match="load_xlsx"):
        load("", "xlsx")


# -- plain and save --------------------------------------------------------


def test_plain_render_prints_every_sheet():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        render(load_xlsx(sample()))
    out = buffer.getvalue()
    assert "Sales" in out and "North" in out
    assert "Notes" in out and "planning" in out


def test_workbooks_cannot_be_written_back():
    with pytest.raises(SaveError, match="read-only"):
        serialize(load_xlsx(sample()))


# -- the interactive view --------------------------------------------------


def notes(app: LcatApp) -> list[str]:
    seen: list[str] = []
    app.notify = lambda message, **kwargs: seen.append(message)
    return seen


async def test_the_first_sheet_is_shown_with_its_name():
    app = LcatApp(load_xlsx(sample()))
    async with app.run_test():
        table = app.query_one(DataTable)
        assert [column.label.plain for column in table.ordered_columns] == [
            "region",
            "units",
        ]
        assert table.row_count == 2
        assert "Sales" in app.sub_title


async def test_brackets_walk_the_sheets():
    app = LcatApp(load_xlsx(sample()))
    async with app.run_test() as pilot:
        view = app.query_one(WorkbookView)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert view.workbook.index == 1
        assert "Notes" in app.sub_title
        assert app.query_one(DataTable).row_count == 1
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert view.workbook.index == 0
        assert "Sales" in app.sub_title


async def test_switching_sheets_puts_the_cursor_back_at_the_top():
    app = LcatApp(load_xlsx(sample()))
    async with app.run_test() as pilot:
        await pilot.press("G", "dollar_sign")
        assert app.query_one(DataTable).cursor_coordinate != Coordinate(0, 0)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.query_one(DataTable).cursor_coordinate == Coordinate(0, 0)


async def test_one_sheet_workbook_says_so_instead_of_wrapping():
    app = LcatApp(load_xlsx(workbook_bytes({"Only": [["a"], ["1"]]})))
    async with app.run_test() as pilot:
        seen = notes(app)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert seen == ["the workbook has one sheet"]


async def test_f_toggles_formulas_and_keeps_the_cursor():
    app = LcatApp(load_xlsx(workbook_bytes({"S": [["a", "double"], [2, "=A2*2"]]})))
    async with app.run_test() as pilot:
        view = app.query_one(WorkbookView)
        await pilot.press("right")
        assert view.cell_value(Coordinate(0, 1)) == ""
        await pilot.press("f")
        await pilot.pause()
        assert view.cell_value(Coordinate(0, 1)) == "=A2*2"
        assert app.query_one(DataTable).cursor_coordinate == Coordinate(0, 1)
        assert "formulas" in app.sub_title
        await pilot.press("f")
        await pilot.pause()
        assert view.cell_value(Coordinate(0, 1)) == ""
        assert "formulas" not in app.sub_title


async def test_editing_and_saving_are_refused():
    app = LcatApp(load_xlsx(sample()))
    async with app.run_test() as pilot:
        seen = notes(app)
        await pilot.press("i")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert seen == ["xlsx files are read-only"] * 2
        assert not app.dirty


async def test_reload_keeps_the_sheet_and_the_formula_view(tmp_path):
    path = tmp_path / "book.xlsx"
    path.write_bytes(workbook_bytes({"One": [["a"], [1]], "Two": [["b"], ["=1+1"]]}))

    def reload():
        return load_xlsx(path.read_bytes(), path)

    app = LcatApp(reload(), reload=reload)
    async with app.run_test() as pilot:
        await pilot.press("right_square_bracket", "f")
        await pilot.pause()
        assert app.doc.sheet.rows == [["=1+1"]]
        path.write_bytes(workbook_bytes({"One": [["a"], [1]], "Two": [["b"], ["=2+2"]]}))
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.names[app.doc.index] == "Two"
        assert app.doc.formulas
        assert app.doc.sheet.rows == [["=2+2"]]


async def test_reload_falls_back_to_the_first_sheet_when_one_disappears(tmp_path):
    path = tmp_path / "book.xlsx"
    path.write_bytes(sample())

    def reload():
        return load_xlsx(path.read_bytes(), path)

    app = LcatApp(reload(), reload=reload)
    async with app.run_test() as pilot:
        await pilot.press("right_square_bracket")
        await pilot.pause()
        path.write_bytes(workbook_bytes({"Sales": SHEETS["Sales"]}))
        await app._poll_disk()
        await pilot.pause()
        assert app.doc.index == 0
        assert "Sales" in app.sub_title
