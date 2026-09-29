"""Tests for SvgProcessor utility functions and SVG processing."""

import base64
from pathlib import Path

import pytest

# Defusedxml exposes ElementTree as a module.
from defusedxml import ElementTree as det  # noqa: N813

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
    svg = det.fromstring(svg_content)
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
    content = det.fromstring(svg_content)
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
    svg = det.fromstring(svg_content)
    width, height, _updated_svg = SvgProcessor().extract_svg_dimensions_as_px(svg)
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
        SvgProcessor().extract_svg_dimensions_as_px(det.fromstring(svg_content))


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
    width, height, updated_svg = svg_processor.extract_svg_dimensions_as_px(det.fromstring(svg_content))
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
    svg = det.fromstring('<svg width="100" height="100"></svg>')
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


@pytest.mark.parametrize(
    "html,expected_width,expected_style",
    [
        # Nothing sizes the image, so it gets the width of the SVG: the PNG is rasterized at the size
        # of the SVG times the scale factor and would otherwise come out that many times too large.
        ('<img style="color: red;">', "100px", "color: red; width: 100px"),
        ('<img style="max-width: 650px;">', "100px", "max-width: 650px; width: 100px"),
        ("<img>", "100px", "width: 100px"),
    ],
)
def test_apply_img_dimensions_from_svg_where_the_document_gives_none(html, expected_width, expected_style):
    """The width of the SVG lands on an image the document does not size."""
    from bs4 import BeautifulSoup

    node = BeautifulSoup(html, "html.parser").find("img")

    SvgProcessor()._apply_img_dimensions_from_svg(node, det.fromstring('<svg width="100" height="200"></svg>'))

    assert node.get("width") == expected_width
    assert node.get("style") == expected_style


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "style,expected_render_size",
    [
        # The PNG is rasterized at the size the document draws the image at, so the scale factor keeps it
        # sharp there rather than at the size of the SVG; #375.
        ('style="width: 400px; height: 200px;"', (400, 200)),
        ('style="width: 400px;"', (400, 200)),  # the height follows the ratio of the SVG
        ('style="height: 50px;"', (100, 50)),
        ('style="width: 400px !important; width: 100px;"', (400, 200)),  # the cascade of a style attribute
        # Nothing the document draws the image at, so the SVG says the size, as it always did
        ('style="max-width: 650px;"', None),
        ('style="width: 50%;"', None),  # a percentage has no meaning without a layout
        ('style="width: 50%; height: 50px;"', None),  # and the other half would be a guess
        ('style="width: infpx;"', None),  # a length which is no length
        ("", None),
    ],
)
async def test_svg_is_rasterized_at_the_size_the_document_draws_it(style, expected_render_size, mocker):
    """The size handed to the conversion is the size the image is drawn at."""
    from bs4 import BeautifulSoup

    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"></svg>'
    src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    soup = BeautifulSoup(f'<img src="{src}" {style}>', "html.parser")

    processor = SvgProcessor()
    convert = mocker.patch.object(processor, "replace_svg_with_png", return_value=("image/png", b"png bytes"))

    await processor.replace_img_base64(soup)

    assert convert.call_args.args[1] == expected_render_size


@pytest.mark.parametrize(
    "html,expected_width,expected_style",
    [
        # `auto` and the keywords beside it state no size, so the width of the SVG still lands on the image
        ('<img style="width: auto;">', "100px", "width: auto; width: 100px"),
        ('<img style="width: initial;">', "100px", "width: initial; width: 100px"),
        ('<img style="width: unset;">', "100px", "width: unset; width: 100px"),
        ('<img style="width: fit-content; max-width: 650px;">', "100px", "width: fit-content; max-width: 650px; width: 100px"),
    ],
)
def test_apply_img_dimensions_where_the_style_states_no_size(html, expected_width, expected_style):
    """A keyword is not a size: without one the PNG would come out as many times too large as the scale factor."""
    from bs4 import BeautifulSoup

    node = BeautifulSoup(html, "html.parser").find("img")

    SvgProcessor()._apply_img_dimensions_from_svg(node, det.fromstring('<svg width="100" height="200"></svg>'))

    assert node.get("width") == expected_width
    assert node.get("style") == expected_style


