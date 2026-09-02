import contextlib
import io

from lcat.loaders import load
from lcat.plain import render


def capture(doc, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        render(doc, **kwargs)
    return buffer.getvalue()


def test_markdown_plain_render():
    out = capture(load("# Title\n\nbody text\n", "md"))
    assert "Title" in out
    assert "body text" in out


def test_table_plain_render():
    out = capture(load("a,b\n1,2\n", "csv"))
    assert "a" in out and "b" in out and "1" in out


def test_head_truncates_and_reports():
    doc = load("a\n" + "\n".join(str(i) for i in range(50)) + "\n", "csv")
    trimmed = doc.head(5)
    assert len(trimmed.rows) == 5
    assert trimmed.total_rows == 50
    assert "45 more rows" in capture(trimmed)


def test_head_is_a_noop_when_it_fits():
    doc = load("a\n1\n2\n", "csv")
    assert doc.head(10) is doc
    assert doc.head(None) is doc
