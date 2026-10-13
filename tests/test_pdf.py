import io
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import Static

from lcat import views
from lcat.app import LcatApp
from lcat.cli import main
from lcat.detect import is_pdf, mode_from_extension, resolve_mode
from lcat.loaders import PdfDoc, load, load_pdf
from lcat.plain import render
from lcat.views import PdfView


def pdf_bytes(*pages: list[str]) -> bytes:
    """A minimal PDF: one page per list of lines, set in Helvetica. An empty list makes
    a page with no text on it, like a scan."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, once the page numbers are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for lines in pages:
        page = len(objects) + 1
        kids.append(f"{page} 0 R")
        ops = ["BT", "/F1 14 Tf", "72 720 Td", "18 TL"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({escaped}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page + 1} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


THREE_PAGES = pdf_bytes(["Chapter one", "It begins (here)."], ["Chapter two"], [])


@pytest.fixture
def pixels(monkeypatch):
    """Pretend the terminal draws real pixels, so the view starts on the picture."""
    monkeypatch.setattr(views, "has_pixels", lambda: True)


# -- detection ---------------------------------------------------------------


def test_pdf_extension():
    assert mode_from_extension(Path("paper.PDF")) == "pdf"


def test_pdf_magic():
    assert is_pdf(THREE_PAGES)
    assert is_pdf(b"\x00junk\n" + THREE_PAGES)
    assert not is_pdf(b"#" * 2000 + b" a markdown file about %PDF-")
    assert resolve_mode(None, "auto", "%PDF-1.4", raw=THREE_PAGES) == "pdf"
    assert resolve_mode(Path("paper"), "auto", "%PDF-1.4", raw=THREE_PAGES) == "pdf"


# -- loading -----------------------------------------------------------------


def test_load_pdf_pages_and_text():
    doc = load_pdf(THREE_PAGES, Path("paper.pdf"))
    assert isinstance(doc, PdfDoc)
    assert doc.page_count == 3
    assert doc.page_text(0) == "Chapter one\nIt begins (here)."
    assert doc.page_text(1) == "Chapter two"
    assert doc.page_text(2) == ""


def test_page_image_is_rendered_and_cached():
    doc = load_pdf(THREE_PAGES)
    image = doc.page_image(0)
    assert image.size == (1224, 1584)  # letter at 144 dpi
    assert doc.page_image(0) is image


def test_load_pdf_rejects_garbage():
    with pytest.raises(ValueError, match="not a readable PDF"):
        load_pdf(b"%PDF-1.4 and then nothing")


def test_load_refuses_pdf_mode_from_text():
    with pytest.raises(ValueError, match="load_pdf"):
        load("x", "pdf")


# -- plain -------------------------------------------------------------------


def test_plain_prints_every_page():
    console = Console(file=io.StringIO(), width=60, color_system=None)
    render(load_pdf(THREE_PAGES), console)
    out = console.file.getvalue()
    assert "Chapter one\nIt begins (here)." in out
    assert "page 2" in out and "Chapter two" in out
    assert "page 3" in out and "(no text on this page)" in out
    assert "page 1" not in out


def test_cli_plain(tmp_path, capsys):
    path = tmp_path / "paper.pdf"
    path.write_bytes(THREE_PAGES)
    assert main([str(path), "-p"]) == 0
    assert "Chapter two" in capsys.readouterr().out


def test_cli_rejects_broken_pdf(tmp_path, capsys):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 truncated")
    assert main([str(path), "-p"]) == 2
    assert "not a readable PDF" in capsys.readouterr().err


# -- interactive -------------------------------------------------------------


def page_text(app: LcatApp) -> str:
    return str(app.query_one("#page-text", Static).render())


async def test_starts_on_text_without_pixels():
    app = LcatApp(load_pdf(THREE_PAGES, Path("paper.pdf")))
    async with app.run_test() as pilot:
        view = app.query_one(PdfView)
        assert view.pdf.as_text
        assert "Chapter one" in page_text(app)
        assert not view.image_widget.display
        assert "page 1 of 3 · text" in app.sub_title
        await pilot.press("right_square_bracket")
        assert "Chapter two" in page_text(app)
        await pilot.press("right_square_bracket")
        assert "(no text on this page)" in page_text(app)
        assert "page 3 of 3" in app.sub_title


async def test_paging_and_toggling_text(pixels):
    app = LcatApp(load_pdf(THREE_PAGES, Path("paper.pdf")))
    seen: list[str] = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: seen.append(message)
        view = app.query_one(PdfView)
        assert not view.pdf.as_text
        assert view.image_widget.display
        assert not app.query_one("#page-text").display
        assert app.sub_title == "paper.pdf · page 1 of 3"

        await pilot.press("left_square_bracket")
        assert seen[-1] == "first page" and view.pdf.index == 0
        await pilot.press("right_square_bracket")
        assert view.pdf.index == 1
        assert view.image_widget.image is view.pdf.page_image(1)

        await pilot.press("t")
        assert view.pdf.as_text and "Chapter two" in page_text(app)
        assert "page 2 of 3 · text" in app.sub_title
        await pilot.press("z")
        assert "t shows it" in seen[-1]
        await pilot.press("t")
        assert not view.pdf.as_text and view.image_widget.display


async def test_pdf_is_read_only(pixels):
    app = LcatApp(load_pdf(THREE_PAGES, Path("paper.pdf")))
    seen: list[str] = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: seen.append(message)
        await pilot.press("ctrl+s")
        assert seen == ["PDF files are read-only"]


async def test_reload_keeps_page_and_reading(tmp_path, pixels):
    path = tmp_path / "paper.pdf"
    path.write_bytes(THREE_PAGES)

    def reload():
        return load_pdf(path.read_bytes(), path)

    app = LcatApp(reload(), reload=reload)
    async with app.run_test() as pilot:
        await pilot.press("right_square_bracket", "t")
        path.write_bytes(pdf_bytes(["One"], ["Two, revised"], ["Three"], ["Four"]))
        await app.reload_from_disk()
        view = app.query_one(PdfView)
        assert view.pdf.index == 1 and view.pdf.as_text
        assert "Two, revised" in page_text(app)
        assert "page 2 of 4" in app.sub_title

        # A shorter PDF clamps to its last page.
        await pilot.press("right_square_bracket", "right_square_bracket")
        path.write_bytes(pdf_bytes(["Only"]))
        await app.reload_from_disk()
        assert app.query_one(PdfView).pdf.index == 0
        assert "Only" in page_text(app)