@pytest.mark.parametrize(
    "html",
    [
        '<img style="width: 500px; height: 300px; color: red;">',
        '<img style="width : 100px;">',  # a space before the colon is valid CSS
        '<img style="WIDTH: 100PX;">',
        '<img style="width: 50%;">',
        '<img style="height: 300px;">',
        '<img style="max-width: 650px; width: 200%;">',
        '<img style="width: inherit;">',  # the size of the parent, which a width written here would win over
    ],
)
def test_apply_img_dimensions_keeps_the_size_the_document_gives(html):
    """A width or a height of the document is the size its author asked for; #375."""
    from bs4 import BeautifulSoup

    node = BeautifulSoup(html, "html.parser").find("img")
    before = dict(node.attrs)

    SvgProcessor()._apply_img_dimensions_from_svg(node, det.fromstring('<svg width="100" height="200"></svg>'))

    assert dict(node.attrs) == before


def test_apply_img_dimensions_survives_a_broken_svg(mocker):
    """Applying dimensions is best effort: a failure leaves the node untouched."""
    from bs4 import BeautifulSoup

    processor = SvgProcessor()
    node = BeautifulSoup('<img src="x.png">', "html.parser").img
    mocker.patch.object(processor, "extract_svg_dimensions_as_px", side_effect=RuntimeError("no dims"))

    processor._apply_img_dimensions_from_svg(node, det.fromstring("<svg/>"))

    assert "style" not in node.attrs


# The paths a document takes which nothing else in this file reaches: #375 asks for all of them.


@pytest.mark.parametrize(
    "svg,expected",
    [
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 5"/>', {"src"}),
        ('<svg xmlns="http://www.w3.org/2000/svg" width="10"/>', {"src", "width"}),
        ('<svg xmlns="http://www.w3.org/2000/svg" height="5"/>', {"src", "height"}),
    ],
)
def test_replace_svg_with_img_carries_the_dimensions_the_svg_has(svg, expected):
    """An inline <svg> becomes an <img> with the width and the height it states, and no others."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(f"<div>{svg}</div>", "html.parser")

    SvgProcessor().replace_inline_svgs_with_img(soup)

    assert set(soup.find("img").attrs) == expected


@pytest.mark.asyncio
async def test_replace_img_base64_passes_over_what_is_not_an_svg_data_url(mocker):
    """An image which is not a base64 data URL, and one whose payload is no SVG, are left as they are."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<img src="picture.png"><img src="data:image/png;base64,Zm9v">', "html.parser")
    processor = SvgProcessor()
    convert = mocker.patch.object(processor, "replace_svg_with_png")

    await processor.replace_img_base64(soup)

    convert.assert_not_called()
    assert [img["src"] for img in soup.find_all("img")] == ["picture.png", "data:image/png;base64,Zm9v"]


@pytest.mark.asyncio
async def test_replace_img_base64_leaves_an_svg_the_conversion_gives_back(mocker):
    """Where the conversion returns the SVG it was given, the image keeps the source it had."""
    from bs4 import BeautifulSoup

    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>'
    src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    soup = BeautifulSoup(f'<img src="{src}">', "html.parser")
    processor = SvgProcessor()
    mocker.patch.object(processor, "replace_svg_with_png", return_value=("image/svg+xml", svg))

    await processor.replace_img_base64(soup)

    assert soup.find("img")["src"] == src
    assert "style" not in soup.find("img").attrs


def test_apply_img_dimensions_leaves_an_svg_without_a_width_alone():
    """Nothing to apply where the SVG states no width, and no style is written for the sake of it."""
    from bs4 import BeautifulSoup

    node = BeautifulSoup("<img>", "html.parser").img

    SvgProcessor()._apply_img_dimensions_from_svg(node, det.fromstring("<svg/>"))

    assert "width" not in node.attrs
    assert "style" not in node.attrs


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"/>',  # no viewBox to scale into
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 0"/>',  # no size of its own
    ],
)
def test_requested_size_is_none_where_the_svg_cannot_be_scaled(svg):
    """The size of the document is kept, but the PNG is rasterized as it always was."""
    from bs4 import BeautifulSoup

    node = BeautifulSoup('<img style="width: 400px;">', "html.parser").img

    assert SvgProcessor()._requested_size_px(node, det.fromstring(svg)) is None


