"""Work out what kind of file we were handed."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path

MODES = ("auto", "md", "csv", "tsv", "json", "img")

_EXTENSIONS = {
    ".md": "md",
    ".markdown": "md",
    ".mdown": "md",
    ".mkd": "md",
    ".csv": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
    ".png": "img",
    ".jpg": "img",
    ".jpeg": "img",
    ".bmp": "img",
    ".gif": "img",
    ".webp": "img",
    ".tif": "img",
    ".tiff": "img",
}

SNIFF_BYTES = 8192

_CANDIDATE_DELIMITERS = (",", "\t", ";", "|")
_MIN_AGREEMENT = 0.8
"""Fraction of head rows that must share a field count for a delimiter to win."""

_MD_TABLE_RULE = re.compile(r"^\s*\|?[\s:-]*\|[\s:|-]*$")
"""The `|---|---|` rule under a markdown table header."""

_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
    b"II*\x00",  # TIFF, little endian
    b"MM\x00*",  # TIFF, big endian
)


def mode_from_extension(path: Path) -> str | None:
    return _EXTENSIONS.get(path.suffix.lower())


def _head(sample: str, limit: int = 20) -> str:
    lines = [line for line in sample.strip().splitlines() if line.strip()]
    return "\n".join(lines[:limit])


def _score(head: str, delimiter: str) -> tuple[float, int] | None:
    """Rate a delimiter by how consistently it splits the head into wide rows.

    `csv.Sniffer` gives up on plausible files (a quoted cell containing commas is
    enough), so score the candidates ourselves with the real csv parser.
    """
    try:
        rows = [row for row in csv.reader(io.StringIO(head), delimiter=delimiter) if row]
    except csv.Error:
        return None
    if len(rows) < 2:
        return None
    width, count = Counter(len(row) for row in rows).most_common(1)[0]
    if width < 2:
        return None
    agreement = count / len(rows)
    if agreement < _MIN_AGREEMENT:
        return None
    return agreement, width


def best_delimiter(sample: str) -> str | None:
    """The most plausible delimiter for `sample`, or None if it isn't tabular."""
    head = _head(sample)
    best: tuple[tuple[float, int], str] | None = None
    for delimiter in _CANDIDATE_DELIMITERS:
        score = _score(head, delimiter)
        if score is not None and (best is None or score > best[0]):
            best = (score, delimiter)
    return best[1] if best else None


def sniff_delimiter(sample: str, default: str = ",") -> str:
    return best_delimiter(sample) or default


def is_image(data: bytes) -> bool:
    """True if `data` starts like one of the raster formats the image view reads."""
    if data.startswith(_IMAGE_MAGIC):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    # BMP: "BM", then the four reserved bytes after the file size are zero. "BM" on
    # its own would catch text that happens to start with those letters.
    return len(data) >= 14 and data[:2] == b"BM" and data[6:10] == b"\x00\x00\x00\x00"


def sniff_mode(sample: str) -> str:
    """Guess a mode from the head of a file. Falls back to markdown."""
    stripped = sample.strip()
    if stripped and stripped[0] in "[{":
        try:
            json.loads(stripped)
            return "json"
        except ValueError:
            # A truncated sample or JSON Lines: a complete first line is enough.
            try:
                json.loads(stripped.splitlines()[0])
                return "json"
            except (ValueError, IndexError):
                pass

    lines = stripped.splitlines()
    if any("|" in line and _MD_TABLE_RULE.match(line) for line in lines[:5]):
        # A pipe table: markdown, not a pipe-delimited data file.
        return "md"

    delimiter = best_delimiter(stripped)
    if delimiter is not None:
        return "tsv" if delimiter == "\t" else "csv"
    return "md"


def resolve_mode(
    path: Path | None, explicit: str, sample: str, raw: bytes | None = None
) -> str:
    """Resolve the render mode. `explicit` is one of MODES; `path` is None for stdin.

    `sample` is the decoded head of the file; `raw`, when given, is the same head
    as bytes so image files without an extension are still recognised.
    """
    if explicit != "auto":
        return explicit
    if path is not None:
        by_ext = mode_from_extension(path)
        if by_ext is not None:
            return by_ext
    if raw is not None and is_image(raw):
        return "img"
    return sniff_mode(sample)
