import base64
import logging
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image

IMAGE_PNG = "image/png"
IMAGE_SVG = "image/svg+xml"

NON_SVG_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif")
CHROMIUM_HEIGHT_ADJUSTMENT = 100


# Process img tags, replacing base64 SVG images with PNGs
def process_svg(html: str) -> str:
    pattern = re.compile(r'<img(?P<intermediate>[^>]+?src="data:)(?P<type>[^;>]+)?;base64,\s?(?P<base64>[^">]+)?"')
    return re.sub(pattern, replace_img_base64, html)


# Decode and validate if the provided content is SVG.
def get_svg_content(content_type: str, content_base64: str) -> str | None:
    # We do not require to have 'image/svg+xml' content type coz not all systems will properly set it

    if content_type in NON_SVG_CONTENT_TYPES:
        return None  # Skip processing if content type set explicitly as not svg

    try:
        decoded_content = base64.b64decode(content_base64)
        if b"\0" in decoded_content:
            return None  # Skip processing if decoded content is binary (not text)

        svg_content = decoded_content.decode("utf-8")

        # Fast check that this is a svg
        if "</svg>" not in svg_content:
            return None

        return svg_content
    except Exception as e:
        logging.error(f"Failed to decode base64 content: {e}")
        return None


# Replace base64 SVG images with PNG equivalents in the HTML img tag.
def replace_img_base64(match: re.Match[str]) -> str:
    entry = match.group(0)
    content_type = match.group("type")
    content_base64 = match.group("base64")

    svg_content = get_svg_content(content_type, content_base64)
    if not svg_content:
        return entry

    image_type, content = replace_svg_with_png(svg_content)
    replaced_content_base64 = to_base64(content)
    if replaced_content_base64 == content_base64:
        return entry  # For some reason content wasn't replaced

    return f'<img{match.group("intermediate")}{image_type};base64,{replaced_content_base64}"'


# Checks that base64 encoded content is a svg image and replaces it with the png screenshot made by chromium
def replace_svg_with_png(svg_content: str) -> tuple[str, str | bytes]:
    width, height = extract_svg_dimensions_as_px(svg_content)
    if not width or not height:
        return IMAGE_SVG, svg_content

    svg_filepath, png_filepath = prepare_temp_files(svg_content)
    if not svg_filepath or not png_filepath:
        return IMAGE_SVG, svg_content

    if not convert_svg_to_png(width, height + CHROMIUM_HEIGHT_ADJUSTMENT, png_filepath, svg_filepath):  # Add 100 pixels to height to make chromium render the entire svg
        return IMAGE_SVG, svg_content

    if not crop_png(png_filepath, CHROMIUM_HEIGHT_ADJUSTMENT):
        return IMAGE_SVG, svg_content

    png_content = read_and_cleanup_png(png_filepath)
    if not png_content:
        return IMAGE_SVG, svg_content

    return IMAGE_PNG, png_content


# Remove added bottom pixels from PNG after conversion
def crop_png(file_path: Path, bottom_pixels_to_crop: int) -> bool:
    try:
        with Image.open(file_path) as img:
            img_width, img_height = img.size

            if bottom_pixels_to_crop >= img_height:
                raise ValueError("Not possible to crop more than the height of the picture")

            cropped = img.crop((0, 0, img_width, img_height - bottom_pixels_to_crop))
            cropped.save(file_path)
            return True
    except Exception as e:
        logging.error(f"PNG file to crop not found: {e}")
        return False


# Extract the width and height from the SVG tag (and convert it to px)
def extract_svg_dimensions_as_px(svg_content: str) -> tuple[int | None, int | None]:
    width_match = re.search(r'<svg[^>]+?width="(?P<width>[\d.]+)(?P<unit>\w+)?', svg_content)
    height_match = re.search(r'<svg[^>]+?height="(?P<height>[\d.]+)(?P<unit>\w+)?', svg_content)

    width = width_match.group("width") if width_match else None
    height = height_match.group("height") if height_match else None

    if not width or not height:
        logging.error(f"Cannot find SVG dimensions. Width: {width}, Height: {height}")

    width_unit = width_match.group("unit") if width_match else None
    height_unit = height_match.group("unit") if height_match else None

    return convert_to_px(width, width_unit), convert_to_px(height, height_unit)


# Save the SVG content to a temporary file and return the file paths for the SVG and PNG.
def prepare_temp_files(svg_content: str) -> tuple[Path | None, Path | None]:
    try:
        temp_folder = tempfile.gettempdir()
        uuid = str(uuid4())

        svg_filepath = Path(temp_folder, f"{uuid}.svg")
        png_filepath = Path(temp_folder, f"{uuid}.png")

        with svg_filepath.open("w", encoding="utf-8") as f:
            f.write(svg_content)

        return svg_filepath, png_filepath
    except Exception as e:
        logging.error(f"Failed to save SVG to temp file: {e}")
        return None, None


# Convert the SVG file to PNG using Chromium and return success status
def convert_svg_to_png(width: int, height: int, png_filepath: Path, svg_filepath: Path) -> bool:
    command = create_chromium_command(width, height, png_filepath, svg_filepath)
    if not command:
        return False

    try:
        result = subprocess.run(command, check=False)  # noqa: S603
        if result.returncode != 0:
            logging.error(f"Error converting SVG to PNG, return code = {result.returncode}")
            return False
        return True
    except Exception as e:
        logging.error(f"Failed to convert SVG to PNG: {e}")
        return False


# Read the PNG file and clean up the temporary file
def read_and_cleanup_png(png_filepath: Path) -> bytes | None:
    try:
        with png_filepath.open("rb") as img_file:
            img_data = img_file.read()

        png_filepath.unlink()
        return img_data
    except Exception as e:
        logging.error(f"Failed to read or clean up PNG file: {e}")
        return None


# Create the Chromium command for converting SVG to PNG
def create_chromium_command(width: int, height: int, png_filepath: Path, svg_filepath: Path) -> list[str] | None:
    chromium_executable = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if not chromium_executable:
        logging.error("CHROMIUM_EXECUTABLE_PATH is not set.")
        return None

    command = [
        chromium_executable,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--default-background-color=00000000",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb",
        f"--screenshot={png_filepath}",
        f"--window-size={width},{height}",
        str(svg_filepath),
    ]

    return command


# Encode string or byte array to base64
def to_base64(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")  # encode the string to bytes
    return base64.b64encode(content).decode("utf-8")


# Conversion to px
def convert_to_px(value: str | None, unit: str | None) -> int | None:
    try:
        if value is None:
            raise ValueError()
        value_f64 = float(value)
        return math.ceil(value_f64 * get_px_conversion_ratio(unit))
    except ValueError:
        logging.error(f"Invalid value for conversion: {value}")
        return None


def get_px_conversion_ratio(unit: str | None) -> float:
    return {"px": 1.0, "pt": 4 / 3, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 2.54 * 10, "pc": 16.0}.get(unit, 1.0) if unit else 1.0
