from __future__ import annotations

import logging
from typing import TypedDict
from weakref import WeakKeyDictionary

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

# Maximum length for truncated log messages
MAX_LOG_MESSAGE_LENGTH = 50


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
        logger.debug("Parsing HTML string, size: %d characters", len(string))
        xml_decl = self._extract_xml_decl(string)
        if xml_decl:
            # Sanitize XML declaration for logging - remove control characters
            safe_xml_decl = "".join(c if c.isprintable() and c not in "\n\r" else "_" for c in xml_decl)
            truncated = safe_xml_decl[:MAX_LOG_MESSAGE_LENGTH]
            logger.debug("Found XML declaration: %s", truncated + "..." if len(safe_xml_decl) > len(truncated) else safe_xml_decl)
        is_full_document = self._is_full_document(string)
        logger.debug("Document type: %s", "full document" if is_full_document else "fragment")

        html = BeautifulSoup(string, self.parser)
        html = self._clear_leading_comment(html)

        self._set_meta(html, was_full_document=is_full_document, xml_decl=xml_decl)
        logger.info("HTML parsed successfully using %s parser", self.parser)
        return html

    def serialize(self, html: BeautifulSoup) -> str:
        """
        Serialize BeautifulSoup back to string.
        - If it was a full document: return as-is (+ restored XML declaration).
        - If it was a fragment: return only inner body contents (fallback: whole soup).
        """
        logger.debug("Serializing HTML back to string")
        meta = self._get_meta(html)
        if meta is None:
            # Fallback: infer document type directly from soup structure
            inferred_full = html.find("html") is not None
            xml_decl = ""
            was_full = inferred_full
            logger.debug("No metadata found, inferring document type: %s", "full document" if was_full else "fragment")
        else:
            xml_decl = meta["xml_decl"]
            was_full = meta["was_full_document"]

        if was_full:
            result = html.decode(formatter=self.formatter)
            if xml_decl:
                result = f"{xml_decl}{result}"
            logger.info("Serialized full document, size: %d characters", len(result))
            return result

        body = html.body
        if body is None:
            result = html.decode(formatter=self.formatter)
            logger.info("Serialized HTML (no body found), size: %d characters", len(result))
            return result
        result = body.decode_contents(formatter=self.formatter)
        logger.info("Serialized fragment (body contents only), size: %d characters", len(result))
        return result

    # -------- Internal helpers --------

    @staticmethod
    def _startswith_ci(s: str, idx: int, token: str) -> bool:
        return s[idx : idx + len(token)].lower() == token

    @staticmethod
    def _try_skip_comment(s: str, idx: int) -> tuple[int, bool]:
        if s.startswith("<!--", idx):
            end = s.find("-->", idx + 4)
            return (-1 if end == -1 else end + 3, end != -1)
        return (idx, False)

    @staticmethod
    def _try_skip_pi(s: str, idx: int) -> tuple[int, bool]:
        if s.startswith("<?", idx):
            end = s.find("?>", idx + 2)
            return (-1 if end == -1 else end + 2, end != -1)
        return (idx, False)

    @staticmethod
    def _looks_like_html_tag(s: str, idx: int) -> bool:
        n = len(s)
        if not s.startswith("<", idx):
            return False
        j = idx + 1
        while j < n and s[j].isspace():
            j += 1
        if j < n and s[j : j + 4].lower() == "html":
            j2 = j + 4
            if j2 >= n:
                return True
            ch = s[j2]
            if ch.isspace() or ch in {">", "/"}:
                return True
        return False

    @staticmethod
    def _skip_ws(s: str, idx: int) -> int:
        n = len(s)
        while idx < n and s[idx].isspace():
            idx += 1
        return idx

    @staticmethod
    def _skip_ws_comments_and_pi(s: str, pos: int) -> int:
        n = len(s)
        pos = HtmlParser._skip_ws(s, pos)
        while pos < n:
            next_pos, ok = HtmlParser._try_skip_comment(s, pos)
            if ok:
                if next_pos == -1:
                    return n
                pos = HtmlParser._skip_ws(s, next_pos)
                continue
            next_pos, ok = HtmlParser._try_skip_pi(s, pos)
            if ok:
                if next_pos == -1:
                    return n
                pos = HtmlParser._skip_ws(s, next_pos)
                continue
            break
        return pos

    @staticmethod
    def _advance_to_next_angle(s: str, pos: int) -> int:
        n = len(s)
        if s.startswith("<", pos):
            j = pos + 1
            while j < n and s[j] != "<":
                j += 1
            return HtmlParser._skip_ws(s, j)
        return HtmlParser._skip_ws(s, pos + 1)

    def _set_meta(self, soup: BeautifulSoup, *, was_full_document: bool, xml_decl: str) -> None:
        meta: _Meta = {"was_full_document": was_full_document, "xml_decl": xml_decl}
        self._meta[soup] = meta

    def _get_meta(self, soup: BeautifulSoup) -> _Meta | None:
        return self._meta.get(soup)

    @staticmethod
    def _clear_leading_comment(html: BeautifulSoup) -> BeautifulSoup:
        """Removes comment like <!--?xml ... ?--> left by some parsers."""
        if html.contents and isinstance(html.contents[0], Comment) and str(html.contents[0]).strip().startswith("?xml"):
            logger.debug("Removing leading XML comment artifact")
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
        """Detect if input string is a full HTML/XHTML document without regex.

        Rules inferred from tests:
        - Allow leading BOM, whitespace, comments <!-- ... -->, and XML PI.
        - Consider a string a full document if, after skipping allowed leading
          constructs, we encounter either a <!DOCTYPE ...> declaration (any case)
          or an <html ...> start tag (any case).
        - Ignore <html> that appears inside comments.
        """
        i = 0
        n = len(s)

        # Skip BOM if present
        if i < n and s[i] == "\ufeff":
            i += 1

        i = HtmlParser._skip_ws_comments_and_pi(s, i)
        while i < n:
            if HtmlParser._startswith_ci(s, i, "<!doctype") or HtmlParser._looks_like_html_tag(s, i):
                return True
            i = HtmlParser._skip_ws_comments_and_pi(s, HtmlParser._advance_to_next_angle(s, i))
        return False
