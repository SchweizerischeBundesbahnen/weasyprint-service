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

    @staticmethod
    def _is_full_document2(s: str) -> bool:
        """
        Determine whether the given HTML string represents a full HTML document.

        Rules derived from tests:
        - Allow leading BOM, whitespace, HTML comments (<!-- -->), and processing
          instructions like XML declaration (<?xml ...?>) before the document.
        - A full document is present if, after skipping the above, we encounter:
          * <!DOCTYPE ...> possibly followed by more allowed prefixes and then an
            <html ...> root element; OR
          * directly an <html ...> root element (case-insensitive), including
            XHTML with xmlns attribute.
        - If any other content (text or non-comment/PI tags) appears before the
          <html> element (and not part of allowed prefixes), it's considered a fragment.
        """
        i = 0
        n = len(s)

        def startswith_ci(pos: int, prefix: str) -> bool:
            return s[pos:pos + len(prefix)].lower() == prefix.lower()

        # Helper: skip BOM once at the very beginning
        if s.startswith("\ufeff"):
            i = 1

        def skip_ws(pos: int) -> int:
            while pos < n and s[pos].isspace():
                pos += 1
            return pos

        def skip_comment(pos: int) -> int:
            # HTML comment <!-- ... --> (non-nested scanning)
            if s.startswith("<!--", pos):
                end = s.find("-->", pos + 4)
                if end == -1:
                    # Malformed comment; treat as content (fragment)
                    return pos
                return end + 3
            return pos

        def skip_pi(pos: int) -> int:
            # Processing instruction like <?xml ...?> or <?pi?>
            if s.startswith("<?", pos):
                end = s.find("?>", pos + 2)
                if end == -1:
                    return pos
                return end + 2
            return pos

        saw_doctype = False

        def style_has_break_after_page(tag_open: str) -> bool:
            # Check style attribute containing break-after: page (case-insensitive, spaces optional)
            # tag_open is like "<div ...>" without ensuring closure yet.
            # We only inspect within the opening tag up to '>':
            end = tag_open.find('>')
            if end == -1:
                end = len(tag_open)
            chunk = tag_open[:end]
            # find style="..." or style='...'
            lower = chunk.lower()
            idx = lower.find("style=")
            if idx == -1:
                return False
            # extract quoted value
            qpos = idx + len("style=")
            if qpos >= len(chunk):
                return False
            quote = chunk[qpos]
            if quote not in ('"', "'"):
                return False
            qpos += 1
            endq = chunk.find(quote, qpos)
            if endq == -1:
                return False
            val = chunk[qpos:endq].lower()
            # normalize spaces
            val = ' '.join(val.split())
            return "break-after: page" in val

        def skip_leading_page_break_div(pos: int) -> int:
            # Only allow exactly one specific div with break-after: page to be skipped
            if not startswith_ci(pos, "<div"):
                return pos
            # Find end of opening tag
            gt = s.find('>', pos + 4)
            if gt == -1:
                return pos
            tag_open = s[pos:gt + 1]
            if not style_has_break_after_page(tag_open):
                return pos
            # Now skip until matching </div>. We'll do a simple depth counter for nested divs
            depth = 1
            j = gt + 1
            while j < n and depth > 0:
                next_open = s.find('<div', j)
                next_open_ci = s.lower().find('<div', j)
                next_close = s.lower().find('</div', j)
                # choose nearest tag occurrence case-insensitively
                candidates = [c for c in [next_open_ci, next_close] if c != -1]
                if not candidates:
                    # no closing tag; malformed, do not skip
                    return pos
                k = min(candidates)
                if s.lower().startswith('<div', k):
                    depth += 1
                    j = s.find('>', k + 4)
                    if j == -1:
                        return pos
                    j += 1
                else:
                    # closing div
                    j2 = s.find('>', k)
                    if j2 == -1:
                        return pos
                    depth -= 1
                    j = j2 + 1
            return j if depth == 0 else pos

        while True:
            prev = i
            i = skip_ws(i)

            # Comments
            new_i = skip_comment(i)
            if new_i != i:
                i = new_i
                continue

            # Processing instruction (XML decl or others)
            new_i = skip_pi(i)
            if new_i != i:
                i = new_i
                continue

            # Allow a single leading page-break div wrapper before the real document
            new_i = skip_leading_page_break_div(i)
            if new_i != i:
                i = new_i
                continue

            # Doctype
            if s.startswith("<", i):
                if startswith_ci(i, "<!doctype"):
                    # Skip doctype declaration up to '>'
                    end = s.find(">", i + 9)
                    if end == -1:
                        return False
                    i = end + 1
                    saw_doctype = True
                    # loop to allow further comments/PI/whitespace before <html>
                    continue
                elif startswith_ci(i, "<html"):
                    return True
                else:
                    # Some other tag before <html> → fragment
                    return False
            # If not starting with '<' and we have any non-space text here → fragment
            if i < n and not s[i].isspace():
                return False

            # Only whitespace remains
            if i >= n:
                # No <html> encountered
                return False

            # prevent infinite loop if no progress
            if i == prev:
                # Should not happen; treat conservatively
                return False
