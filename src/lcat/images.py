"""Helpers shared by the image views: terminal cell geometry and link targets.

Rendering itself is done by textual-image, which picks the best protocol the
terminal supports (Sixel, the kitty graphics protocol, or coloured half-cells)
when it is imported. That import queries the terminal, so it has to happen
before Textual starts reading the keyboard; `views` and `plain` import it only
on the interactive / tty paths.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote, urlsplit

FALLBACK_CELL = (10, 20)
"""Cell size in pixels when the terminal cannot be asked (VT340 dimensions)."""

_BROWSER_SCHEMES = {"http", "https", "mailto", "file", "ftp"}


def silence_cell_size_probe() -> None:
    r"""Keep textual-image's cell size probe from printing a traceback.

    textual-image asks the terminal for its cell size with `\x1b[16t` and, when
    no reply arrives within its 0.1s timeout, logs a warning *with a traceback*
    and falls back to FALLBACK_CELL. Plenty of terminals never answer (ssh,
    screen, anything without the xterm window-ops), and nothing is broken when
    they don't, so the traceback is pure noise on an otherwise clean start.

    Called from `lcat/__init__.py`, which Python runs before any `lcat` module
    can import textual_image -- importing `textual_image.widget` probes at once.
    """
    logging.getLogger("textual_image._terminal").setLevel(logging.ERROR)


def cell_size() -> tuple[int, int]:
    """The terminal's cell size in pixels, (width, height)."""
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        return int(size.width) or FALLBACK_CELL[0], int(size.height) or FALLBACK_CELL[1]
    except (ImportError, OSError, ValueError):  # pragma: no cover - private API
        return FALLBACK_CELL


def natural_cells(width_px: int, height_px: int) -> tuple[int, int]:
    """How many cells an image covers at one image pixel per screen pixel."""
    cell_w, cell_h = cell_size()
    return max(1, round(width_px / cell_w)), max(1, round(height_px / cell_h))


def is_url(target: str) -> bool:
    """True for a link target with a scheme (http, mailto, ...), not a local path."""
    scheme = urlsplit(target).scheme
    return len(scheme) > 1 and scheme.lower() in _BROWSER_SCHEMES


def local_path(target: str, base: Path) -> Path | None:
    """The file a markdown link or image source points at, or None for a URL/anchor."""
    if not target or target.startswith("#") or is_url(target):
        return None
    location = unquote(target.partition("#")[0])
    if not location:
        return None
    return (base / location).expanduser()


def browser_url(target: str, base: Path) -> str | None:
    """Something a browser can open for a link target, or None for an in-page anchor."""
    if is_url(target):
        return target
    path = local_path(target, base)
    if path is None:
        return None
    return path.resolve().as_uri()
