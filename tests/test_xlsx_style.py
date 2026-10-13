"""The pure formatting helpers: colours, widths and number formats, with no app around."""

import io
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Color, Font, PatternFill

from lcat.xlsx_style import (
    DEFAULT,
    DEFAULT_THEME,
    CellStyle,
    StyledCell,
    apply_tint,
    cell_style,
    column_widths,
    implicit_align,
    number_text,
    resolve_color,
    theme_colors,
)

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample.xlsx"


# -- theme colours -----------------------------------------------------------


def test_theme_falls_back_to_the_office_palette():
    assert theme_colors(None) == DEFAULT_THEME
    assert theme_colors(b"not xml at all") == DEFAULT_THEME


def test_theme_is_reordered_the_way_cells_index_it():
    book = load_workbook(SAMPLE, read_only=True)
    colors = theme_colors(book.loaded_theme)
    book.close()
    # <a:clrScheme> lists dk1 (black) first, but cells index lt1 (white) as 0.
    assert colors[0] == "#ffffff"
    assert colors[1] == "#000000"
    assert colors[4] == "#4f81bd"  # accent1, this file's own blue
    assert len(colors) == 12


# -- tint --------------------------------------------------------------------


def test_tint_zero_is_identity():
    assert apply_tint("#4f81bd", 0) == "#4f81bd"


def test_tint_lightens_and_darkens():
    assert apply_tint("#000000", 1.0) == "#ffffff"
    assert apply_tint("#ffffff", -1.0) == "#000000"
    assert apply_tint("#808080", 0.5) > "#808080"  # lighter
    assert apply_tint("#808080", -0.5) < "#808080"  # darker


# -- colour resolution -------------------------------------------------------


def test_resolve_rgb_strips_the_alpha():
    assert resolve_color(Color(rgb="00FF0000")) == "#ff0000"
    assert resolve_color(Color(rgb="FFFF0000")) == "#ff0000"


def test_resolve_indexed_and_its_out_of_range_sentinels():
    assert resolve_color(Color(indexed=2)) == "#ff0000"
    # 64/65 mean system foreground/background and are past the table's end.
    assert resolve_color(Color(indexed=64)) is None
    assert resolve_color(Color(indexed=65)) is None


def test_resolve_theme_applies_the_tint():
    assert resolve_color(Color(theme=1, tint=0.0)) == "#000000"
    assert resolve_color(Color(theme=1, tint=1.0)) == "#ffffff"
    assert resolve_color(Color(theme=99)) is None


def test_resolve_unset_colors():
    assert resolve_color(None) is None
    assert resolve_color(Color(auto=True)) is None


# -- number formats ----------------------------------------------------------


@pytest.mark.parametrize(
    "value,fmt,expected",
    [
        (0.25, "0%", "25%"),
        (0.255, "0.0%", "25.5%"),
        (1234.5, "#,##0", "1,234"),
        (1234.5, "#,##0.00", "1,234.50"),
        (0.5, "0.00", "0.50"),
        (1234.5, '"$"#,##0.00', "$1,234.50"),
        (1234.5, "[$$-409]#,##0.00", "$1,234.50"),
        (1234.5, '"€"#,##0', "€1,234"),
        (12.0, '0" kg"', "12 kg"),
        (3.14159, "0.##", "3.14"),
        (3.1, "0.##", "3.1"),
        (-1234.5, "#,##0", "-1,234"),
        (-1234.5, "#,##0.00;(#,##0.00)", "(1,234.50)"),
        (-1234.5, "#,##0.00;-#,##0.00", "-1,234.50"),
        (0, "0.00", "0.00"),
    ],
)
def test_supported_number_formats(value, fmt, expected):
    assert number_text(value, fmt)[0] == expected


@pytest.mark.parametrize(
    "fmt",
    ["General", "", "@", "yyyy-mm-dd", "0.00E+00", "# ?/?", "[h]:mm", "#,##0,", "mmm-yy"],
)
def test_unsupported_number_formats_fall_back(fmt):
    assert number_text(1234.5, fmt) is None


