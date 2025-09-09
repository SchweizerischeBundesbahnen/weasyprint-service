
import pytest

from app.html_parser import HtmlParser


@pytest.mark.parametrize(
    "html,expected_output",
    [
        (
                # HTML fragment without html/body
                '<div><p>Hello</p></div>',
                '<div><p>Hello</p></div>',
        ),
        (
                # full HTML document
                '<!DOCTYPE html>'
                '<html>'
                '<head><title>T</title></head>'
                '<body><p>Hi</p></body>'
                '</html>',
                '<!DOCTYPE html>'
                '<html>'
                '<head><title>T</title></head>'
                '<body><p>Hi</p></body>'
                '</html>',
        ),
        (
                # full HTML document
                '<html>'
                '<head><title>T</title></head>'
                '<body><p>Hi</p></body>'
                '</html>',
                '<html>'
                '<head><title>T</title></head>'
                '<body><p>Hi</p></body>'
                '</html>',
        ),
        (
                # full HTML document
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<!DOCTYPE html>"
                "<html>"
                "<head><title>X</title></head>"
                "<body><p>Y</p></body>"
                "</html>",
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<!DOCTYPE html>"
                "<html>"
                "<head><title>X</title></head>"
                "<body><p>Y</p></body>"
                "</html>",
        ),
        (
                # SVG with viewBox and foreignObject (register is saved as is)
                '<svg width="100" height="100" viewBox="0 0 100 100">'
                '<foreignObject width="100%" height="100%">'
                '<div xmlns="http://www.w3.org/1999/xhtml">Test</div>'
                '</foreignObject>'
                '</svg>',
                '<svg height="100" viewBox="0 0 100 100" width="100">'
                '<foreignObject height="100%" width="100%">'
                '<div xmlns="http://www.w3.org/1999/xhtml">Test</div>'
                '</foreignObject>'
                '</svg>',
        ),
    ],
)
def test_process_html_inputs(html: str, expected_output: str):
    html_parser = HtmlParser()
    html = html_parser.parse(html)
    output = html_parser.serialize(html)
    assert __strip_string(output) == __strip_string(expected_output)


def __strip_string(string: str) -> str:
    return string.replace("\r", "").replace("\n", "")


@pytest.mark.parametrize(
    "html, expected",
    [
        # fragments → False
        ("<div>fragment</div>", False),
        ("\n  <!-- just a comment -->\n<div>x</div>", False),
        ("text before <div>hi</div>", False),
        ("<?pi something?><div>x</div>", False),
        ("<!--?xml version='1.0' encoding='UTF-8'?-->\n<div>fragment</div>", False),

        # full documents → True
        ("<!DOCTYPE html><html><head></head><body></body></html>", True),
        ("\n\n<!doctype HTML>\n<html><body></body></html>", True),
        ("<html lang='en'><head></head><body></body></html>", True),
        ("\ufeff<!-- a --><!-- b -->\n<!DoCtYpE hTmL>\n<html></html>", True),

        # allowed comments/spaces/BOM before document
        ("\ufeff   <!-- header -->   <!DOCTYPE html>\n<html></html>", True),
        ("<!-- comment --><!-- another -->   <html></html>", True),

        # XML declaration and XHTML
        ("<?xml version='1.0' encoding='UTF-8'?><html xmlns='http://www.w3.org/1999/xhtml'></html>", True),
        ("<!--?xml version='1.0' encoding='UTF-8'?-->\n<!DOCTYPE html>\n<html></html>", True),
        ("<!--  ?xml version='1.0' encoding='UTF-8'?  -->\n<!DOCTYPE html>\n<html></html>", True),

        # other cases
        ("<?xml version='1.0' encoding='UTF-8'?>\n<div style='break-after:page'>page to be removed</div>", False),
        ("   <!-- multi-line \n comment -->   <HTML></HTML>", True),
        ("\t\r\n<!-- c --><!-- d --><?xml version='1.0'?><html></html>", True),
        ("<!--not start-->  <?pi?>  <!--x-->\n<div>only fragment</div>", False),
        ("<div style='break-after:page'>page to be removed</div><?xml version='1.0' encoding='UTF-8'?><!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.0 Strict//EN' 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd'><html lang='en' xml:lang='en' xmlns='http://www.w3.org/1999/xhtml'></html>", True),
        ("<!-- <html></html> --><div style='break-after:page'>page to be removed</div><?xml version='1.0' encoding='UTF-8'?>", False),
    ],
)
def test_is_full_document(html, expected):
    assert HtmlParser()._is_full_document(html) is expected
