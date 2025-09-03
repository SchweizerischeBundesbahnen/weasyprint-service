from bs4 import BeautifulSoup, Comment


def serialize(html: BeautifulSoup) -> str:
    """
    Serialize BeautifulSoup back to string.
    - If it was a full document: return as-is.
    - If it was a fragment: return only the inner body contents.
    """
    xml_decl: str = getattr(html, "_xml_decl", "")

    if getattr(html, "_was_full_document", False):
        result = html.decode(formatter="minimal")
        if xml_decl:
            result = xml_decl + result
        return result
    else:
        body = html.body
        if body is None:
            return html.decode(formatter="minimal")
        return body.decode_contents(formatter="minimal")


def deserialize(string: str) -> BeautifulSoup:
    """
    Parse HTML string into BeautifulSoup and mark whether it was a full document.
    Stores the original XML declaration in the BeautifulSoup object.
    """
    xml_decl = _extract_xml_decl(string)
    is_full_document = _is_full_document(string)

    html = BeautifulSoup(string, "html5lib")

    html = _clear_leading_comment(html)

    html._was_full_document = is_full_document  # type: ignore[attr-defined]
    html._xml_decl = xml_decl  # type: ignore[attr-defined]

    return html


def _clear_leading_comment(html: BeautifulSoup) -> BeautifulSoup:
    """
    Removes comment like <!--?xml ... ?-->
    """
    if html.contents and isinstance(html.contents[0], Comment) and str(html.contents[0]).strip().startswith("?xml"):
        html.contents[0].extract()
    return html


def _extract_xml_decl(s: str) -> str:
    s = s.lstrip()
    if s.startswith("<?xml"):
        end = s.find("?>")
        if end != -1:
            return s[: end + 2]
    return ""


def _is_full_document(s: str) -> bool:
    s = s.lstrip().lower()
    return s.startswith("<!doctype") or s.startswith("<html") or s.startswith("<?xml")