@pytest.mark.parametrize("value,expected", [("abcpx", None), ("10", None), (None, None), ("10px", 10)])
def test_px_value(value, expected):
    """A length in px, and nothing else."""
    assert SvgProcessor()._px_value(value) == expected


@pytest.mark.parametrize(
    "src",
    [
        "picture.png",  # no data URL at all
        "data:image/svg+xml,<svg/>",  # a data URL which is not base64
        "not-data:image/svg+xml;base64,Zm9v",  # base64, but no data URL
    ],
)
def test_parse_data_url_base64_takes_only_a_base64_data_url(src):
    assert SvgProcessor()._parse_data_url_base64(src) is None


@pytest.mark.asyncio
async def test_replace_svg_with_png_keeps_an_svg_without_dimensions():
    """Nothing to rasterize where the SVG says no size."""
    processor = SvgProcessor()

    content_type, content = await processor.replace_svg_with_png(det.fromstring('<svg xmlns="http://www.w3.org/2000/svg"/>'))

    assert content_type == processor.IMAGE_SVG
    assert "<svg" in content


@pytest.mark.asyncio
async def test_replace_svg_with_png_rasterizes_at_the_size_it_is_given(mocker):
    """The size handed in replaces the one of the SVG, which its viewBox scales the drawing into."""
    processor = SvgProcessor()
    processor.chromium_manager = mocker.Mock()
    processor.chromium_manager.convert_svg_to_png = mocker.AsyncMock(return_value=b"png bytes")
    svg = det.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"/>')

    content_type, content = await processor.replace_svg_with_png(svg, (400, 200))

    assert (content_type, content) == (processor.IMAGE_PNG, b"png bytes")
    svg_content, width, height, _ = processor.chromium_manager.convert_svg_to_png.call_args.args
    assert (width, height) == (400, 200)
    assert 'width="400px"' in svg_content


@pytest.mark.asyncio
async def test_replace_svg_with_png_keeps_the_svg_where_the_conversion_fails(mocker):
    """A conversion which raises leaves the image as the SVG it was."""
    processor = SvgProcessor()
    processor.chromium_manager = mocker.Mock()
    processor.chromium_manager.convert_svg_to_png = mocker.AsyncMock(side_effect=RuntimeError("no chromium"))

    content_type, content = await processor.replace_svg_with_png(det.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>'))

    assert content_type == processor.IMAGE_SVG
    assert "<svg" in content


def test_calculate_special_unit_refuses_a_value_which_is_no_number():
    with pytest.raises(ValueError, match="could not convert string to float"):
        SvgProcessor().calculate_special_unit("ten", "pt", 100)


@pytest.mark.parametrize("value,default,expected", [("abc", 1.5, 1.5), (None, 2.5, 2.5), ("3", 1.0, 3.0)])
def test_parse_float(value, default, expected):
    assert SvgProcessor()._parse_float(value, default) == expected


@pytest.mark.asyncio
async def test_replace_img_base64_passes_over_what_is_no_tag(mocker):
    """The search gives tags, and anything else is passed over rather than read as one."""
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup("<img>", "html.parser")
    mocker.patch.object(soup, "find_all", return_value=[NavigableString("text")])
    processor = SvgProcessor()
    convert = mocker.patch.object(processor, "replace_svg_with_png")

    await processor.replace_img_base64(soup)

    convert.assert_not_called()


@pytest.mark.asyncio
async def test_replace_svg_with_png_keeps_the_svg_without_a_browser_to_rasterize_it():
    """Nothing converts an SVG where no browser was started, so the image stays the SVG it was."""
    processor = SvgProcessor()
    processor.chromium_manager = None

    content_type, content = await processor.replace_svg_with_png(det.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>'))

    assert content_type == processor.IMAGE_SVG
    assert "<svg" in content
