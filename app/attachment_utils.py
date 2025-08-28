import re
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

import weasyprint  # type: ignore
from fastapi import UploadFile


def find_referenced_attachment_names(html: str) -> set[str]:
    """
    Collect file names mentioned in <a|link rel="attachment" href="...">.
    Returns basenames (no path segments).
    """
    tag_pattern = re.compile(r"<(?P<tag>a|link)\b[^>]*?>", re.IGNORECASE)
    rel_attachment = re.compile(r'\brel\s*=\s*([\'"])attachment\1', re.IGNORECASE)
    href_attr = re.compile(r'\bhref\s*=\s*(?P<q>[\'"])(?P<href>.+?)(?P=q)', re.IGNORECASE)

    names: set[str] = set()
    for m in tag_pattern.finditer(html):
        tag_html = m.group(0)
        if not rel_attachment.search(tag_html):
            continue
        hm = href_attr.search(tag_html)
        if hm:
            names.add(Path(unquote(hm.group("href"))).name)
    return names


def rewrite_attachment_links_to_file_uri(html: str, name_to_path: dict[str, Path]) -> str:
    """
    Rewrite href in <a|link rel="attachment"...> to absolute file:// URIs
    so that PDF viewers can click and open the embedded file.
    """
    tag_pattern = re.compile(r"<(?P<tag>a|link)\b[^>]*?>", re.IGNORECASE)
    rel_attachment = re.compile(r'\brel\s*=\s*([\'"])attachment\1', re.IGNORECASE)
    href_attr = re.compile(r'\bhref\s*=\s*(?P<q>[\'"])(?P<href>.+?)(?P=q)', re.IGNORECASE)

    def fix_tag(m: re.Match) -> str:
        tag_html = m.group(0)
        if not rel_attachment.search(tag_html):
            return tag_html
        href_m = href_attr.search(tag_html)
        if not href_m:
            return tag_html
        href_val = href_m.group("href")
        name = Path(unquote(href_val)).name
        p = name_to_path.get(name)
        if not p:
            return tag_html
        file_uri = p.resolve().as_uri()
        start, end = href_m.span("href")
        return tag_html[:start] + file_uri + tag_html[end:]

    return tag_pattern.sub(fix_tag, html)


async def save_uploads_to_tmpdir(files: Sequence[UploadFile] | None, tmpdir: Path) -> dict[str, Path]:
    """
    Save uploaded files into tmpdir preserving original names (and uniquifying if needed).
    Returns mapping {basename -> saved Path}.
    """
    mapping: dict[str, Path] = {}
    if not files:
        return mapping

    for f in files:
        # read content
        content = await f.read()
        name = Path(f.filename).name if f.filename else "attachment.bin"

        path = tmpdir.joinpath(name)
        i = 1
        while path.exists():
            path = path.with_name(f"{path.stem} ({i}){path.suffix}")
            i += 1

        with path.open("wb") as out:
            out.write(content)

        mapping[name] = path

    return mapping


def build_attachments_for_unreferenced(name_to_path: dict[str, Path], referenced: set[str]) -> list[weasyprint.Attachment]:
    """
    Build a list of weasyprint.Attachment for files that are not referenced in HTML.
    Avoid duplicates by path.
    """
    attachments: list[weasyprint.Attachment] = []
    added: set[Path] = set()
    for name, path in name_to_path.items():
        if name in referenced:
            continue
        if path in added:
            continue
        attachments.append(weasyprint.Attachment(filename=str(path)))
        added.add(path)
    return attachments
