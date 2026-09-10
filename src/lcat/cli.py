"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lcat import __version__
from lcat.detect import MODES, SNIFF_BYTES, resolve_mode
from lcat.loaders import Document, TableDoc, WorkbookDoc, load, load_image, load_xlsx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lcat",
        description="Render markdown, CSV/TSV, JSON, xlsx and image files in the terminal.",
    )
    parser.add_argument("file", help="file to view, or - for stdin")
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="auto",
        help="force a renderer (default: auto, by extension then content sniffing)",
    )
    parser.add_argument(
        "-p",
        "--plain",
        action="store_true",
        help="print a static render instead of the interactive view",
    )
    parser.add_argument(
        "-d",
        "--delimiter",
        help="delimiter for csv/tsv (default: sniffed)",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="treat the first row as data instead of column names",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="input encoding (default: utf-8)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        help="show only the first N rows of a table",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="show markdown images as their alt text instead of rendering them",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="start with auto-reload off (R toggles it in the viewer)",
    )
    parser.add_argument("--version", action="version", version=f"lcat {__version__}")
    return parser


def _fail(message: str) -> int:
    """Print to stderr and return the exit code to raise with."""
    print(message, file=sys.stderr)
    return 2


def _read_source(target: str) -> tuple[bytes, Path | None]:
    if target == "-":
        return sys.stdin.buffer.read(), None

    path = Path(target)
    if not path.exists():
        raise SystemExit(_fail(f"lcat: {target}: no such file"))
    if path.is_dir():
        raise SystemExit(_fail(f"lcat: {target}: is a directory"))
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SystemExit(_fail(f"lcat: {target}: {error.strerror or error}")) from error
    return data, path


def _reopen_tty() -> bool:
    """After reading stdin, reattach it to the terminal so the app can read keys."""
    try:
        tty = open("/dev/tty")
    except OSError:
        return False
    os.dup2(tty.fileno(), 0)
    return True


def _build(raw: bytes, path: Path | None, mode: str, args: argparse.Namespace) -> Document:
    """Turn file bytes into a document with the options given on the command line."""
    if mode == "img":
        return load_image(raw, path)
    if mode == "xlsx":
        return load_xlsx(
            raw, path, has_header=not args.no_header, max_rows=args.max_rows
        )
    doc = load(
        raw.decode(args.encoding, errors="replace"),
        mode,
        path=path,
        delimiter=args.delimiter,
        has_header=not args.no_header,
    )
    if isinstance(doc, TableDoc):
        doc = doc.head(args.max_rows)
    return doc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    raw, path = _read_source(args.file)
    if not raw.strip():
        print(f"lcat: {args.file}: empty file", file=sys.stderr)
        return 0

    head = raw[:SNIFF_BYTES]
    sample = head.decode(args.encoding, errors="replace")
    mode = resolve_mode(path, args.mode, sample, head)
    try:
        doc = _build(raw, path, mode, args)
    except ValueError as error:
        return _fail(f"lcat: {args.file}: {error}")

    if isinstance(doc, TableDoc) and not doc.columns:
        print(f"lcat: {args.file}: no rows to show", file=sys.stderr)
        return 0
    if isinstance(doc, WorkbookDoc) and not any(sheet.columns for sheet in doc.sheets):
        print(f"lcat: {args.file}: no rows to show", file=sys.stderr)
        return 0

    interactive = not args.plain and sys.stdout.isatty()
    if interactive and path is None and not _reopen_tty():
        print(
            "lcat: stdin is not a terminal, falling back to plain output",
            file=sys.stderr,
        )
        interactive = False

    if not interactive:
        from lcat.plain import render

        render(doc)
        return 0

    from lcat.app import LcatApp

    def reload() -> Document:
        """Read the file again, the same way. `path` is set: stdin cannot reload."""
        assert path is not None
        data = path.read_bytes()
        if not data.strip():
            raise ValueError("the file is empty")
        return _build(data, path, mode, args)

    LcatApp(
        doc,
        encoding=args.encoding,
        images=not args.no_images,
        reload=reload if path is not None else None,
        auto_reload=not args.no_reload,
    ).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
