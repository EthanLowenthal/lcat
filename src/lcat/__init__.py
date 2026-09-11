"""lcat - an interactive terminal viewer for markdown and tabular files."""

from lcat.images import silence_cell_size_probe

__version__ = "0.1.0"

# Before anything can import textual-image, which probes the terminal on import.
silence_cell_size_probe()
