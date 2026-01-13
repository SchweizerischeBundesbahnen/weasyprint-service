"""Tests for SvgProcessor utility functions and SVG processing."""

from pathlib import Path

import pytest
from defusedxml import ElementTree as DET

from app.html_parser import HtmlParser
from app.svg_processor import SvgProcessor


@pytest.mark.parametrize(
    "input_html_file,expected_html_file",
    [
        ("tests/test-data/svg-image.html", "tests/test-data/svg-image.embedded.html"),
        ("tests/test-data/svg-image-as-base64.html", "tests/test-data/svg-image-as-base64.embedded.html"),
        ("tests/test-data/svg-image-recursive.html", "tests/test-data/svg-image-recursive.embedded.html"),
    ],
)
def test_replace_inline_svgs_with_img(input_html_file: str, expected_html_file: str):
    """
    Test replace_inline_svgs_with_img with different inputs.

    This test verifies that replace_inline_svgs_with_img correctly converts SVG to base64 encoded IMG tags.
    """
    html_parser = HtmlParser()
    svg_processor = SvgProcessor()

    html = __load_test_html(input_html_file)
    parsed_html = html_parser.parse(html)
    replaced_svg_parsed_html = svg_processor.replace_inline_svgs_with_img(parsed_html)
    replaced_svg_html = html_parser.serialize(replaced_svg_parsed_html)
    expected_html = __load_test_html(expected_html_file)
    assert __equal_ignore_newlines(replaced_svg_html, expected_html)


def __load_test_html(file_path: str) -> str:
    """Load HTML file contents."""
    with Path(file_path).open(encoding="utf-8") as html_file:
        return html_file.read()


def __equal_ignore_newlines(a: str, b: str) -> bool:
    """Compare two strings ignoring all newline characters."""

    def normalize(s: str) -> str:
        return s.replace("\r", "").replace("\n", "")

    return normalize(a) == normalize(b)


# Test parsing SVG dimension values and units
@pytest.mark.parametrize(
    "svg_content,dimension,expected",
    [
        ('<svg width="100px"></svg>', "width", ("100", "px")),  # Basic pixel units
        ('<svg height="50"></svg>', "height", ("50", None)),  # No units specified
        ("<svg></svg>", "width", (None, None)),  # No dimensions
        # Additional unit tests
        ('<svg width="10em"></svg>', "width", ("10", "em")),  # Em units
        ('<svg width="15ex"></svg>', "width", ("15", "ex")),  # Ex units
        ('<svg width="5Q"></svg>', "width", ("5", "Q")),  # Q units
        # Test with XML namespace
        ('<svg xmlns="http://www.w3.org/2000/svg" width="100px"></svg>', "width", ("100", "px")),
    ],
)
def test_parse_svg_dimension(svg_content: str, dimension: str, expected: tuple[str | None, str | None]):
    """Test parsing of SVG dimensions with various inputs.

    Tests extraction of numeric values and units from SVG width/height attributes.
    Verifies handling of different unit types and invalid formats.
    """
    svg = DET.fromstring(svg_content)
    value, unit = SvgProcessor().get_svg_dimension(svg, dimension)
    assert (value, unit) == expected


# Test parsing SVG viewBox values
@pytest.mark.parametrize(
    "svg_content,expected",
    [
        ('<svg viewBox="0 0 800 600"></svg>', (800.0, 600.0)),  # Valid viewBox
        ("<svg></svg>", (None, None)),  # No viewBox
        ('<svg viewBox="0 0 800"></svg>', (None, None)),  # Invalid viewBox (missing height)
        ('<svg viewBox="0 0 800.5 600.5"></svg>', (800.5, 600.5)),  # Decimal values
        ('<svg viewBox="0,0,800,600"></svg>', (800.0, 600.0)),  # Comma-separated tokens
        ('<svg viewBox="0, 0 800, 600"></svg>', (800.0, 600.0)),  # Mixed commas and spaces
        ('<svg viewBox="   0   0    800    600   "></svg>', (800.0, 600.0)),  # Extra whitespace
        ('<svg viewBox="0 0 abc 600"></svg>', (None, None)),  # Non-numeric width
        ('<svg viewBox="0 0 800 def"></svg>', (None, None)),  # Non-numeric height
        ('<svg viewBox="-10 -20 800.25 600.75"></svg>', (800.25, 600.75)),  # Negative mins, float dims
        ('<svg viewBox="0 0 800 600 700"></svg>', (None, None)),  # Too many tokens
    ],
)
def test_parse_viewbox(svg_content: str, expected: tuple[float | None, float | None]):
    """Test parsing of SVG viewBox with various inputs.

    Tests extraction of width and height from viewBox attribute.
    Verifies handling of decimal values and invalid formats.
    """
    content = DET.fromstring(svg_content)
    width, height = SvgProcessor().parse_viewbox(content)
    assert (width, height) == expected


