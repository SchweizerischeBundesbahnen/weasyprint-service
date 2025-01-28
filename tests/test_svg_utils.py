import os
from collections.abc import Callable
from pathlib import Path

from app.svg_utils import *


def setup_env_variables(f: Callable[[], None]) -> Callable[[], None]:
    def inner():
        os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
        os.environ["SET_TEST_EXIT_ONE"] = ""
        os.environ["SET_WRITE_OUTPUT"] = ""
        f()
        os.environ["CHROMIUM_EXECUTABLE_PATH"] = ""
        os.environ["SET_TEST_EXIT_ONE"] = ""
        os.environ["SET_WRITE_OUTPUT"] = ""

    return inner


@setup_env_variables
def test_process_svg():
    html = '<img src="data:image/svg+xml;base64,123ABC=="/>"'
    content = process_svg(html)
    assert content == html

    html = '<img src="data:image/png;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"'
    content = process_svg(html)
    assert content == html

    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "./test.sh"
    os.environ["SET_WRITE_OUTPUT"] = "true"
    html = '<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"'
    expected_output = f'<img src="data:image/png;base64,{base64.b64encode(b"test\n").decode("utf-8")}"/>"'
    content = process_svg(html)
    assert content == expected_output


@setup_env_variables
def test_get_svg_content():
    content = get_svg_content("image/png", "123ABC==")
    assert content is None

    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiAA==")
    assert content is None

    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgi")
    assert content is None

    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+")
    assert content == r'<svg height="200px" width="100px"</svg>'

    content = get_svg_content("image/svg+xml", "PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc¨")
    assert content is None


@setup_env_variables
def test_replace_img_base64():
    pass


@setup_env_variables
def test_replace_svg_with_png():
    svg_content = r'<svg height=200px" width "100px'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    svg_content = r'<svg height="200px" width="100px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "./test.sh"
    svg_content = r'<svg height="200px" width="100px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_SVG, content == svg_content

    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "./test.sh"
    os.environ["SET_WRITE_OUTPUT"] = "true"
    svg_content = r'<svg height="200px" width="100px"'
    mime, content = replace_svg_with_png(svg_content)
    assert mime == IMAGE_PNG, content == b"test\n"


@setup_env_variables
def test_extract_svg_dimensions_as_px():
    svg_content = r'<svg height="200px" width="100px">'
    width, height = extract_svg_dimensions_as_px(svg_content)
    assert width == 100 and height == 200

    svg_content = r'<svg height=200px" width "100px'
    width, height = extract_svg_dimensions_as_px(svg_content)
    assert width is None and height is None


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
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "./test.sh"
    os.environ["SET_TEST_EXIT_ONE"] = "true"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "definitely_not_a_valid_command"
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert not res
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "./test.sh"
    os.environ["SET_TEST_EXIT_ONE"] = ""
    res = convert_svg_to_png(1, 1, Path("/"), Path("/"))
    assert res


@setup_env_variables
def test_read_and_cleanup_png():
    png_file = Path("./test.png")
    png_file.touch()
    png_file.write_bytes(b"test")
    assert read_and_cleanup_png(png_file) == b"test"
    assert read_and_cleanup_png(png_file) is None


@setup_env_variables
def test_create_chromium_command():
    assert create_chromium_command(1, 1, Path("/"), Path("/")) is None
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = "/"
    assert create_chromium_command(1, 1, Path("/"), Path("/")) == [
        "/",
        "--headless=old",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--default-background-color=00000000",
        "--hide-scrollbars",
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
