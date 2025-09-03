import functools
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from defusedxml import ElementTree as DET
from PIL import Image

from app.html_utils import deserialize, serialize
from app.svg_utils import (
    IMAGE_PNG,
    IMAGE_SVG,
    calculate_dimension,
    calculate_special_unit,
    convert_svg_to_png,
    convert_to_px,
    create_chromium_command,
    crop_png,
    extract_svg_dimensions_as_px,
    get_px_conversion_ratio,
    get_svg,
    get_svg_dimension,
    parse_viewbox,
    prepare_temp_files,
    process_svg,
    read_and_cleanup_png,
    replace_svg_size_attributes,
    replace_svg_with_png,
    svg_to_string,
    to_base64, replace_inline_svgs_with_img,
)

test_script_path = "./tests/scripts/test_script.sh"
cropped_test_script_output = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"

EXIT_ONE = "WEASYPRINT_SERVICE_TEST_EXIT_ONE"
WRITE_OUTPUT = "WEASYPRINT_SERVICE_TEST_WRITE_OUTPUT"


def setup_env_variables(f: Callable) -> Callable:
    """Decorator that sets up and tears down environment variables for tests.

    This decorator wraps test functions to ensure they have a clean environment variable state.
    It sets CHROMIUM_EXECUTABLE_PATH, EXIT_ONE, and WRITE_OUTPUT to empty strings before the test,
    runs the test, then resets those variables back to empty strings after the test completes.
    This prevents environment variable state from leaking between tests.

    Args:
        f: The test function to wrap

    Returns:
        A wrapped function that handles environment variable setup/teardown
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            # Set up clean environment before test
            os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
            os.environ[EXIT_ONE] = ""
            os.environ[WRITE_OUTPUT] = ""

            # Run the test
            result = f(*args, **kwargs)
            return result

        finally:
            # Clean up environment after test
            os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
            os.environ[EXIT_ONE] = ""
            os.environ[WRITE_OUTPUT] = ""

    return wrapper


@pytest.mark.parametrize(
    "html,expected_output",
    [
        # Invalid base64 - tests handling of malformed base64 input
        (
            '<img src="data:image/svg+xml;base64,123ABC=="/>"',
            '<img src="data:image/svg+xml;base64,123ABC=="/>"',
        ),
        # Non-SVG image type - tests that non-SVG images are passed through unchanged
        (
            '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="/>',
            '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="/>',
        ),
        # Invalid base64 SVG - tests handling of invalid base64 that claims to be SVG
        (
            '<img src="data:image/svg+xml;base64,invalid==="/>',
            '<img src="data:image/svg+xml;base64,invalid==="/>',
        ),
    ],
)
@setup_env_variables
def test_process_svg_invalid_inputs(html: str, expected_output: str):
    """Test process_svg with various invalid inputs.

    This test verifies that process_svg correctly handles invalid inputs by:
    1. Passing through invalid base64 data unchanged
    2. Not modifying non-SVG image types
    3. Handling invalid base64 that claims to be SVG

    The test uses parametrize to run multiple test cases with different inputs.
    """
    assert serialize(process_svg(deserialize(html))) == expected_output


@setup_env_variables
def test_process_svg_valid_conversion():
    """Test process_svg with valid SVG content.

    This test verifies that process_svg correctly converts SVG images to PNG:
    1. Sets up environment variables needed for Chrome
    2. Tests conversion of a single SVG image
    3. Tests conversion of multiple SVG images in one HTML document
    """
    # Set Chrome executable path and enable test output
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[WRITE_OUTPUT] = "true"

    # Test single SVG conversion
    html = '<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>'
    result = serialize(process_svg(deserialize(html)))
    assert "image/png" in result  # Verify PNG conversion
    assert "base64" in result  # Verify base64 encoding

    # Test inline SVG conversion
    html = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'
    result = serialize(process_svg(deserialize(html)))
    assert "image/png" in result  # Verify PNG conversion
    assert "base64" in result  # Verify base64 encoding

    # Test multiple SVGs in one HTML
    html = """
        <img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>
        <img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>
    """
    result = serialize(process_svg(deserialize(html)))
    assert result.count("image/png") == 2  # Verify both SVGs converted


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

    This test verifies that replace_inline_svgs_with_img correctly converts SVG to base64 encoded IMG tags:
    """
    html = __load_test_html(input_html_file)
    parsed_html = deserialize(html)
    replaced_svg_parsed_html = replace_inline_svgs_with_img(parsed_html)
    replaced_svg_html = serialize(replaced_svg_parsed_html)
    expected_html = __load_test_html(expected_html_file)
    assert __equal_ignore_newlines(replaced_svg_html, expected_html)


