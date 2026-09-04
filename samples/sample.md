# lcat

A `cat` that *renders*.

## Why

Reading a markdown file in a terminal usually means one of:

1. `cat` it and read the raw syntax
2. open an editor
3. give up and open a browser

None of those are great for a five-second look.

## Features

- Styled headings, lists, code and tables
- A table of contents you can jump from — press `t`
- Vim-ish scrolling: `j`, `k`, `g`, `G`, `ctrl+d`, `ctrl+u`

### Code

```python
def greet(name: str) -> str:
    return f"hello, {name}"
```

### A table

| format | view | interactive |
| ------ | ---- | ----------- |
| markdown | MarkdownViewer | scroll, contents |
| csv | DataTable | cell cursor, search, sort |
| json | DataTable or Syntax | depends on shape |

> Piping still works: `lcat notes.md | less -R`.

### An image

Local images render as pictures when the terminal can draw them (Sixel, kitty, or
coloured half-cells otherwise); remote ones stay as text.

![a gradient with two shapes](sample.png)

### Links

Links open in the browser when clicked, and terminals that understand hyperlinks let you
cmd/ctrl-click them directly: [Textual](https://textual.textualize.io),
[the source](https://github.com/EthanLowenthal/lcat), or a heading in this file: [Why](#why).

## Long section

Paragraph one, here to make the document long enough that scrolling actually does something
visible when you try it out.

Paragraph two. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua.

Paragraph three. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
aliquip ex ea commodo consequat.

Paragraph four. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu
fugiat nulla pariatur.