# Test extraction of SVG dimensions in pixels
@pytest.mark.parametrize(
    "svg_content,expected_width,expected_height",
    [
        # Absolute units
        ('<svg height="200px" width="100px"></svg>', 100, 200),
        # ViewBox only
        ('<svg viewBox="0 0 300 150"></svg>', 300, 150),
        # Missing dimensions
        ("<svg></svg>", None, None),
        # Mixed: width with viewBox
        ('<svg width="100px" viewBox="0 0 400 200"></svg>', 100, 200),
        # Mixed: height with viewBox
        ('<svg height="50px" viewBox="0 0 400 200"></svg>', 400, 50),
        # Non-numeric values
        ('<svg width="abc" height="xyz"></svg>', None, None),
    ],
)
def test_extract_svg_dimensions(svg_content: str, expected_width: int | None, expected_height: int | None):
    """Test extraction of SVG dimensions with various inputs.

    Tests conversion of SVG dimensions to absolute pixel values.
    Verifies handling of:
    - Explicit pixel dimensions
    - ViewBox dimensions
    - Mixed explicit/viewBox dimensions
    """
    svg = DET.fromstring(svg_content)
    width, height, updated_svg = SvgProcessor().extract_svg_dimensions_as_px(svg)
    assert width == expected_width
    assert height == expected_height


# Test error handling for relative units without viewBox
@pytest.mark.parametrize(
    "svg_content,expected_error",
    [
        ('<svg width="100vw" height="100vh"></svg>', "vw units require a viewBox to be defined"),
        ('<svg width="100%" height="100%"></svg>', "% units require a viewBox to be defined"),
    ],
)
def test_extract_svg_dimensions_relative_units_error(svg_content: str, expected_error: str):
    """Test extraction of SVG dimensions with relative units without viewBox.

    Verifies that appropriate errors are raised when using relative units (vw, vh, %)
    without a viewBox to reference.
    """
    with pytest.raises(ValueError, match=expected_error):
        SvgProcessor().extract_svg_dimensions_as_px(DET.fromstring(svg_content))


# Test handling of relative units with viewBox
@pytest.mark.parametrize(
    "svg_content,expected_width,expected_height",
    [
        ('<svg width="100vw" height="100vh" viewBox="0 0 800 600"></svg>', 800, 600),
        ('<svg width="50vw" height="50vh" viewBox="0 0 800 600"></svg>', 400, 300),
        ('<svg width="100%" height="100%" viewBox="0 0 800 600"></svg>', 800, 600),
        ('<svg width="50%" height="25%" viewBox="0 0 800 600"></svg>', 400, 150),
        ('<svg width="50%" height="25%" viewBox="0,0,800,600"></svg>', 400, 150),  # Comma-separated viewBox
        ('<svg width="50%" height="25%" viewBox="0, 0 800, 600"></svg>', 400, 150),  # Mixed separators
    ],
)
def test_extract_svg_dimensions_relative_units(svg_content: str, expected_width: int, expected_height: int):
    """Test extraction of SVG dimensions with relative units and viewBox.

    Tests conversion of relative units (vw, vh, %) to absolute pixel values
    when a viewBox is present to provide reference dimensions.
    """
    svg_processor = SvgProcessor()
    width, height, updated_svg = svg_processor.extract_svg_dimensions_as_px(DET.fromstring(svg_content))
    assert width == expected_width
    assert height == expected_height
    updated_svg_content = svg_processor.svg_to_string(updated_svg)
    assert f'width="{width}px"' in updated_svg_content
    assert f'height="{height}px"' in updated_svg_content