def test_red_only_applies_to_negatives():
    assert number_text(-1234.5, "#,##0.00;[Red](#,##0.00)") == ("(1,234.50)", True)
    assert number_text(1234.5, "#,##0.00;[Red](#,##0.00)") == ("1,234.50", False)


def test_non_numbers_are_not_formatted():
    assert number_text("text", "0.00") is None
    assert number_text(True, "0.00") is None
    assert number_text(None, "0.00") is None


# -- alignment ---------------------------------------------------------------


def test_implicit_alignment_follows_the_value_type():
    from datetime import datetime

    assert implicit_align(True) == "center"
    assert implicit_align(12) == "right"
    assert implicit_align(12.5) == "right"
    assert implicit_align(datetime(2026, 1, 1)) == "right"
    assert implicit_align("text") == "left"
    assert implicit_align(None) == "left"


# -- column widths -----------------------------------------------------------


def styled_book(build) -> bytes:
    book = Workbook()
    build(book.active)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_column_widths_reads_custom_widths_and_spans():
    def build(sheet):
        sheet["A1"] = "a"
        sheet["E1"] = "e"
        sheet.column_dimensions["A"].width = 30
        for letter in ("C", "D"):
            sheet.column_dimensions[letter].width = 12

    book = load_workbook(io.BytesIO(styled_book(build)), read_only=True)
    widths = column_widths(book.worksheets[0])
    book.close()
    assert widths[1] == 30
    assert widths[3] == 12 and widths[4] == 12
    assert 5 not in widths  # never given a width of its own


def test_column_widths_is_empty_when_nothing_is_custom():
    book = load_workbook(SAMPLE, read_only=True)
    widths = column_widths(book["Sales"])
    book.close()
    assert widths == {}


def test_column_widths_never_raises():
    assert column_widths(object()) == {}


# -- cell styles -------------------------------------------------------------


def test_cell_style_reads_font_fill_and_alignment():
    def build(sheet):
        sheet["A1"] = "hdr"
        sheet["A1"].font = Font(bold=True, italic=True, color="FFFF0000")
        sheet["A1"].fill = PatternFill("solid", fgColor="FF4F81BD")
        sheet["A1"].alignment = Alignment(horizontal="center")

    book = load_workbook(io.BytesIO(styled_book(build)), read_only=True)
    sheet = book.worksheets[0]
    sheet.reset_dimensions()
    cell = next(sheet.iter_rows(min_row=1, max_row=1))[0]
    style = cell_style(cell, DEFAULT_THEME, {})
    book.close()
    assert style == CellStyle(
        color="#ff0000", background="#4f81bd", bold=True, italic=True, align="center"
    )


def test_an_unfilled_cell_has_no_background():
    """openpyxl reports a black fgColor on a cell with no fill; the pattern gates it."""

    def build(sheet):
        sheet["A1"] = "plain"

    book = load_workbook(io.BytesIO(styled_book(build)), read_only=True)
    sheet = book.worksheets[0]
    sheet.reset_dimensions()
    cell = next(sheet.iter_rows(min_row=1, max_row=1))[0]
    style = cell_style(cell, DEFAULT_THEME, {})
    book.close()
    assert style.background is None


def test_identical_formats_share_one_style_object():
    def build(sheet):
        for row in range(1, 4):
            sheet.cell(row=row, column=1, value=f"r{row}").font = Font(bold=True)

    book = load_workbook(io.BytesIO(styled_book(build)), read_only=True)
    sheet = book.worksheets[0]
    sheet.reset_dimensions()
    cache = {}
    styles = [cell_style(row[0], DEFAULT_THEME, cache) for row in sheet.iter_rows()]
    book.close()
    assert styles[0] is styles[1] is styles[2]
    assert len(cache) == 1


# -- the renderable ----------------------------------------------------------


def test_styled_cell_reads_as_its_text():
    cell = StyledCell("hello", DEFAULT)
    assert str(cell) == "hello"
    assert cell.text == "hello"
    assert cell.style is DEFAULT
