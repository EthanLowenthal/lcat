import contextlib
import io
from pathlib import Path

import pytest
from PIL import Image as PILImage
from textual.widgets import Markdown
from textual.widgets.markdown import MarkdownBlock

from lcat.app import LcatApp
from lcat.detect import is_image, mode_from_extension, resolve_mode
from lcat.images import browser_url, local_path
from lcat.loaders import ImageDoc, load, load_image
from lcat.plain import render
from lcat.save import SaveError, serialize
from lcat.views import ImageView, image_run


def png_bytes(width: int = 40, height: int = 20, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), "orange").save(buffer, fmt)
    return buffer.getvalue()


# -- detection ---------------------------------------------------------------


def test_image_extensions():
    for suffix in (".png", ".jpg", ".JPEG", ".bmp", ".gif", ".webp"):
        assert mode_from_extension(Path(f"a{suffix}")) == "img"


def test_magic_bytes():
    assert is_image(png_bytes())
    assert is_image(png_bytes(fmt="JPEG"))
    assert is_image(png_bytes(fmt="BMP"))
    assert is_image(png_bytes(fmt="GIF"))
    assert not is_image(b"BMW,price\n3,50000\n")
    assert not is_image(b"a,b\n1,2\n")


def test_resolve_mode_sniffs_images_without_an_extension():
    data = png_bytes()
    assert resolve_mode(Path("photo"), "auto", "�PNG", raw=data) == "img"
    assert resolve_mode(None, "auto", "�PNG", raw=data) == "img"
    assert (
        resolve_mode(Path("photo"), "auto", "a,b\n1,2\n3,4\n", raw=b"a,b\n1,2\n3,4\n")
        == "csv"
    )


# -- loading -----------------------------------------------------------------


def test_load_image():
    doc = load_image(png_bytes(40, 20), Path("a.png"))
    assert isinstance(doc, ImageDoc)
    assert doc.size == (40, 20)
    assert doc.format == "PNG"


def test_load_image_rejects_garbage():
    with pytest.raises(ValueError):
        load_image(b"not an image at all")


def test_load_refuses_img_mode_from_text():
    with pytest.raises(ValueError):
        load("x", "img")


def test_images_cannot_be_saved():
    with pytest.raises(SaveError):
        serialize(load_image(png_bytes()))


# -- link targets ------------------------------------------------------------


def test_link_targets():
    base = Path("/docs")
    assert browser_url("https://example.com/x", base) == "https://example.com/x"
    assert browser_url("mailto:a@b.c", base) == "mailto:a@b.c"
    assert browser_url("#heading", base) is None
    assert (
        browser_url("guide/intro.md#top", base)
        == (base / "guide/intro.md").resolve().as_uri()
    )
    assert local_path("pics/a%20b.png", base) == base / "pics/a b.png"
    assert local_path("https://example.com/a.png", base) is None


# -- plain output ------------------------------------------------------------


def test_plain_render_describes_the_image_in_a_pipe():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        render(load_image(png_bytes(40, 20), Path("shot.png")))
    assert "shot.png" in buffer.getvalue()
    assert "40×20" in buffer.getvalue()


# -- image view --------------------------------------------------------------


async def test_image_file_opens_the_image_view():
    app = LcatApp(load_image(png_bytes(40, 20), Path("shot.png")))
    async with app.run_test() as pilot:
        view = app.query_one("#view")
        assert isinstance(view, ImageView)
        assert "shot.png" in app.sub_title and "PNG" in app.sub_title
        assert view.fit
        await pilot.press("z")
        assert not view.fit
        await pilot.press("z")
        assert view.fit


async def test_fit_never_upscales_and_actual_size_is_one_to_one():
    app = LcatApp(load_image(png_bytes(1600, 1600), Path("big.png")))
    async with app.run_test(size=(80, 24)) as pilot:
        view = app.query_one(ImageView)
        image = view.image_widget
        assert image.size.height <= view.size.height
        assert image.size.width < 80
        fit_size = image.size
        await pilot.press("z")
        await pilot.pause()
        assert image.size.height > fit_size.height  # 1600px tall is more than a screen
        assert image.size.width > fit_size.width


async def test_small_image_keeps_its_natural_size():
    app = LcatApp(load_image(png_bytes(40, 20), Path("icon.png")))
    async with app.run_test(size=(80, 24)):
        image = app.query_one(ImageView).image_widget
        assert image.size.width <= 5  # 40px is only a few cells wide


# -- markdown images ---------------------------------------------------------


def test_image_run_only_accepts_image_only_paragraphs():
    from markdown_it import MarkdownIt

    def inline(text):
        return next(t for t in MarkdownIt("gfm-like").parse(text) if t.type == "inline")

    assert image_run(inline("![a](a.png)")) == [("a.png", "a")]
    assert image_run(inline("![a](a.png)\n![b](b.png)")) == [("a.png", "a"), ("b.png", "b")]
    assert image_run(inline("see ![a](a.png)")) == []
    assert image_run(inline("plain text")) == []


