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
