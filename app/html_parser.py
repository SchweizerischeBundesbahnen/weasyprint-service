from __future__ import annotations

import re
from typing import TypedDict
from weakref import WeakKeyDictionary

from bs4 import BeautifulSoup, Comment


class _Meta(TypedDict):
    was_full_document: bool
    xml_decl: str


class HtmlParser:
    """
    Class-based HTML (de)serializer around BeautifulSoup.

    - parse(string) -> BeautifulSoup
      * Detects full document vs fragment
      * Extracts and stores XML declaration (<?xml ...?>)
      * Removes leading <!--?xml ... ?--> comment artifacts

    - serialize(soup) -> str
      * If full document: returns soup as-is (+ restored XML declaration).
      * If fragment: returns inner body contents (fallback: whole soup).

    Metadata is always stored in a WeakKeyDictionary sidecar mapping bound to the parser instance.
    """

    def __init__(
        self,
        parser: str = "html5lib",
        formatter: str = "minimal",
    ) -> None:
        self.parser = parser
        self.formatter = formatter
        self._meta: WeakKeyDictionary[BeautifulSoup, _Meta] = WeakKeyDictionary()

    # -------- Public API --------

    def parse(self, string: str) -> BeautifulSoup:
        """
        Parse HTML string into BeautifulSoup and remember:
        - was it a full document?
        - original XML declaration (<?xml ...?>)
        """
        xml_decl = self._extract_xml_decl(string)
        is_full_document = self._is_full_document(string)

        html = BeautifulSoup(string, self.parser)
        html = self._clear_leading_comment(html)

        self._set_meta(html, was_full_document=is_full_document, xml_decl=xml_decl)
        return html

    def serialize(self, html: BeautifulSoup) -> str:
        """
        Serialize BeautifulSoup back to string.
        - If it was a full document: return as-is (+ restored XML declaration).
        - If it was a fragment: return only inner body contents (fallback: whole soup).
        """
        meta = self._get_meta(html)
        if meta is None:
            # Fallback: infer document type directly from soup structure
            inferred_full = html.find("html") is not None
            xml_decl = ""
            was_full = inferred_full
        else:
            xml_decl = meta["xml_decl"]
            was_full = meta["was_full_document"]

        if was_full:
            result = html.decode(formatter=self.formatter)
            if xml_decl:
                result = f"{xml_decl}{result}"
            return result

        body = html.body
        if body is None:
            return html.decode(formatter=self.formatter)
        return body.decode_contents(formatter=self.formatter)

    # -------- Internal helpers --------

    def _set_meta(self, soup: BeautifulSoup, *, was_full_document: bool, xml_decl: str) -> None:
        meta: _Meta = {"was_full_document": was_full_document, "xml_decl": xml_decl}
        self._meta[soup] = meta

    def _get_meta(self, soup: BeautifulSoup) -> _Meta | None:
        return self._meta.get(soup)

    @staticmethod
    def _clear_leading_comment(html: BeautifulSoup) -> BeautifulSoup:
        """Removes comment like <!--?xml ... ?--> left by some parsers."""
        if html.contents and isinstance(html.contents[0], Comment) and str(html.contents[0]).strip().startswith("?xml"):
            html.contents[0].extract()
        return html

    @staticmethod
    def _extract_xml_decl(s: str) -> str:
        s2 = s.lstrip()
        if s2.startswith("<?xml"):
            end = s2.find("?>")
            if end != -1:
                return s2[: end + 2]
        return ""

    @staticmethod
    def _is_full_document(s: str) -> bool:
        _COMMENT_RE = re.compile(r"(?is)<!--.*?-->")
        _DOC_MARKER_RE = re.compile(r"(?is)(<!doctype\b|<html\b)")

        # 1) remove comments not to catch <html> inside <!-- ... -->
        cleaned = _COMMENT_RE.sub("", s)
        # 2) check if <!DOCTYPE ...> or <html ...> exist
        return bool(_DOC_MARKER_RE.search(cleaned))