def __load_test_html(file_path: str) -> str:
    """
    Load HTML file contents.
    """
    with Path(file_path).open(encoding="utf-8") as html_file:
        html = html_file.read()
        return html


def __equal_ignore_newlines(a: str, b: str) -> bool:
    """
    Compare two strings ignoring all newline characters.
    """
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
@setup_env_variables
def test_parse_svg_dimension(svg_content: str, dimension: str, expected: tuple[str | None, str | None]):
    """Test parsing of SVG dimensions with various inputs.

    Tests extraction of numeric values and units from SVG width/height attributes.
    Verifies handling of different unit types and invalid formats.
    """
    svg = DET.fromstring(svg_content)
    value, unit = get_svg_dimension(svg, dimension)
    assert (value, unit) == expected


# Test parsing SVG viewBox values
@pytest.mark.parametrize(
    "svg_content,expected",
    [
        ('<svg viewBox="0 0 800 600"></svg>', (800.0, 600.0)),  # Valid viewBox
        ("<svg></svg>", (None, None)),  # No viewBox
        ('<svg viewBox="0 0 800"></svg>', (None, None)),  # Invalid viewBox (missing height)
        ('<svg viewBox="0 0 800.5 600.5"></svg>', (800.5, 600.5)),  # Decimal values
    ],
)
@setup_env_variables
def test_parse_viewbox(svg_content: str, expected: tuple[float | None, float | None]):
    """Test parsing of SVG viewBox with various inputs.

    Tests extraction of width and height from viewBox attribute.
    Verifies handling of decimal values and invalid formats.
    """
    content = DET.fromstring(svg_content)
    width, height = parse_viewbox(content)
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
@setup_env_variables
def test_extract_svg_dimensions(svg_content: str, expected_width: int | None, expected_height: int | None):
    """Test extraction of SVG dimensions with various inputs.

    Tests conversion of SVG dimensions to absolute pixel values.
    Verifies handling of:
    - Explicit pixel dimensions
    - ViewBox dimensions
    - Mixed explicit/viewBox dimensions
    """
    svg = DET.fromstring(svg_content)
    width, height, updated_svg = extract_svg_dimensions_as_px(svg)
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
@setup_env_variables
def test_extract_svg_dimensions_relative_units_error(svg_content: str, expected_error: str):
    """Test extraction of SVG dimensions with relative units without viewBox.

    Verifies that appropriate errors are raised when using relative units (vw, vh, %)
    without a viewBox to reference.
    """
    with pytest.raises(ValueError, match=expected_error):
        extract_svg_dimensions_as_px(DET.fromstring(svg_content))


# Test handling of relative units with viewBox
@pytest.mark.parametrize(
    "svg_content,expected_width,expected_height",
    [
        ('<svg width="100vw" height="100vh" viewBox="0 0 800 600"></svg>', 800, 600),
        ('<svg width="50vw" height="50vh" viewBox="0 0 800 600"></svg>', 400, 300),
        ('<svg width="100%" height="100%" viewBox="0 0 800 600"></svg>', 800, 600),
        ('<svg width="50%" height="25%" viewBox="0 0 800 600"></svg>', 400, 150),
    ],
)
@setup_env_variables
def test_extract_svg_dimensions_relative_units(svg_content: str, expected_width: int, expected_height: int):
    """Test extraction of SVG dimensions with relative units and viewBox.

    Tests conversion of relative units (vw, vh, %) to absolute pixel values
    when a viewBox is present to provide reference dimensions.
    """
    width, height, updated_svg = extract_svg_dimensions_as_px(DET.fromstring(svg_content))
    assert width == expected_width
    assert height == expected_height
    updated_svg_content = svg_to_string(updated_svg)
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
@setup_env_variables
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
    svg = get_svg(content_type, content_base64)
    if expected_content is None:
        assert svg is None
    else:
        assert svg_to_string(svg) == expected_content


