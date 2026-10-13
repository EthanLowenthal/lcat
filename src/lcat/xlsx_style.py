"""Turning a spreadsheet cell's formatting into something a terminal can draw.

openpyxl hands formatting back in Excel's own terms: colours that index a theme palette
the file carries with it, fills that report black when there is no fill at all, and
number formats written in a little DSL. Everything here resolves that into plain
``#rrggbb`` strings and one small frozen `CellStyle` per distinct format, so the two
render paths never have to know any OOXML.

openpyxl is deliberately not imported at module level: `loaders` reaches for this only
on the xlsx path, and markdown/CSV startup should not pay for it.
"""

from __future__ import annotations

import colorsys
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache

from rich.measure import Measurement
from rich.style import Style
from rich.text import Text

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DRAW = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_SHEET_DATA = _MAIN + "sheetData"
_COL = _MAIN + "col"

DEFAULT_THEME: tuple[str, ...] = (
    "#ffffff",  # 0 lt1
    "#000000",  # 1 dk1
    "#e7e6e6",  # 2 lt2
    "#44546a",  # 3 dk2
    "#4472c4",  # 4 accent1
    "#ed7d31",  # 5 accent2
    "#a5a5a5",  # 6 accent3
    "#ffc000",  # 7 accent4
    "#5b9bd5",  # 8 accent5
    "#70ad47",  # 9 accent6
    "#0563c1",  # 10 hlink
    "#954f72",  # 11 folHlink
)
"""The Office palette, already in the order cell colours index it. Used for workbooks
that carry no theme part of their own."""

_SCHEME_ORDER = ("dk1", "lt1", "dk2", "lt2") + tuple(
    f"accent{n}" for n in range(1, 7)
) + ("hlink", "folHlink")
"""The order `<a:clrScheme>` lists its children in. Cells index the first two pairs the
other way round, which `theme_colors` corrects."""


@dataclass(frozen=True, slots=True)
class CellStyle:
    """How one cell is drawn. Frozen so identical formats can share a single object."""

    color: str | None = None
    """Font colour as `#rrggbb`, or None to inherit the canvas."""
    background: str | None = None
    """Solid fill as `#rrggbb`, or None for no fill."""
    bold: bool = False
    italic: bool = False
    align: str = "left"
    """Already resolved to left/right/center: Excel's implicit default needs the cell's
    Python type, which only the loader still has."""


DEFAULT = CellStyle()


@lru_cache(maxsize=512)
def rich_style(style: CellStyle) -> Style:
    """The Rich style for a cell, built once per distinct format."""
    return Style(
        color=style.color,
        bgcolor=style.background,
        bold=style.bold or None,
        italic=style.italic or None,
    )


class StyledCell:
    """A spreadsheet cell as a renderable: display text plus the style it is drawn with.

    Both render paths use this, so a sheet looks the same piped as it does in the app.
    It is a slotted wrapper rather than a `rich.text.Text` because a DataTable keeps
    every cell it is given for the life of the table, and a Text costs several times as
    much per cell.
    """

    __slots__ = ("text", "style")

    def __init__(self, text: str, style: CellStyle = DEFAULT) -> None:
        self.text = text
        self.style = style

    def __rich_console__(self, console, options):
        # justify is honoured because both hosts render a cell into a fixed-width
        # region; no_wrap is left unset so each host keeps its own wrapping rules.
        yield Text(
            self.text, style=rich_style(self.style), justify=self.style.align, end=""
        )

    def __rich_measure__(self, console, options):
        return Measurement.get(console, options, Text(self.text, end=""))

    @property
    def plain(self) -> str:
        """The text without its styling, as `rich.text.Text` spells it. Textual reaches
        for this on column labels, so it is part of the contract, not a convenience."""
        return self.text

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"StyledCell({self.text!r}, {self.style!r})"

    def __eq__(self, other) -> bool:
        if isinstance(other, StyledCell):
            return self.text == other.text and self.style == other.style
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.text, self.style))


# -- colour ------------------------------------------------------------------


def theme_colors(theme_xml: bytes | None) -> tuple[str, ...]:
    """The workbook's 12 theme colours, in the order cell colours index them.

    `<a:clrScheme>` lists dk1, lt1, dk2, lt2 but cells index lt1, dk1, lt2, dk2, so the
    first two pairs are swapped on the way out. Falls back to the Office palette for a
    workbook with no theme part or one we cannot parse.
    """
    if not theme_xml:
        return DEFAULT_THEME
    try:
        root = ET.fromstring(theme_xml)
        scheme = root.find(f".//{_DRAW}clrScheme")
        if scheme is None:
            return DEFAULT_THEME
        found: dict[str, str] = {}
        for child in scheme:
            name = child.tag.removeprefix(_DRAW)
            srgb = child.find(f"{_DRAW}srgbClr")
            if srgb is not None and srgb.get("val"):
                found[name] = "#" + srgb.get("val", "").lower()
                continue
            system = child.find(f"{_DRAW}sysClr")
            if system is not None and system.get("lastClr"):
                found[name] = "#" + system.get("lastClr", "").lower()
        if not found:
            return DEFAULT_THEME
        ordered = [
            found.get(name, DEFAULT_THEME[i]) for i, name in enumerate(_SCHEME_ORDER)
        ]
        ordered[0], ordered[1] = ordered[1], ordered[0]
        ordered[2], ordered[3] = ordered[3], ordered[2]
        return tuple(ordered)
    except (ET.ParseError, ValueError, IndexError):
        return DEFAULT_THEME


