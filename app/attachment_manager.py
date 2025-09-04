from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

import weasyprint  # type: ignore
from bs4 import BeautifulSoup, Tag

if TYPE_CHECKING:  # imports used only for type hints
    from collections.abc import Sequence

    from fastapi import UploadFile


class AttachmentManager:
    """
    Utilities for handling HTML-referenced attachments and uploaded files.

    Methods mirror the previous module-level functions:
      - find_referenced_attachment_names(soup) -> set[str]
      - rewrite_attachment_links_to_file_uri(soup, name_to_path) -> BeautifulSoup
      - save_uploads_to_tmpdir(files, tmpdir) -> dict[str, Path]  (async)
      - build_attachments_for_unreferenced(name_to_path, referenced) -> list[weasyprint.Attachment]

    Additionally provides a convenience orchestrator:
      - process_html_and_uploads(parsed_html, files, tmpdir) -> tuple[BeautifulSoup, list[weasyprint.Attachment]]
        which performs the 4-step flow in one call.
    """

    def __init__(self, default_tmpdir: Path | None = None) -> None:
        self.default_tmpdir = default_tmpdir

    # ---------- HTML parsing helpers ----------

    def find_referenced_attachment_names(self, soup: BeautifulSoup) -> set[str]:
        """
        Collect file names mentioned in <a|link rel="attachment" href="...">.
        Returns basenames (no path segments).
        """
        names: set[str] = set()

        for tag in soup.find_all(["a", "link"]):
            if not isinstance(tag, Tag):
                continue

            rels = tag.get("rel")
            rel_list = ([r.strip().lower() for r in rels.split()] if rels else []) if isinstance(rels, str) else [str(r).lower() for r in rels] if isinstance(rels, list | tuple) else []
            if "attachment" not in rel_list:
                continue

            href = tag.get("href")
            if isinstance(href, str):
                names.add(Path(unquote(href)).name)

        return names

    def rewrite_attachment_links_to_file_uri(
        self,
        soup: BeautifulSoup,
        name_to_path: dict[str, Path],
    ) -> BeautifulSoup:
        """
        Rewrite href in <a|link rel="attachment"...> to absolute file:// URIs
        so that PDF viewers can click and open the embedded file.
        """
        for tag in soup.find_all(["a", "link"]):
            if not isinstance(tag, Tag):
                continue

            rels = tag.get("rel")
            rel_list = ([r.strip().lower() for r in rels.split()] if rels else []) if isinstance(rels, str) else [str(r).lower() for r in rels] if isinstance(rels, list | tuple) else []
            if "attachment" not in rel_list:
                continue

            href = tag.get("href")
            if not isinstance(href, str):
                continue

            name = Path(unquote(href)).name
            p = name_to_path.get(name)
            if not p:
                continue

            tag["href"] = p.resolve().as_uri()

        return soup

    # ---------- Upload handling ----------

    async def save_uploads_to_tmpdir(
        self,
        files: Sequence[UploadFile] | None,
        tmpdir: Path | None = None,
    ) -> dict[str, Path]:
        """
        Save uploaded files into tmpdir preserving original names (and uniquifying if needed).
        Returns mapping {basename -> saved Path}.
        """
        mapping: dict[str, Path] = {}
        if not files:
            return mapping

        target_dir = tmpdir or self.default_tmpdir
        if target_dir is None:
            raise ValueError("tmpdir is required (not provided and no default_tmpdir set)")

        target_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            content = await f.read()
            name = Path(f.filename).name if f.filename and f.filename.strip() else "attachment.bin"

            path = target_dir.joinpath(name)
            i = 1
            while path.exists():
                path = path.with_name(f"{path.stem} ({i}){path.suffix}")
                i += 1

            with path.open("wb") as out:
                out.write(content)

            mapping[name] = path

        return mapping

    # ---------- WeasyPrint attachments ----------

    def build_attachments_for_unreferenced(
        self,
        name_to_path: dict[str, Path],
        referenced: set[str],
    ) -> list[weasyprint.Attachment]:
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

    # ---------- Orchestrator ----------

    async def process_html_and_uploads(
        self,
        parsed_html: BeautifulSoup,
        files: Sequence[UploadFile] | None,
        tmpdir: Path | None = None,
    ) -> tuple[BeautifulSoup, list[weasyprint.Attachment]]:
        """
        Perform the 4-step flow:
          1) find names referenced in HTML via rel="attachment"
          2) persist uploads into tmpdir and get mapping {name -> Path}
          3) build attachments only for files NOT referenced in HTML
          4) rewrite rel="attachment" hrefs to absolute file:// URIs pointing to saved files

        Returns updated BeautifulSoup and a list of attachments.
        """
        referenced: set[str] = self.find_referenced_attachment_names(parsed_html)
        name_to_path: dict[str, Path] = await self.save_uploads_to_tmpdir(files, tmpdir or self.default_tmpdir)
        attachments: list[weasyprint.Attachment] = self.build_attachments_for_unreferenced(name_to_path, referenced)
        updated_html = self.rewrite_attachment_links_to_file_uri(parsed_html, name_to_path)
        return updated_html, attachments
