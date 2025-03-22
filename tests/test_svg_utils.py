import base64
import os
from collections.abc import Callable
from pathlib import Path

from app.svg_utils import (
    IMAGE_PNG,
    IMAGE_SVG,
    convert_svg_to_png,
    convert_to_px,
    create_chromium_command,
    extract_svg_dimensions_as_px,
    get_px_conversion_ratio,
    get_svg_content,
    prepare_temp_files,
    process_svg,
    read_and_cleanup_png,
    replace_svg_with_png,
    to_base64,
)

test_script_path = "./tests/scripts/test_script.sh"
cropped_test_script_output = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"

EXIT_ONE = "WEASYPRINT_SERVICE_TEST_EXIT_ONE"
WRITE_OUTPUT = "WEASYPRINT_SERVICE_TEST_WRITE_OUTPUT"


def setup_env_variables(f: Callable[[], None]) -> Callable[[], None]:
    def inner():
        os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
        os.environ[EXIT_ONE] = ""
        os.environ[WRITE_OUTPUT] = ""
        f()
        os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
        os.environ[EXIT_ONE] = ""
        os.environ[WRITE_OUTPUT] = ""

    return inner


@setup_env_variables
def test_process_svg():
    # Invalid utf-8 string 123ABC==, return same content
    html = '<img src="data:image/svg+xml;base64,123ABC=="/>"'
    content = process_svg(html)
    assert content == html

    # image/png is not extracted, return the same value
    html = '<img src="data:image/png;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"'
    content = process_svg(html)
    assert content == html

    # svg image type extracted and converted using test script
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[WRITE_OUTPUT] = "true"
    html = '<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"'
    expected_output = f'<img src="data:image/png;base64,{base64.b64encode(cropped_test_script_output).decode("utf-8")}"/>"'
    content = process_svg(html)
    assert content == expected_output


@setup_env_variables
def test_get_svg_content():
    # image/png not svg image type, return None
    content = get_svg_content("image/png", "123ABC==")
    assert content is None

    # 0x00 in base64 decoded content (b'<svg height="200px" width="100px"\x00'), return None
    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiAA==")
    assert content is None

    # No end tag </svg> (b'<svg height="200px" width="100px"'), return None
    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgi")
    assert content is None

    # Valid input (b'<svg height="200px" width="100px"</svg>'), return decoded svg content
    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+")
    assert content == r'<svg height="200px" width="100px"</svg>'

    # Invalid base64 string, return None
    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc¨")
    assert content is None


@setup_env_variables
def test_replace_svg_with_png():
    # Invalid svg tag attributes, return same content
    svg_content = r'<svg height=200px" width "100px'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    # Chrome executable not set, return same content
    svg_content = r'<svg height="200px" width="100px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    # Chrome executable test script returns empty, return same content
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    svg_content = r'<svg height="200px" width="100px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    # Valid input with chrome executable test script set correctly, return script output
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[WRITE_OUTPUT] = "true"
    svg_content = r'<svg height="1px" width="1px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_PNG
    assert content == cropped_test_script_output


@setup_env_variables
def test_extract_svg_dimensions_as_px():
    # Valid width and height with absolute units
    svg_content = r'<svg height="200px" width="100px"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 100 and height == 200
    assert 'width="100px"' in updated_svg
    assert 'height="200px"' in updated_svg

    # Invalid width and height attribute formatting → None
    svg_content = r'<svg height=200px" width "100px></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width is None and height is None
    assert updated_svg == svg_content

    # Valid viewBox fallback when width and height are missing
    svg_content = r'<svg viewBox="0 0 300 150"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 300 and height == 150
    assert 'width="300px"' in updated_svg
    assert 'height="150px"' in updated_svg

    # viewBox with incorrect format → None
    svg_content = r'<svg viewBox="0 0 300"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width is None and height is None
    assert updated_svg == svg_content

    # Missing everything → None, None
    svg_content = r"<svg></svg>"
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width is None and height is None
    assert updated_svg == svg_content

    # Partial attributes: width only, no height, but with valid viewBox
    svg_content = r'<svg width="100px" viewBox="0 0 400 200"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 100 and height == 200
    assert 'width="100px"' in updated_svg
    assert 'height="200px"' in updated_svg

    # Partial attributes: height only, no width, but with valid viewBox
    svg_content = r'<svg height="50px" viewBox="0 0 400 200"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 400 and height == 50
    assert 'width="400px"' in updated_svg
    assert 'height="50px"' in updated_svg

    # Non-numeric width and height → None
    svg_content = r'<svg width="abc" height="xyz"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width is None and height is None
    assert updated_svg == svg_content


