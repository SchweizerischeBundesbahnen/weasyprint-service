import asyncio
import io
from pathlib import Path

from fastapi import UploadFile
import weasyprint  # type: ignore

from app.attachment_manager import AttachmentManager
from app.html_parser import HtmlParser


def test_extracts_basenames_and_decodes():
    html = (
        '<a rel="attachment" href="/files/report%20final.pdf">Report</a>'
        "<link REL='attachment' href='images/photo.png'>"
        '<a href="nope.txt">ignore</a>'
        '<a rel="attachment">missing</a>'
    )
    names = AttachmentManager().find_referenced_attachment_names(HtmlParser().parse(html))
    assert names == {"report final.pdf", "photo.png"}


def test_ignores_non_attachment_and_other_tags():
    html = (
        '<a rel="stylesheet" href="/x.css">X</a>'
        "<link rel='preload' href='a.bin'>"
        '<p rel="attachment" href="weird">text</p>'
    )
    assert AttachmentManager().find_referenced_attachment_names(HtmlParser().parse(html)) == set()


def test_rewrites_only_attachment_links_matching_name(tmp_path: Path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.txt"
    a.write_bytes(b"PDF")
    b.write_text("hello")

    html = (
        f"<a rel=\"attachment\" href=\"{a.name}\">A</a>"
        f"<a REL='attachment' href='sub/dir/{b.name}'>B</a>"
        f"<a rel=\"attachment\" href=\"missing.bin\">M</a>"
        f"<a rel=\"stylesheet\" href=\"{a.name}\">CSS</a>"
    )
    html_parser = HtmlParser()
    parsed_html = AttachmentManager().rewrite_attachment_links_to_file_uri(html_parser.parse(html), {a.name: a, b.name: b})
    out = html_parser.serialize(parsed_html)

    assert f'href="{a.resolve().as_uri()}"' in out
    assert f'href="{b.resolve().as_uri()}"' in out
    # missing mapping unchanged
    assert 'href="missing.bin"' in out
    # non-attachment unchanged
    assert 'rel="stylesheet"' in out


def test_handles_urlencoded_names(tmp_path: Path):
    f = tmp_path / "my file.txt"
    f.write_text("x")
    html = "<a rel='attachment' href='dir/my%20file.txt'>click</a>"
    html_parser = HtmlParser()
    parsed_html = AttachmentManager().rewrite_attachment_links_to_file_uri(html_parser.parse(html), {f.name: f})
    out = html_parser.serialize(parsed_html)

    assert f.resolve().as_uri() in out


def _mk_upload(content: bytes, filename: str | None) -> UploadFile:
    fileobj = io.BytesIO(content)
    # UploadFile accepts a file-like object and optional filename
    return UploadFile(filename=filename, file=fileobj)


def test_saves_files_and_uniquifies_names(tmp_path: Path):
    up1 = _mk_upload(b"one", "doc.txt")
    up2 = _mk_upload(b"two", "doc.txt")
    up3 = _mk_upload(b"bin", None)

    mapping = asyncio.run(AttachmentManager().save_uploads_to_tmpdir([up1, up2, up3], tmp_path))

    # Original base name should point to the last saved unique path
    assert set(mapping.keys()) == {"doc.txt", "attachment.bin"}
    p1 = mapping["doc.txt"]
    assert p1.exists()
    assert p1.name in {"doc.txt", "doc (1).txt"}
    # Since the second had the same name, ensure either order produced a unique name existing on disk
    other_name = "doc (1).txt" if p1.name == "doc.txt" else "doc.txt"
    assert (tmp_path / other_name).exists()

    p2 = mapping["attachment.bin"]
    assert p2.exists()
    assert p2.read_bytes() == b"bin"


def test_empty_or_none_files_returns_empty_mapping(tmp_path: Path):
    attachment_manager = AttachmentManager()
    assert asyncio.run(attachment_manager.save_uploads_to_tmpdir([], tmp_path)) == {}
    assert asyncio.run(attachment_manager.save_uploads_to_tmpdir(None, tmp_path)) == {}


def test_builds_for_unreferenced_and_avoids_duplicates(tmp_path: Path):
    p1 = tmp_path / "a.pdf"
    p2 = tmp_path / "b.pdf"
    p1.write_text("a")
    p2.write_text("b")

    mapping = {"a.pdf": p1, "b.pdf": p2, "alias-b.pdf": p2}
    referenced = {"a.pdf"}

    atts = AttachmentManager().build_attachments_for_unreferenced(mapping, referenced)

    # Only b.pdf once
    assert len(atts) == 1
    assert isinstance(atts[0], weasyprint.Attachment)
    # weasyprint.Attachment doesn't expose original filename; ensure it yields a file source
    # In WeasyPrint 68.0, source context manager returns tuple (file_obj, url, None, None)
    with atts[0].source as (file_obj, url, _, _):
        assert hasattr(file_obj, 'read')
        assert url.startswith('file://')


def test_all_referenced_results_empty(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"x")
    atts = AttachmentManager().build_attachments_for_unreferenced({"x.bin": p}, {"x.bin"})
    assert atts == []