def apply_tint(color: str, tint: float) -> str:
    """Lighten (tint > 0) or darken (tint < 0) `#rrggbb` the way OOXML asks."""
    if not tint:
        return color
    red, green, blue = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    hue, lum, sat = colorsys.rgb_to_hls(red, green, blue)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    red, green, blue = colorsys.hls_to_rgb(hue, min(max(lum, 0.0), 1.0), sat)
    return "#%02x%02x%02x" % (round(red * 255), round(green * 255), round(blue * 255))


def resolve_color(color, theme: tuple[str, ...] = DEFAULT_THEME) -> str | None:
    """One openpyxl Color as `#rrggbb`, or None when it means "unset".

    Branching on `color.type` is the only safe way to read one: every other accessor
    returns a descriptor error *message* as a string when it is not the live type, and
    those strings are truthy. `.auto` included.
    """
    if color is None:
        return None
    kind = getattr(color, "type", None)
    if kind == "auto":
        return None
    if kind == "rgb":
        value = color.value
        if not isinstance(value, str) or len(value) < 6:
            return None
        return "#" + value[-6:].lower()
    if kind == "indexed":
        from openpyxl.styles.colors import COLOR_INDEX

        index = color.value
        # 64 and 65 mean "system foreground/background"; they are past the table's end.
        if not isinstance(index, int) or not 0 <= index < len(COLOR_INDEX):
            return None
        return "#" + COLOR_INDEX[index][-6:].lower()
    if kind == "theme":
        index = color.value
        if not isinstance(index, int) or not 0 <= index < len(theme):
            return None
        return apply_tint(theme[index], float(getattr(color, "tint", 0.0) or 0.0))
    return None


# -- column widths -----------------------------------------------------------


def column_widths(worksheet) -> dict[int, int]:
    """1-based column index to width in terminal cells, from the sheet's `<cols>`.

    `read_only=True` drops `column_dimensions` entirely, so this streams the sheet XML
    instead. `<cols>` always precedes `<sheetData>`, so the parse stops there and reads
    a few hundred bytes however big the sheet is. Only columns Excel marks
    `customWidth` are reported; the rest size better from their content.

    Widths are cosmetic, so every failure here is swallowed.
    """
    widths: dict[int, int] = {}
    source = None
    try:
        source = worksheet._get_source()
        for event, element in ET.iterparse(source, events=("start", "end")):
            if event == "start":
                if element.tag == _SHEET_DATA:
                    break
                continue
            if element.tag != _COL:
                continue
            if element.get("customWidth") not in ("1", "true"):
                element.clear()
                continue
            raw = element.get("width")
            first, last = element.get("min"), element.get("max")
            if raw and first and last:
                cells = round(float(raw))
                for index in range(int(first), int(last) + 1):
                    widths[index] = cells
            element.clear()
    except (ET.ParseError, OSError, ValueError, TypeError, AttributeError, KeyError):
        return {}
    finally:
        if source is not None:
            try:
                source.close()
            except Exception:  # pragma: no cover - a closed stream is fine
                pass
    return widths


# -- number formats ----------------------------------------------------------

_NUMERIC_CORE = re.compile(r"^[#,]*[#0,]*(\.[#0]*)?$")
_CURRENCY = re.compile(r"^\[\$([^\]-]*)")