@pytest.mark.parametrize(
    "content_type,content_base64,expected_content",
    [
        # Test non-SVG content type
        ("image/png", "123ABC==", None),
        # Test 0x00 in base64 decoded content
        ("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiAA==", None),
        # Test no end tag </svg>
        ("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgi", None),
        # Test malformed SVG content
        ("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+", None),
        # Test valid SVG content
        ("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPjwvc3ZnPg==", '<svg height="200px" width="100px" />'),
        # Test invalid base64 string
        ("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc¨", None),
    ],
)
def test_get_svg_content(content_type: str, content_base64: str, expected_content: str | None):
    """Test SVG content validation and decoding.

    Tests various scenarios for SVG content validation:
    - Non-SVG content types
    - Invalid/corrupted content
    - Missing SVG tags
    - Malformed SVG content
    - Valid SVG content
    - Invalid base64 encoding

    Args:
        content_type: MIME type of the content
        content_base64: Base64 encoded content
        expected_content: Expected decoded SVG content or None if invalid
    """
    svg_processor = SvgProcessor()
    svg = svg_processor.get_svg(content_type, content_base64)
    if expected_content is None:
        assert svg is None
    else:
        assert svg_processor.svg_to_string(svg) == expected_content


def test_to_base64():
    """Test base64 encoding functionality.

    Tests encoding of both bytes and string inputs.
    """
    assert SvgProcessor().to_base64(b"00000") == "MDAwMDA="
    assert SvgProcessor().to_base64("abcde") == "YWJjZGU="


def test_convert_to_px():
    """Test conversion of various units to pixels.

    Tests conversion of different units to pixel values.
    """
    svg_processor = SvgProcessor()
    assert svg_processor.convert_to_px("10", "px") == 10
    assert svg_processor.convert_to_px("1", "mm") == 4  # ceil(96/25.4) = ceil(3.78)
    assert svg_processor.convert_to_px(None, "px") is None
    assert svg_processor.convert_to_px("abc", "px") is None
    assert svg_processor.convert_to_px("100", "vh") is None
    assert svg_processor.convert_to_px("100", "vw") is None
    assert svg_processor.convert_to_px("100", "%") is None
    assert svg_processor.convert_to_px("27.595", "ex") == 221


def test_px_conversion_ratio():
    """Test conversion ratios for different units to pixels.

    Tests conversion ratios for standard CSS units.
    """
    svg_processor = SvgProcessor()
    assert svg_processor.get_px_conversion_ratio("px") == 1
    assert svg_processor.get_px_conversion_ratio("pt") == 4 / 3
    assert svg_processor.get_px_conversion_ratio("in") == 96
    assert svg_processor.get_px_conversion_ratio("cm") == 96 / 2.54
    assert svg_processor.get_px_conversion_ratio("mm") == 96 / 2.54 / 10
    assert svg_processor.get_px_conversion_ratio("pc") == 16
    assert svg_processor.get_px_conversion_ratio("ex") == 8
    assert svg_processor.get_px_conversion_ratio("abcde") == 1
    assert svg_processor.get_px_conversion_ratio(None) == 1


def test_calculate_dimension():
    """Test calculation of SVG dimensions.

    Tests dimension calculations for:
    - Absolute units
    - Relative units with viewBox
    - Error handling
    """
    svg_processor = SvgProcessor()

    # Test absolute units
    assert svg_processor.calculate_dimension("100", "px", None) == 100
    assert svg_processor.calculate_dimension("75", "pt", None) == 100  # 75 * 4/3 = 100

    # Test relative units with viewBox
    assert svg_processor.calculate_dimension("100", "vw", 800.0) == 800
    assert svg_processor.calculate_dimension("50", "vh", 600.0) == 300
    assert svg_processor.calculate_dimension("50", "%", 1000.0) == 500

    # Test relative units without viewBox
    try:
        svg_processor.calculate_dimension("100", "vw", None)
        raise AssertionError("Should raise ValueError")
    except ValueError as e:
        assert "vw units require a viewBox to be defined" in str(e)

    # Test invalid input
    assert svg_processor.calculate_dimension(None, "px", None) is None
    assert svg_processor.calculate_dimension("abc", "px", None) is None


