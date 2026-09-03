# lcat

A `cat` that renders. Point it at a markdown file and get styled, scrollable prose with a
table-of-contents jump list; point it at a CSV and get a full-screen table you can walk with the
arrow keys, search, sort, and copy from.

```
lcat notes.md
lcat data.csv
lcat records.json
```

Markdown, CSV, TSV and JSON (including JSON Lines) are supported. Press `i` to edit what you are
looking at and `ctrl+s` to write it back. When stdout is not a terminal (`lcat notes.md | less -R`)
it prints a static render and exits, so it stays usable in a pipe.

## Install

```sh
uv tool install git+https://github.com/EthanLowenthal/lcat   # or, from a clone:
uv tool install .
```

## Usage

```
lcat [FILE|-] [options]

  --mode {auto,md,csv,tsv,json}   force a renderer (default: auto, by extension then sniffing)
  -p, --plain                     static render to stdout instead of the interactive view
  -d, --delimiter CHAR            delimiter for csv/tsv (default: sniffed)
  --no-header                     treat the first row as data, name columns col1..colN
  --encoding ENC                  input encoding (default: utf-8)
  --max-rows N                    show only the first N rows of a table
  --version
```

`-` reads from stdin: `psql -Atc '...' | lcat - --mode csv`.

## Keys

Everywhere: `i` edit, `ctrl+s` write the file, `q` quit, `?` help, `ctrl+p` command palette
(themes and commands).

Markdown / code view:

| Key | Action |
| --- | --- |
| `↑` `↓` `j` `k` | scroll a line |
| `pgup` `pgdn` `ctrl+u` `ctrl+d` | scroll a page |
| `g` `G` `home` `end` | top / bottom |
| `t` | toggle the table of contents (markdown only) |
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
with `--max-rows`, which would write back only the head.

## Notes

- Format detection is by extension first, then by content, so extensionless files and stdin
  still land in the right view. A markdown pipe table is treated as markdown, not as
  pipe-delimited data.
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
```
