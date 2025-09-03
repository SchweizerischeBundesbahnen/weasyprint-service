from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

import weasyprint  # type: ignore
from bs4 import BeautifulSoup, Tag
from fastapi import UploadFile


def find_referenced_attachment_names(soup: BeautifulSoup) -> set[str]:
    """
    Collect file names mentioned in <a|link rel="attachment" href="...">.
    Returns basenames (no path segments).
    """
    names: set[str] = set()

    for tag in soup.find_all(["a", "link"]):
        if not isinstance(tag, Tag):
            continue
        rels = tag.get("rel")
        if rels and "attachment" in [r.lower() for r in rels]:
            href = tag.get("href")
            if isinstance(href, str):
                names.add(Path(unquote(href)).name)

    return names


def rewrite_attachment_links_to_file_uri(soup: BeautifulSoup, name_to_path: dict[str, Path]) -> BeautifulSoup:
    """
    Rewrite href in <a|link rel="attachment"...> to absolute file:// URIs
    so that PDF viewers can click and open the embedded file.
    """
    for tag in soup.find_all(["a", "link"]):
        if not isinstance(tag, Tag):
            continue
        rels = tag.get("rel")
        if rels and "attachment" in [r.lower() for r in rels]:
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            name = Path(unquote(href)).name
            p = name_to_path.get(name)
            if not p:
                continue
            tag["href"] = p.resolve().as_uri()

    return soup


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
        name = Path(f.filename).name if f.filename and f.filename.strip() else "attachment.bin"

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