def _sections(fmt: str) -> list[str]:
    """Split a format on its top-level `;`, ignoring ones inside quotes or brackets."""
    parts, current, quoted, depth = [], [], False, 0
    index = 0
    while index < len(fmt):
        char = fmt[index]
        if char == "\\" and index + 1 < len(fmt):
            current.append(fmt[index : index + 2])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "[":
            depth += 1
        elif not quoted and char == "]":
            depth = max(0, depth - 1)
        elif char == ";" and not quoted and not depth:
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _parse_section(section: str) -> tuple[str, str, str, bool] | None:
    """Split one section into (prefix, numeric core, suffix, red).

    None when the section asks for something outside the subset: scientific notation,
    fractions, or a trailing comma (which scales by a thousand).
    """
    prefix, suffix, core = [], [], []
    red = False
    index = 0
    seen_core = False
    while index < len(section):
        char = section[index]
        target = suffix if seen_core else prefix
        if char == "[":
            end = section.find("]", index)
            if end == -1:
                return None
            token = section[index : end + 1]
            if token.lower() == "[red]":
                red = True
            else:
                money = _CURRENCY.match(token)
                if money:
                    target.append(money.group(1))
                elif not re.fullmatch(r"\[[a-zA-Z]+\]", token):
                    # a condition like [>100] or a locale we cannot honour
                    return None
            index = end + 1
            continue
        if char == '"':
            end = section.find('"', index + 1)
            if end == -1:
                return None
            target.append(section[index + 1 : end])
            index = end + 1
            continue
        if char == "\\" and index + 1 < len(section):
            target.append(section[index + 1])
            index += 2
            continue
        if char == "_" and index + 1 < len(section):
            target.append(" ")
            index += 2
            continue
        if char == "*" and index + 1 < len(section):
            index += 2
            continue
        if char in "#0,." and not suffix:
            core.append(char)
            seen_core = True
            index += 1
            continue
        if char in "?/":
            return None  # a fraction
        if char in "Ee" and index + 1 < len(section) and section[index + 1] in "+-":
            return None  # scientific notation
        target.append(char)
        index += 1
    body = "".join(core)
    if body.partition(".")[0].endswith(","):
        return None  # a trailing comma scales the value by a thousand
    return "".join(prefix), body, "".join(suffix), red


def number_text(value, number_format: str) -> tuple[str, bool] | None:
    """Format a number the way a supported Excel format code asks: (text, red).

    None for anything outside the supported subset — percentages, currency and literal
    affixes, thousands separators, decimal places, a negative section and `[Red]`. Dates,
    durations, scientific notation, fractions and `General` all fall back to the caller.
    """
    if not number_format or number_format == "General":
        return None
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return None

    sections = _sections(number_format)
    negative = value < 0
    section = sections[1] if negative and len(sections) > 1 and sections[1] else sections[0]
    explicit_negative = negative and section is not sections[0]

    parsed = _parse_section(section)
    if parsed is None:
        return None
    prefix, core, suffix, red = parsed

    percents = prefix.count("%") + suffix.count("%")
    if not core or not _NUMERIC_CORE.match(core):
        return None

    number = abs(value) if explicit_negative or negative else value
    number = float(number) * (100**percents)

    integer, _, fraction = core.partition(".")
    decimals = len(fraction)
    grouped = "," in integer
    text = f"{number:,.{decimals}f}" if grouped else f"{number:.{decimals}f}"
    if fraction and "0" not in fraction:
        text = text.rstrip("0").rstrip(".")
    text = prefix + text + suffix
    # The sign sits outside any currency symbol: -$800.00, not $-800.00.
    if negative and not explicit_negative:
        text = "-" + text
    return text, red and negative


# -- alignment ---------------------------------------------------------------

_ALIGNMENTS = {
    "left": "left",
    "right": "right",
    "center": "center",
    "centerContinuous": "center",
    "justify": "left",
    "distributed": "left",
    "fill": "left",
    "general": "",
}


def implicit_align(value) -> str:
    """What Excel does with a cell that does not ask for an alignment."""
    if isinstance(value, bool):
        return "center"
    if isinstance(value, (int, float, Decimal, datetime, date, time)):
        return "right"
    return "left"


def cell_style(cell, theme: tuple[str, ...], cache: dict) -> CellStyle:
    """The interned CellStyle for one openpyxl cell.

    Cells sharing a format share an object: the workbook's own style index is the cache
    key, so each distinct format is resolved once however many cells use it.
    """
    align = _ALIGNMENTS.get(getattr(cell.alignment, "horizontal", None) or "", "")
    align = align or implicit_align(cell.value)
    style_id = getattr(cell, "_style_id", None)
    if style_id is None:
        # EmptyCell, the filler for gaps inside a row, carries no style at all.
        return DEFAULT if align == "left" else CellStyle(align=align)

    key = (style_id, align)
    found = cache.get(key)
    if found is not None:
        return found

    font, fill = cell.font, cell.fill
    background = None
    # An unfilled cell still reports a black fgColor, so the pattern gates the colour.
    if fill is not None and fill.patternType == "solid":
        background = resolve_color(fill.fgColor, theme)
    color = resolve_color(getattr(font, "color", None), theme) if font else None
    # Every ordinary cell claims theme 1, which is the default text colour rather than
    # a choice the author made. Treating it as unset is what keeps `colored` meaningful.
    if color is not None and color == theme[1]:
        color = None
    style = CellStyle(
        color=color,
        background=background,
        bold=bool(getattr(font, "bold", False)),
        italic=bool(getattr(font, "italic", False)),
        align=align,
    )
    if style == DEFAULT:
        style = DEFAULT
    cache[key] = style
    return style