def markdown_app(tmp_path: Path, text: str, **kwargs) -> LcatApp:
    (tmp_path / "pic.png").write_bytes(png_bytes(40, 20))
    return LcatApp(load(text, "md", tmp_path / "notes.md"), **kwargs)


async def test_local_markdown_images_are_rendered(tmp_path):
    app = markdown_app(tmp_path, "# T\n\n![a picture](pic.png)\n\nafter\n")
    async with app.run_test():
        images = app.query(".markdown-image")
        assert len(images) == 1
        assert images.first().tooltip == "a picture"
        paragraph = images.first().parent
        assert isinstance(paragraph, MarkdownBlock)
        assert paragraph._content.plain == ""
        assert images.first().size.width > 0


async def test_missing_and_remote_images_keep_their_alt_text(tmp_path):
    text = "![gone](nope.png)\n\n![badge](https://img.example/x.svg)\n"
    app = markdown_app(tmp_path, text)
    async with app.run_test():
        assert not app.query(".markdown-image")
        blocks = app.query(MarkdownBlock)
        plain = " ".join(block._content.plain for block in blocks)
        assert "gone" in plain and "badge" in plain


async def test_no_images_shows_alt_text(tmp_path):
    app = markdown_app(tmp_path, "![a picture](pic.png)\n", images=False)
    async with app.run_test():
        assert not app.query(".markdown-image")
        assert any("a picture" in b._content.plain for b in app.query(MarkdownBlock))


async def test_editing_rerenders_images(tmp_path):
    app = markdown_app(tmp_path, "hello\n")
    async with app.run_test() as pilot:
        assert not app.query(".markdown-image")
        await pilot.press("i")
        app.query_one("#editor").text = "![p](pic.png)\n"
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.query(".markdown-image")) == 1


# -- markdown links ----------------------------------------------------------


def link_styles(app: LcatApp):
    for block in app.query(MarkdownBlock):
        contents = [block._content]
        # table cells are folded into the table block, not mounted themselves
        contents += getattr(block, "_headers", [])
        contents += [cell for row in getattr(block, "_rows", []) for cell in row]
        for content in contents:
            for span in content.spans:
                if getattr(span.style, "link", None):
                    yield span.style


async def test_links_carry_terminal_hyperlinks(tmp_path):
    text = "See [the docs](https://example.com/docs) or [local](guide.md#top).\n"
    app = markdown_app(tmp_path, text)
    async with app.run_test():
        links = [style.link for style in link_styles(app)]
        assert "https://example.com/docs" in links
        assert (tmp_path / "guide.md").resolve().as_uri() in links
        # the click action Textual uses for its own handling is still there
        assert all("@click" in style.meta for style in link_styles(app))


async def test_links_in_headings_lists_and_tables_too(tmp_path):
    text = (
        "# [Title](https://t.example)\n\n"
        "- [item](https://i.example)\n\n"
        "| a |\n| - |\n| [cell](https://c.example) |\n"
    )
    app = markdown_app(tmp_path, text)
    async with app.run_test():
        links = {style.link for style in link_styles(app)}
        assert {"https://t.example", "https://i.example", "https://c.example"} <= links


async def test_clicking_a_link_opens_the_browser(tmp_path):
    app = markdown_app(tmp_path, "[docs](https://example.com/docs) [rel](other.md)\n")
    opened = []
    async with app.run_test() as pilot:
        app.open_url = lambda url, **kwargs: opened.append(url)
        markdown = app.query_one(Markdown)
        markdown.post_message(Markdown.LinkClicked(markdown, "https://example.com/docs"))
        markdown.post_message(Markdown.LinkClicked(markdown, "other.md"))
        await pilot.pause()
        assert opened == [
            "https://example.com/docs",
            (tmp_path / "other.md").resolve().as_uri(),
        ]
        assert isinstance(app.query_one("#view").document, Markdown)  # still our doc


async def test_anchor_links_scroll_instead_of_opening(tmp_path):
    body = "\n\n".join(f"para {i}" for i in range(80))
    app = markdown_app(tmp_path, f"[go](#target)\n\n{body}\n\n## Target\n\nend\n")
    opened = []
    async with app.run_test() as pilot:
        app.open_url = lambda url, **kwargs: opened.append(url)
        view = app.query_one("#view")
        markdown = app.query_one(Markdown)
        markdown.post_message(Markdown.LinkClicked(markdown, "#target"))
        await pilot.pause()
        await pilot.pause()
        assert opened == []
        assert view.scroll_offset.y > 0
