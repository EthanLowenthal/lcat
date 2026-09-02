# lcat

A `cat` that renders. Point it at a markdown file and get styled, scrollable prose with a
table-of-contents jump list; point it at a CSV and get a full-screen table you can walk with the
arrow keys, search, sort, and copy from.

```
lcat notes.md
lcat data.csv
lcat records.json
```

Markdown, CSV, TSV and JSON (including JSON Lines) are supported. When stdout is not a terminal
(`lcat notes.md | less -R`) it prints a static render and exits, so it stays usable in a pipe.

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

Everywhere: `q` quit, `?` help, `ctrl+p` command palette (themes and commands).

Markdown / code view:

| Key | Action |
| --- | --- |
| `↑` `↓` `j` `k` | scroll a line |
| `pgup` `pgdn` `ctrl+u` `ctrl+d` | scroll a page |
| `g` `G` `home` `end` | top / bottom |
| `t` | toggle the table of contents (markdown only) |

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
```
