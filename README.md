# lcat

A `cat` that renders. Point it at a markdown file and get styled, scrollable prose with a
table-of-contents jump list, clickable links and inline images; point it at a CSV and get a
full-screen table you can walk with the arrow keys, search, sort, and copy from; point it at a
spreadsheet and get the same table, a sheet at a time; point it at a PNG and see the picture.

```
lcat notes.md
lcat data.csv
lcat records.json
lcat book.xlsx
lcat photo.png
```

Markdown, CSV, TSV, JSON (including JSON Lines), xlsx workbooks and PNG/JPEG/GIF/BMP/WebP/TIFF
images are supported. Press `i` to edit what you are looking at and `ctrl+s` to write it back
(xlsx is read-only). The view follows the file: when something else writes it, lcat reloads it
in place (`R` toggles this, `r` reloads on demand). When stdout is not a terminal
(`lcat notes.md | less -R`) it prints a static render and exits, so it stays usable in a pipe.

## Install

```sh
uv tool install git+https://github.com/EthanLowenthal/lcat   # or, from a clone:
uv tool install .
```

## Usage

```
lcat [FILE|-] [options]

  --mode {auto,md,csv,tsv,json,xlsx,img}
                                  force a renderer (default: auto, by extension then sniffing)
  -p, --plain                     static render to stdout instead of the interactive view
  -d, --delimiter CHAR            delimiter for csv/tsv (default: sniffed)
  --no-header                     treat the first row as data, name columns col1..colN
                                  (A..Z for a worksheet)
  --encoding ENC                  input encoding (default: utf-8)
  --max-rows N                    show only the first N rows of a table
  --no-images                     show markdown images as their alt text
  --no-reload                     start with auto-reload off
  --version
```

`-` reads from stdin: `psql -Atc '...' | lcat - --mode csv`, `curl -s .../chart.png | lcat -`.

## Keys

Everywhere: `i` edit, `ctrl+s` write the file, `r` reload from disk, `R` toggle auto-reload,
`q` quit, `?` help, `ctrl+p` command palette (themes and commands).

Markdown / code view:

| Key | Action |
| --- | --- |
| `↑` `↓` `j` `k` | scroll a line |
| `pgup` `pgdn` `ctrl+u` `ctrl+d` | scroll a page |
| `g` `G` `home` `end` | top / bottom |
| `t` | toggle the table of contents (markdown only) |
| click a link | open it in the browser (`#anchors` scroll to the heading) |
| `i` | edit the raw text; `esc` renders it again |

Table view:

| Key | Action |
| --- | --- |
| arrows / `h` `j` `k` `l` | move the cell cursor |
| `g` `G` | first / last row |
| `^` `$` | first / last column |
| `pgup` `pgdn` | scroll a page |
| `enter` | show the full cell value |
| `/` then `n` / `N` | search cells, next / previous match |
| `s` | sort by this column: ascending, descending, original |
| `y` / `Y` | copy the cell / the row |
| `i` | edit this cell in the full-value modal; `esc` keeps the edit |

Workbook view (xlsx): the table keys above, minus editing, plus

| Key | Action |
| --- | --- |
| `]` `[` | next / previous sheet |
| `f` | show formulas instead of the values Excel computed |

Image view:

| Key | Action |
| --- | --- |
| `z` | toggle fit-to-window / actual size |
| arrows / `h` `j` `k` `l` | scroll (at actual size) |
| `pgup` `pgdn` `ctrl+u` `ctrl+d` | scroll a page |
| `g` `G` `home` `end` | top / bottom |

## Editing

`i` is insert. In the markdown and JSON views it swaps the rendered page for the raw text, with
line numbers; `esc` leaves insert mode and renders it again. In a table it opens the same modal
`enter` uses to show a full cell value, but editable, so long or multi-line cells have room.

Nothing touches the disk until you ask: `esc` keeps an edit in the buffer (`ctrl+z` inside the
editor undoes), the subtitle shows `modified`, and `ctrl+s` writes the file — from inside the
editor too. Quitting with unsaved edits asks first.

Files are written in the format they were read from, through a temporary file in the same
directory, so a failed write leaves the original alone. Saving normalizes as the parser saw the
file: blank lines and ragged rows go, quoting is minimal, and a JSON table is re-indented with two
spaces (one document per line for JSON Lines) with every record carrying the union of the keys.
Cell types survive a round trip — a column that held numbers stays numbers, a column that held
strings stays strings. `lcat -` cannot save (there is no file), and neither can a table loaded
with `--max-rows`, which would write back only the head, nor an xlsx, which is read-only.