@setup_env_variables
def test_replace_svg_with_png():
    """Test SVG to PNG conversion functionality.

    Tests various scenarios for SVG to PNG conversion:
    - Missing Chrome executable
    - Chrome execution failures
    - Successful conversion
    """
    # Chrome executable not set, return same content
    svg = DET.fromstring(r'<svg height="200px" width="100px"></svg>')
    mime, content = replace_svg_with_png(svg)
    assert mime == IMAGE_SVG, content == svg

    # Chrome executable test script returns empty, return same content
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    svg = DET.fromstring(r'<svg height="200px" width="100px"></svg>')
    mime, content = replace_svg_with_png(svg)
    assert mime == IMAGE_SVG, content == svg

    # Valid input with chrome executable test script set correctly, return script output
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[WRITE_OUTPUT] = "true"
    svg = DET.fromstring(r'<svg height="200px" width="100px"></svg>')
    mime, content = replace_svg_with_png(svg)
    assert mime == IMAGE_PNG
    assert content == cropped_test_script_output


@setup_env_variables
def test_prepare_temp_files():
    """Test preparation of temporary files for SVG/PNG conversion.

    Tests creation of temporary files for SVG input and PNG output.
    """
    # Test with no content
    svg_filepath, png_filepath = prepare_temp_files(None)
    assert svg_filepath is None and png_filepath is None

    # Test with content
    svg_filepath, png_filepath = prepare_temp_files("test")
    assert svg_filepath is not None and svg_filepath != ""
    assert png_filepath is not None and png_filepath != ""


@setup_env_variables
def test_convert_svg_to_png():
    """Test SVG to PNG conversion process.

    Tests various scenarios in the conversion process:
    - Missing Chrome executable
    - Chrome execution failures
    - Invalid Chrome path
    - Successful conversion
    """
    # Test missing Chrome executable
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res

    # Test Chrome execution failure
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[EXIT_ONE] = "true"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res

    # Test invalid Chrome path
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "definitely_not_a_valid_command"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res

    # Test successful conversion
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[EXIT_ONE] = ""
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert res


@setup_env_variables
def test_read_and_cleanup_png():
    """Test reading and cleanup of PNG files.

    Tests reading PNG file content and proper cleanup afterwards.
    """
    # Create test file
    png_file = Path("./test.png")
    png_file.touch()
    png_file.write_bytes(b"test")

    # Test reading content
    assert read_and_cleanup_png(png_file) == b"test"

    # Test file cleanup
    assert read_and_cleanup_png(png_file) is None


@setup_env_variables
def test_create_chromium_command():
    """Test creation of Chrome command for SVG conversion.

    Tests command line argument construction for Chrome headless mode.
    """
    # Test without Chrome executable
    assert create_chromium_command(1, 1, Path("/"), Path("/")) is None

    # Test with Chrome executable
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "/"
    assert create_chromium_command(1, 1, Path("/"), Path("/")) == [
        "/",
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--default-background-color=00000000",
        "--hide-scrollbars",
        "--force-device-scale-factor=1.0",
        "--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb",
        "--screenshot=/",
        f"--window-size={1},{1}",
        "/",
    ]


@setup_env_variables
def test_to_base64():
    """Test base64 encoding functionality.

    Tests encoding of both bytes and string inputs.
    """
    assert to_base64(b"00000") == "MDAwMDA="
    assert to_base64("abcde") == "YWJjZGU="


@setup_env_variables
def test_convert_to_px():
    """Test conversion of various units to pixels.

    Tests conversion of different units to pixel values.
    """
    assert convert_to_px("10", "px") == 10
    assert convert_to_px("1", "mm") == 378
    assert convert_to_px(None, "px") is None
    assert convert_to_px("abc", "px") is None
    assert convert_to_px("100", "vh") is None
    assert convert_to_px("100", "vw") is None
    assert convert_to_px("100", "%") is None
    assert convert_to_px("27.595", "ex") == 221


@setup_env_variables
def test_px_conversion_ratio():
    """Test conversion ratios for different units to pixels.

    Tests conversion ratios for standard CSS units.
    """
    assert get_px_conversion_ratio("px") == 1
    assert get_px_conversion_ratio("pt") == 4 / 3
    assert get_px_conversion_ratio("in") == 96
    assert get_px_conversion_ratio("cm") == 96 / 2.54
    assert get_px_conversion_ratio("mm") == 96 / 2.54 * 10
    assert get_px_conversion_ratio("pc") == 16
    assert get_px_conversion_ratio("ex") == 8
    assert get_px_conversion_ratio("abcde") == 1
    assert get_px_conversion_ratio(None) == 1