def test_replace_svg_size_attributes():
    """Test replacement of SVG size attributes.

    Tests updating width/height attributes in SVG content.
    """
    svg_processor = SvgProcessor()

    # Test valid SVG
    svg = DET.fromstring('<svg width="100" height="100"></svg>')
    updated_svg = svg_processor.replace_svg_size_attributes(svg, 200, 300)
    result = svg_processor.svg_to_string(updated_svg)
    assert 'width="200px"' in result
    assert 'height="300px"' in result


def test_calculate_special_unit():
    """Test calculation of special CSS units.

    Tests conversion of viewport and percentage units.
    """
    svg_processor = SvgProcessor()

    # Test percentage
    assert svg_processor.calculate_special_unit("50", "%", 1000) == 500

    # Test viewport units
    assert svg_processor.calculate_special_unit("100", "vw", 800) == 800
    assert svg_processor.calculate_special_unit("50", "vh", 600) == 300

    # Test non-special unit (should use convert_to_px)
    assert svg_processor.calculate_special_unit("75", "pt", 1000) == 100  # 75 * 4/3 = 100

    # Test invalid unit (should use default conversion ratio of 1.0)
    assert svg_processor.calculate_special_unit("100", "invalid", 1000) == 100  # 100 * 1.0 = 100

    # Test invalid value
    try:
        svg_processor.calculate_special_unit("abc", "px", 1000)
        raise AssertionError("Should raise ValueError")
    except ValueError as e:
        assert "could not convert string to float: 'abc'" in str(e)


@pytest.mark.parametrize(
    "svg_content, expected_output",
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" height="100" width="100"><circle r="45" cx="50" cy="50" fill="red"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" height="100" width="100"><circle r="45" cx="50" cy="50" fill="red" /></svg>',
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg"><svg x="100" y="100"></svg></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><svg x="100" y="100" /></svg>',
        ),
    ],
)
def test_get_svg_content_with_namespace(svg_content, expected_output):
    """Test SVG content handling with XML namespaces.

    Tests processing of SVG content with XML namespaces and nested elements.
    """
    svg_processor = SvgProcessor()
    svg = svg_processor.get_svg("image/svg+xml", svg_processor.to_base64(svg_content))
    content = svg_processor.svg_to_string(svg)
    assert content == expected_output


@pytest.mark.parametrize(
    "svg_input",
    [
        "<svg width='10' height='10'></svg>",
        "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'></svg>",
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' width='10' height='10'></svg>",
        "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='10' height='10'></svg>",
    ],
)
def test_ensure_mandatory_attributes(svg_input):
    """Test ensuring mandatory SVG attributes."""
    svg_processor = SvgProcessor()

    svg = svg_processor.svg_from_string(svg_input)
    updated_svg = svg_processor.ensure_mandatory_attributes(svg)

    # Ensure it returns the same element instance
    assert updated_svg is svg

    svg_content = svg_processor.svg_to_string(updated_svg)
    assert svg_content.count('xmlns="http://www.w3.org/2000/svg"') == 1


def test_apply_img_dimensions_from_svg():
    """Test that existing width/height styles are replaced when applying SVG dimensions."""
    from bs4 import BeautifulSoup

    svg_processor = SvgProcessor()

    # Create an img tag with existing width/height styles
    html = '<img style="width: 500px; height: 300px; color: red;">'
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("img")

    # Create SVG with known dimensions
    svg = DET.fromstring('<svg width="100" height="200"></svg>')

    svg_processor._apply_img_dimensions_from_svg(node, svg)

    # Check width attribute is set
    assert node.get("width") == "100px"

    # Check style: width replaced, height removed, other styles preserved
    style = node.get("style")
    assert "width: 100px" in style
    assert "height:" not in style.lower()
    assert "color: red" in style