## Spreadsheets

An xlsx opens in the table view, one worksheet at a time, with a strip of sheet names above the
table and the active sheet in the subtitle; `]` and `[` walk them. Cells show the value Excel
last computed and saved, so a formula whose result was never written to the file reads as empty;
`f` swaps the whole sheet to the formula text (`=C2*D2`) and back. Trailing blank rows and
columns are dropped, so the table is the size it looks in Excel, while gaps inside the sheet are
kept — an unnamed column keeps its spreadsheet letter. Dates come out as `2026-03-04`,
timestamps as `2026-03-04 09:30:00`, and number formats (currency, percent, decimal places) are
not applied: you get the underlying value.

Workbooks are read-only. openpyxl cannot round-trip everything an xlsx holds — charts, images
and pivot tables do not survive a save — so `i` and `ctrl+s` decline rather than quietly drop
parts of your file. `.xlsm` reads too (the macros are ignored); `.xls`, the pre-2007 binary
format, does not.

## Following the file

Once a second lcat checks the file's modification time and size, and when they change it
reads the file again with the same options and updates the view in place: the table keeps its
cursor, sort is reset, the search is re-run, markdown and code keep their scroll position, an
image keeps its zoom, and a workbook stays on the sheet you were reading (matched by name) in
whichever of the value and formula readings you had up. If the file turns into a different kind
of document (a JSON table that stops being tabular, say) the view is swapped. The subtitle shows
`watching` while this is on; `R` toggles it and `--no-reload` starts with it off.

Unsaved edits are never overwritten: if the file changes while the subtitle says `modified`
(or while you are in insert mode) lcat only warns. `r` is the explicit reload and discards the
edits. Your own `ctrl+s` is not treated as a change, and a file that cannot be read mid-write
(a half-written image, an empty file) leaves the old view up with an error notification. Input
from stdin has no file to watch.

## Images and links

Images are drawn with real pixels where the terminal can: Sixel (iTerm2, WezTerm, foot,
mlterm, recent xterm) or the kitty graphics protocol, detected by asking the terminal on
startup. Anywhere else they fall back to coloured half-cell blocks, which is still a
recognisable picture. Fit-to-window never scales an image up past one image pixel per screen
pixel; `z` switches to actual size and scrolls.

In markdown, a paragraph that is only an image (or several, one per line) becomes the picture,
sized to its own pixels or the window, whichever is smaller. Sources are resolved relative to
the markdown file. Remote images and images mixed into a sentence keep Textual's text form,
`🖼 (alt text)`, as does everything with `--no-images`.

Links are clickable: URLs open in the default browser, relative paths open as `file://` URLs,
and `#anchor` links scroll to the heading. Link text also carries an OSC 8 hyperlink, so
terminals that support them (iTerm2, kitty, WezTerm, GNOME Terminal, Windows Terminal) let you
cmd/ctrl-click straight through without lcat's help; others ignore it.

`lcat -p photo.png` on a terminal prints the picture inline and exits, like `imgcat`. In a pipe
it prints a one-line summary (`photo.png: PNG image, 480×270 px`).

## Notes

- Format detection is by extension first, then by content, so extensionless files and stdin
  still land in the right view. A markdown pipe table is treated as markdown, not as
  pipe-delimited data, and image files and xlsx workbooks are recognised by their magic bytes.
- Textual's `DataTable` measures every cell it is handed, so very large tables are streamed in
  batches: the first screenful appears immediately and the status line shows the progress. A
  50k-row, 10 MB CSV paints in about a quarter of a second and finishes loading in about two and
  a half. Use `--max-rows` if you only want the head of something enormous.
- Sorting is numeric-aware: `10` sorts before `200`, and non-numeric values sort after numbers
  with empty cells last.

## Development

```sh
uv sync
uv run pytest -q
uv run lcat samples/sample.csv
uv run lcat samples/nested.json   # JSON that is not a table: the raw code view
uv run lcat samples/sample.md     # includes an image and links
uv run lcat samples/sample.xlsx  # three sheets, a formula column ([ ] and f)
uv run lcat samples/sample.png
```