@setup_env_variables
def test_crop_png():
    """Test PNG image cropping functionality.

    Tests various scenarios for PNG cropping:
    - Successful crop
    - Crop beyond image height
    - Invalid file handling
    """
    # Create test PNG
    temp_file = Path("test_crop.png")
    try:
        # Create a small test PNG
        with Image.new("RGBA", (10, 20)) as img:
            img.save(temp_file)

        # Test successful crop
        assert crop_png(temp_file, 5) is True

        # Verify dimensions after crop
        with Image.open(temp_file) as img:
            assert img.size == (10, 15)

        # Test crop more than height
        assert crop_png(temp_file, 20) is False

        # Test invalid file
        assert crop_png(Path("nonexistent.png"), 5) is False
    finally:
        if temp_file.exists():
            temp_file.unlink()


@setup_env_variables
def test_calculate_dimension():
    """Test calculation of SVG dimensions.

    Tests dimension calculations for:
    - Absolute units
    - Relative units with viewBox
    - Error handling
    """
    # Test absolute units
    assert calculate_dimension("100", "px", None) == 100
    assert calculate_dimension("75", "pt", None) == 100  # 75 * 4/3 = 100

    # Test relative units with viewBox
    assert calculate_dimension("100", "vw", 800.0) == 800
    assert calculate_dimension("50", "vh", 600.0) == 300
    assert calculate_dimension("50", "%", 1000.0) == 500

    # Test relative units without viewBox
    try:
        calculate_dimension("100", "vw", None)
        raise AssertionError("Should raise ValueError")
    except ValueError as e:
        assert "vw units require a viewBox to be defined" in str(e)

    # Test invalid input
    assert calculate_dimension(None, "px", None) is None
    assert calculate_dimension("abc", "px", None) is None


@setup_env_variables
def test_replace_svg_size_attributes():
    """Test replacement of SVG size attributes.

    Tests updating width/height attributes in SVG content.
    """
    # Test valid SVG
    svg = DET.fromstring('<svg width="100" height="100"></svg>')
    updated_svg = replace_svg_size_attributes(svg, 200, 300)
    result = svg_to_string(updated_svg)
    assert 'width="200px"' in result
    assert 'height="300px"' in result


@setup_env_variables
def test_calculate_special_unit():
    """Test calculation of special CSS units.

    Tests conversion of viewport and percentage units.
    """
    # Test percentage
    assert calculate_special_unit("50", "%", 1000) == 500

    # Test viewport units
    assert calculate_special_unit("100", "vw", 800) == 800
    assert calculate_special_unit("50", "vh", 600) == 300

    # Test non-special unit (should use convert_to_px)
    assert calculate_special_unit("75", "pt", 1000) == 100  # 75 * 4/3 = 100

    # Test invalid unit (should use default conversion ratio of 1.0)
    assert calculate_special_unit("100", "invalid", 1000) == 100  # 100 * 1.0 = 100

    # Test invalid value
    try:
        calculate_special_unit("abc", "px", 1000)
        raise AssertionError("Should raise ValueError")
    except ValueError as e:
        assert "could not convert string to float: 'abc'" in str(e)


@setup_env_variables
def test_process_svg_comprehensive():
    """Test comprehensive SVG processing functionality.

    Tests end-to-end SVG processing including:
    - Non-SVG image handling
    - Invalid input handling
    - Single SVG conversion
    - Multiple SVG conversion
    """
    # Test non-SVG image
    html = '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="/>'
    assert serialize(process_svg(deserialize(html))) == html

    # Test invalid base64
    html = '<img src="data:image/svg+xml;base64,invalid==="/>'
    assert serialize(process_svg(deserialize(html))) == html

    # Test valid conversion
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[WRITE_OUTPUT] = "true"
    html = '<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>'
    result = serialize(process_svg(deserialize(html)))
    assert "image/png" in result
    assert "base64" in result

    # Test multiple SVGs
    html = """
        <img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>
        <img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFweCIgd2lkdGg9IjFweCIgdmlld0JveD0iMCAwIDEgMSI+PC9zdmc+"/>
    """
    result = serialize(process_svg(deserialize(html)))
    assert result.count("image/png") == 2


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
@setup_env_variables
def test_get_svg_content_with_namespace(svg_content, expected_output):
    """Test SVG content handling with XML namespaces.

    Tests processing of SVG content with XML namespaces and nested elements.
    """
    svg = get_svg("image/svg+xml", to_base64(svg_content))
    content = svg_to_string(svg)
    assert content == expected_output
