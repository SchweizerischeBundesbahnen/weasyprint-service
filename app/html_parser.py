from __future__ import annotations

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
        """Detect if input string is a full HTML/XHTML document without regex.

        Rules inferred from tests:
        - Allow leading BOM, whitespace, comments <!-- ... -->, and XML PI.
        - Consider a string a full document if, after skipping allowed leading
          constructs, we encounter either:
            * a <!DOCTYPE ...> declaration (any case), or
            * an <html ...> start tag (any case).
        - Ignore any <html> that appears inside comments.
        """
        i = 0
        n = len(s)

        def startswith_ci(idx: int, token: str) -> bool:
            return s[idx:idx + len(token)].lower() == token

        # Skip BOM if present
        if i < n and s[i] == "\ufeff":
            i += 1

        while i < n:
            # Skip whitespace
            while i < n and s[i].isspace():
                i += 1
            if i >= n:
                return False

            # Comments <!-- ... -->
            if s.startswith("<!--", i):
                i += 4
                # find closing -->
                end = s.find("-->", i)
                if end == -1:
                    # Unclosed comment; treat as comment to the end
                    return False
                i = end + 3
                continue

            # Processing instruction / XML declaration <? ... ?>
            if s.startswith("<?", i):
                end = s.find("?>", i + 2)
                if end == -1:
                    return False
                i = end + 2
                continue

            # Doctype
            if startswith_ci(i, "<!doctype"):
                return True

            # <html ...>
            if s.startswith("<", i):
                j = i + 1
                # skip possible whitespace after '<'
                while j < n and s[j].isspace():
                    j += 1
                if j < n and s[j].lower() == 'h':
                    # check for 'html' name
                    if s[j:j+4].lower() == 'html':
                        j2 = j + 4
                        # next must be whitespace, '>' or attribute delimiter
                        if j2 < n:
                            ch = s[j2]
                            if ch.isspace() or ch == '>' or ch == '/':
                                return True
                        else:
                            # end after html
                            return True
                # Other tags: don't decide yet — continue scanning in case doctype/html appears later
                i = j
                # move forward until next '<' to keep linear progress
                while i < n and s[i] != '<':
                    i += 1
                continue

            # Any other visible character before markers: keep scanning (doctype/html may appear later)
            i += 1
            continue

        return False
