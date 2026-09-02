"""Turn raw file text into one of three simple documents the views can render."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from lcat.detect import sniff_delimiter


@dataclass
class MarkdownDoc:
    text: str
    path: Path | None = None


@dataclass
class TableDoc:
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)
    path: Path | None = None
    total_rows: int | None = None
    """Row count before `--max-rows` trimmed it, when it did."""

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.columns)

    def head(self, max_rows: int | None) -> "TableDoc":
        """This table, trimmed to `max_rows`, remembering the original count."""
        if max_rows is None or len(self.rows) <= max_rows:
            return self
        return TableDoc(self.columns, self.rows[:max_rows], self.path, len(self.rows))


@dataclass
class CodeDoc:
    text: str
    lexer: str = "text"
    path: Path | None = None


Document = MarkdownDoc | TableDoc | CodeDoc


def _cell(value: object) -> str:
    """Render a JSON value as a single-line string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_markdown(text: str, path: Path | None = None) -> MarkdownDoc:
    return MarkdownDoc(text, path)


def load_delimited(
    text: str,
    path: Path | None = None,
    delimiter: str | None = None,
    has_header: bool = True,
) -> TableDoc:
    if delimiter is None:
        delimiter = sniff_delimiter(text[:8192])
    raw = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    raw = [row for row in raw if row and any(cell.strip() for cell in row)]
    if not raw:
        return TableDoc([], [], path)

    width = max(len(row) for row in raw)
    if has_header:
        header = raw[0] + [""] * (width - len(raw[0]))
        columns = [name.strip() or f"col{i + 1}" for i, name in enumerate(header)]
        body = raw[1:]
    else:
        columns = [f"col{i + 1}" for i in range(width)]
        body = raw

    rows = [row[:width] + [""] * (width - len(row)) for row in body]
    return TableDoc(columns, rows, path)


def load_json(text: str, path: Path | None = None) -> TableDoc | CodeDoc:
    data, is_lines = _parse_json(text)
    if data is None:
        return CodeDoc(text, "json", path)

    if isinstance(data, list) and data:
        if all(isinstance(item, dict) for item in data):
            columns: list[str] = []
            seen: set[str] = set()
            for item in data:
                for key in item:
                    if key not in seen:
                        seen.add(key)
                        columns.append(key)
            rows = [[_cell(item.get(key)) for key in columns] for item in data]
            return TableDoc(columns, rows, path)
        if all(isinstance(item, list) for item in data):
            width = max((len(item) for item in data), default=0)
            columns = [f"col{i + 1}" for i in range(width)]
            rows = [
                [_cell(v) for v in item] + [""] * (width - len(item)) for item in data
            ]
            return TableDoc(columns, rows, path)
        if all(not isinstance(item, (dict, list)) for item in data):
            return TableDoc(["value"], [[_cell(item)] for item in data], path)

    if isinstance(data, dict) and data and not is_lines:
        rows = [[key, _cell(value)] for key, value in data.items()]
        return TableDoc(["key", "value"], rows, path)

    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    return CodeDoc(pretty, "json", path)


def _parse_json(text: str) -> tuple[object | None, bool]:
    """Parse JSON or JSON Lines. Returns (data, was_json_lines)."""
    stripped = text.strip()
    if not stripped:
        return None, False
    try:
        return json.loads(stripped), False
    except ValueError:
        pass

    items = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except ValueError:
            return None, False
    return (items, True) if items else (None, False)


def load(
    text: str,
    mode: str,
    path: Path | None = None,
    delimiter: str | None = None,
    has_header: bool = True,
) -> Document:
    if mode == "md":
        return load_markdown(text, path)
    if mode == "json":
        return load_json(text, path)
    if mode == "tsv":
        return load_delimited(text, path, delimiter or "\t", has_header)
    if mode == "csv":
        return load_delimited(text, path, delimiter, has_header)
    raise ValueError(f"unknown mode: {mode!r}")
