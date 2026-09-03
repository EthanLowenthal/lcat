"""Write an edited document back to the file it came from."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

from lcat.loaders import CodeDoc, Document, JsonFormat, MarkdownDoc, TableDoc


class SaveError(Exception):
    """This document cannot be written, with a reason fit to show the user."""


def _uncell(text: str, is_text: bool) -> object:
    """Turn a displayed cell back into a JSON value.

    Columns whose source values were strings stay strings; anywhere else an empty
    cell is null and anything JSON can parse keeps its type, so numbers edited in
    the table go back as numbers.
    """
    if is_text:
        return text
    if text == "":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _text_flags(doc: TableDoc) -> list[bool]:
    flags = list(doc.fmt.text_columns)
    return flags + [False] * (len(doc.columns) - len(flags))


def _json_data(doc: TableDoc) -> object:
    shape = doc.fmt.shape
    flags = _text_flags(doc)
    if shape == "records":
        return [
            {
                column: _uncell(cell, text)
                for column, cell, text in zip(doc.columns, row, flags)
            }
            for row in doc.rows
        ]
    if shape == "rows":
        return [[_uncell(cell, text) for cell, text in zip(row, flags)] for row in doc.rows]
    if shape == "scalars":
        return [_uncell(row[0], flags[0]) for row in doc.rows]
    if shape == "keyvalue":
        # One object: the type to keep belongs to the key, not to the column.
        per_key = list(doc.fmt.text_rows)
        per_key += [False] * (len(doc.rows) - len(per_key))
        return {row[0]: _uncell(row[1], text) for row, text in zip(doc.rows, per_key)}
    raise SaveError(f"cannot write back a {shape} table")


def _json_text(doc: TableDoc) -> str:
    data = _json_data(doc)
    if doc.fmt.lines and isinstance(data, list):
        return "".join(
            json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n"
            for item in data
        )
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _delimited_text(doc: TableDoc) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=doc.fmt.delimiter, lineterminator="\n")
    if doc.fmt.has_header:
        writer.writerow(doc.columns)
    writer.writerows(doc.rows)
    return out.getvalue()


def serialize(doc: Document) -> str:
    """The document as file text, in the format it was read from."""
    if isinstance(doc, (MarkdownDoc, CodeDoc)):
        return doc.text
    if isinstance(doc, TableDoc):
        if isinstance(doc.fmt, JsonFormat):
            return _json_text(doc)
        return _delimited_text(doc)
    raise TypeError(f"cannot serialize {type(doc).__name__}")


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temporary file in the same directory, so a failure leaves the
    original intact."""
    tmp = path.with_name(f".{path.name}.lcat-tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def save(doc: Document, encoding: str = "utf-8") -> Path:
    """Write `doc` back to its path. Returns the path written."""
    path = doc.path
    if path is None:
        raise SaveError("nothing to write to: the input came from stdin")
    if isinstance(doc, TableDoc) and doc.total_rows is not None:
        raise SaveError("only the first rows were loaded (--max-rows), refusing to write")
    _atomic_write(path, serialize(doc).encode(encoding))
    return path