@setup_env_variables
def test_extract_svg_dimensions_as_px_relative():
    # width/height in vw/vh without viewBox → raise ValueError
    svg_content = r'<svg width="100vw" height="100vh"></svg>'
    try:
        extract_svg_dimensions_as_px(svg_content)
        raise AssertionError("Expected ValueError due to missing viewBox for vw/vh units")
    except ValueError as e:
        assert "vw units require a viewBox to be defined" in str(e)

    # width/height in % without viewBox → raise ValueError
    svg_content = r'<svg width="100%" height="100%"></svg>'
    try:
        extract_svg_dimensions_as_px(svg_content)
        raise AssertionError("Expected ValueError due to missing viewBox for vw/vh units")
    except ValueError as e:
        assert "% units require a viewBox to be defined" in str(e)

    # width/height in vw/vh with valid viewBox
    svg_content = r'<svg width="100vw" height="100vh" viewBox="0 0 800 600"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 800 and height == 600
    assert 'width="800px"' in updated_svg
    assert 'height="600px"' in updated_svg

    # width/height in vw/vh with valid viewBox
    svg_content = r'<svg width="50vw" height="50vh" viewBox="0 0 800 600"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 400 and height == 300
    assert 'width="400px"' in updated_svg
    assert 'height="300px"' in updated_svg

    # 100% / 100% with viewBox = 800x600
    svg_content = r'<svg width="100%" height="100%" viewBox="0 0 800 600"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 800 and height == 600
    assert 'width="800px"' in updated_svg
    assert 'height="600px"' in updated_svg

    # 50% / 25% with viewBox = 800x600
    svg_content = r'<svg width="50%" height="25%" viewBox="0 0 800 600"></svg>'
    width, height, updated_svg = extract_svg_dimensions_as_px(svg_content)
    assert width == 400 and height == 150
    assert 'width="400px"' in updated_svg
    assert 'height="150px"' in updated_svg


@setup_env_variables
def test_prepare_temp_files():
    svg_filepath, png_filepath = prepare_temp_files(None)
    assert svg_filepath is None and png_filepath is None
    svg_filepath, png_filepath = prepare_temp_files("test")
    assert svg_filepath is not None and svg_filepath != ""
    assert png_filepath is not None and png_filepath != ""


@setup_env_variables
def test_convert_svg_to_png():
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[EXIT_ONE] = "true"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "definitely_not_a_valid_command"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ[EXIT_ONE] = ""
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert res


@setup_env_variables
def test_read_and_cleanup_png():
    png_file = Path("./test.png")
    png_file.touch()
    png_file.write_bytes(b"test")
    assert read_and_cleanup_png(png_file) == b"test"
    # File already cleaned up, return None
    assert read_and_cleanup_png(png_file) is None


@setup_env_variables
def test_create_chromium_command():
    assert create_chromium_command(1, 1, Path("/"), Path("/")) is None
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
        "--force-device-scale-factor=1",
        "--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb",
        "--screenshot=/",
        f"--window-size={1},{1}",
        "/",
    ]


@setup_env_variables
def test_to_base64():
    assert to_base64(b"00000") == "MDAwMDA="
    assert to_base64("abcde") == "YWJjZGU="


@setup_env_variables
def test_convert_to_px():
    assert convert_to_px("10", "px") == 10
    assert convert_to_px("1", "mm") == 378
    assert convert_to_px(None, "px") is None
    assert convert_to_px("abc", "px") is None
    assert convert_to_px("100", "vh") is None
    assert convert_to_px("100", "vw") is None
    assert convert_to_px("100", "%") is None


@setup_env_variables
def test_px_conversion_ratio():
    assert get_px_conversion_ratio("px") == 1
    assert get_px_conversion_ratio("pt") == 4 / 3
    assert get_px_conversion_ratio("in") == 96
    assert get_px_conversion_ratio("cm") == 96 / 2.54
    assert get_px_conversion_ratio("mm") == 96 / 2.54 * 10
    assert get_px_conversion_ratio("pc") == 16
    assert get_px_conversion_ratio("abcde") == 1
    assert get_px_conversion_ratio(None) == 1
