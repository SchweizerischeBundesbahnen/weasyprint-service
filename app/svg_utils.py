"""SVG processing utilities for WeasyPrint service.

This module provides functionality for processing SVG images, including:
- Converting SVG dimensions to absolute pixel values
- Handling relative units (vw, vh, %)
- Converting SVG to PNG using Chromium
- Processing base64-encoded SVG images in HTML

"""

import base64
import logging
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from defusedxml import ElementTree as ET
from PIL import Image

# Constants
SPECIAL_UNITS = ("vw", "vh", "%")  # Special units that require viewBox context
IMAGE_PNG = "image/png"
IMAGE_SVG = "image/svg+xml"
NON_SVG_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif")
CHROMIUM_HEIGHT_ADJUSTMENT = 100

# Logging setup
logger = logging.getLogger(__name__)


def process_svg(html: str) -> str:
    """Process img tags in HTML, replacing base64 SVG images with PNGs.

    Args:
        html: HTML content containing SVG images.

    Returns:
        str: Modified HTML with SVG images converted to PNG where appropriate.

    Performance:
        - Time complexity: O(n) where n is the number of SVG images
        - Memory complexity: O(m) where m is the size of the largest SVG
    """
    pattern = re.compile(r'<img(?P<intermediate>[^>]+?src="data:)(?P<type>[^;>]+)?;base64,\s?(?P<base64>[^">]+)?"')
    return re.sub(pattern, replace_img_base64, html)


def get_svg_content(content_type: str, content_base64: str) -> str | None:
    """Decode and validate base64 content as SVG.

    Args:
        content_type: MIME type of the content.
        content_base64: Base64 encoded content.

    Returns:
        str | None: Decoded SVG content if valid, None if content is invalid or not SVG.

    Note:
        We do not require 'image/svg+xml' content type as not all systems set it correctly.
    """
    if content_type in NON_SVG_CONTENT_TYPES:
        logger.debug(f"Skipping non-SVG content type: {content_type}")
        return None

    try:
        decoded_content = base64.b64decode(content_base64)
        if b"\0" in decoded_content:
            logger.debug("Skipping binary content (contains null bytes)")
            return None

        svg_content = decoded_content.decode("utf-8")
        if "</svg>" not in svg_content:
            logger.debug("Content is not SVG (missing </svg> tag)")
            return None

        return svg_content
    except Exception as e:
        logger.error(f"Failed to decode base64 content: {e}")
        return None


def replace_img_base64(match: re.Match[str]) -> str:
    """Replace base64 SVG images with PNG equivalents in HTML img tags.

    Args:
        match: Regular expression match object containing the img tag components.

    Returns:
        str: Modified img tag with SVG replaced by PNG if conversion successful,
             otherwise returns original tag.
    """
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


def replace_svg_with_png(svg_content: str) -> tuple[str, str | bytes]:
    """Convert SVG content to PNG format.

    Args:
        svg_content: SVG content as string.

    Returns:
        tuple[str, str | bytes]: Tuple containing:
            - MIME type of the result ('image/svg+xml' or 'image/png')
            - Content as either SVG string or PNG bytes
    """
    width, height, updated_svg_content = extract_svg_dimensions_as_px(svg_content)
    if not width or not height:
        return IMAGE_SVG, svg_content

    svg_filepath, png_filepath = prepare_temp_files(updated_svg_content)
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


def crop_png(file_path: Path, bottom_pixels_to_crop: int) -> bool:
    """Remove specified number of pixels from bottom of PNG image.

    Args:
        file_path: Path to the PNG file.
        bottom_pixels_to_crop: Number of pixels to remove from bottom.

    Returns:
        bool: True if cropping successful, False otherwise.

    Raises:
        ValueError: If attempting to crop more pixels than image height.
    """
    try:
        with Image.open(file_path) as img:
            img_width, img_height = img.size

            if bottom_pixels_to_crop >= img_height:
                raise ValueError("Not possible to crop more than the height of the picture")

            cropped = img.crop((0, 0, img_width, img_height - bottom_pixels_to_crop))
            cropped.save(file_path)
            return True
    except Exception as e:
        logger.error(f"PNG file to crop not found: {e}")
        return False


def extract_svg_dimensions_as_px(svg_content: str) -> tuple[int | None, int | None, str]:
    """Extract and convert SVG dimensions to pixels.

    Processes width and height from SVG tag, converting to absolute pixel values.
    For relative units (vw, vh, %) uses viewBox for conversion if available.

    Args:
        svg_content: SVG content as string.

    Returns:
        tuple[int | None, int | None, str]: Tuple containing:
            - Width in pixels or None if not determinable
            - Height in pixels or None if not determinable
            - Updated SVG content with explicit pixel dimensions if viewBox used
    """
    width, width_unit = parse_svg_dimension(svg_content, "width")
    height, height_unit = parse_svg_dimension(svg_content, "height")
    vb_width, vb_height = parse_viewbox(svg_content)

    width_px = calculate_dimension(width, width_unit, vb_width)
    height_px = calculate_dimension(height, height_unit, vb_height)

    if vb_width is not None and vb_height is not None:
        if width_px is None:
            width_px = math.ceil(vb_width)
        if height_px is None:
            height_px = math.ceil(vb_height)
        svg_content = replace_svg_size_attributes(svg_content, width_px, height_px)

    if width_px is None or height_px is None:
        return None, None, svg_content

    return width_px, height_px, svg_content


def parse_svg_dimension(svg_content: str, dimension: str) -> tuple[str | None, str | None]:
    """Extract dimension value and unit from SVG tag.

    Args:
        svg_content: SVG content as string.
        dimension: Name of dimension attribute to parse ('width' or 'height').

    Returns:
        tuple[str | None, str | None]: Tuple containing:
            - Dimension value as string or None if not found
            - Unit as string or None if not specified
    """
    match = re.search(
        rf'<svg[^>]*?\b{dimension}\s*=\s*["\'](?P<value>[\d.]+)(?P<unit>\w+|%)?["\']',
        svg_content,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group("value"), match.group("unit")
    return None, None


def parse_viewbox(svg_content: str) -> tuple[float | None, float | None]:
    """Extract width and height from SVG viewBox attribute.

    Args:
        svg_content: SVG content as string.

    Returns:
        tuple[float | None, float | None]: Tuple containing:
            - ViewBox width as float or None if not found
            - ViewBox height as float or None if not found
    """
    match = re.search(
        r'<svg[^>]*?\bviewBox\s*=\s*["\']'
        r"[\d.\-]+\s+[\d.\-]+\s+"
        r"(?P<vb_width>[\d.\-]+)\s+"
        r"(?P<vb_height>[\d.\-]+)"
        r'["\']',
        svg_content,
        flags=re.IGNORECASE,
    )
    if match:
        return float(match.group("vb_width")), float(match.group("vb_height"))
    return None, None


def calculate_dimension(value: str | None, unit: str | None, vb_dimension: float | None) -> int | None:
    """Calculate absolute pixel value from dimension with unit.

    Args:
        value: Numeric value as string.
        unit: Unit of measurement (px, pt, in, cm, mm, pc, vw, vh, %).
        vb_dimension: ViewBox dimension for relative unit conversion.

    Returns:
        int | None: Dimension in pixels or None if conversion not possible.

    Raises:
        ValueError: If relative unit used without viewBox being defined.
    """
    if value is None:
        return None

    if unit in SPECIAL_UNITS:
        if vb_dimension is None:
            raise ValueError(f"{unit} units require a viewBox to be defined")
        return calculate_special_unit(value, unit, vb_dimension)

    return convert_to_px(value, unit)


def replace_svg_size_attributes(svg_content: str, width_px: int, height_px: int) -> str:
    """Update SVG width and height attributes with pixel values.

    Args:
        svg_content: SVG content as string.
        width_px: Width in pixels.
        height_px: Height in pixels.

    Returns:
        str: Updated SVG content with explicit pixel dimensions.

    Raises:
        ValueError: If SVG content is invalid and cannot be parsed.
    """
    try:
        root = ET.fromstring(svg_content)
    except ET.ParseError as e:
        raise ValueError("Invalid SVG content") from e

    # Set or replace width and height attributes
    root.set("width", f"{width_px}px")
    root.set("height", f"{height_px}px")

    # Convert XML tree back to a string
    return ET.tostring(root, encoding="unicode")


def calculate_special_unit(value: str, unit: str | None, viewbox_dimension: float) -> int:
    """Calculate pixel value for relative units (vw, vh, %).

    Args:
        value: Numeric value as string.
        unit: Unit of measurement (vw, vh, % or others).
        viewbox_dimension: ViewBox dimension for relative unit conversion.

    Returns:
        int: Calculated pixel value.

    Raises:
        ValueError: If unit conversion fails.
    """
    val = float(value)

    if unit in SPECIAL_UNITS:
        return math.ceil((val / 100) * viewbox_dimension)

    fallback = convert_to_px(value, unit)
    if fallback is None:
        raise ValueError(f"Cannot convert unit '{unit}' to px")

    return fallback


def prepare_temp_files(svg_content: str) -> tuple[Path | None, Path | None]:
    """Create temporary files for SVG to PNG conversion.

    Args:
        svg_content: SVG content to write to temporary file.

    Returns:
        tuple[Path | None, Path | None]: Tuple containing:
            - Path to temporary SVG file or None if creation failed
            - Path to temporary PNG file or None if creation failed
    """
    try:
        temp_folder = tempfile.gettempdir()
        uuid = str(uuid4())

        svg_filepath = Path(temp_folder, f"{uuid}.svg")
        png_filepath = Path(temp_folder, f"{uuid}.png")

        with svg_filepath.open("w", encoding="utf-8") as f:
            f.write(svg_content)

        return svg_filepath, png_filepath
    except Exception as e:
        logger.error(f"Failed to save SVG to temp file: {e}")
        return None, None


def convert_svg_to_png(width: int, height: int, png_filepath: Path, svg_filepath: Path) -> bool:
    """Convert SVG file to PNG using Chromium headless browser.

    Args:
        width: Desired width of PNG in pixels.
        height: Desired height of PNG in pixels.
        png_filepath: Path where PNG should be saved.
        svg_filepath: Path to source SVG file.

    Returns:
        bool: True if conversion successful, False otherwise.
    """
    command = create_chromium_command(width, height, png_filepath, svg_filepath)
    if not command:
        return False

    try:
        result = subprocess.run(command, check=False)  # noqa: S603
        if result.returncode != 0:
            logger.error(f"Error converting SVG to PNG, return code = {result.returncode}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to convert SVG to PNG: {e}")
        return False


def read_and_cleanup_png(png_filepath: Path) -> bytes | None:
    """Read PNG file contents and delete the file.

    Args:
        png_filepath: Path to PNG file.

    Returns:
        bytes | None: PNG file contents as bytes, or None if read failed.
    """
    try:
        with png_filepath.open("rb") as img_file:
            img_data = img_file.read()

        png_filepath.unlink()
        return img_data
    except Exception as e:
        logger.error(f"Failed to read or clean up PNG file: {e}")
        return None


def create_chromium_command(width: int, height: int, png_filepath: Path, svg_filepath: Path) -> list[str] | None:
    """Create Chromium command for headless SVG to PNG conversion.

    Args:
        width: Desired width of PNG in pixels.
        height: Desired height of PNG in pixels.
        png_filepath: Path where PNG should be saved.
        svg_filepath: Path to source SVG file.

    Returns:
        list[str] | None: Command as list of strings, or None if Chromium path not found.
    """
    chromium_executable = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if not chromium_executable:
        logger.error("CHROMIUM_EXECUTABLE_PATH is not set.")
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


def to_base64(content: str | bytes) -> str:
    """Convert string or bytes to base64 encoded string.

    Args:
        content: Content to encode, either as string or bytes.

    Returns:
        str: Base64 encoded string.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")  # encode the string to bytes
    return base64.b64encode(content).decode("utf-8")


def convert_to_px(value: str | None, unit: str | None) -> int | None:
    """Convert value with unit to pixels.

    Args:
        value: Numeric value as string.
        unit: Unit of measurement (px, pt, in, cm, mm, pc).

    Returns:
        int | None: Value in pixels, or None if conversion not possible.
    """
    try:
        if value is None:
            raise ValueError()
        value_f64 = float(value)

        if unit in SPECIAL_UNITS:
            return None

        return math.ceil(value_f64 * get_px_conversion_ratio(unit))
    except ValueError:
        logger.error(f"Invalid value for conversion: {value}")
        return None


def get_px_conversion_ratio(unit: str | None) -> float:
    """Get conversion ratio from unit to pixels.

    Args:
        unit: Unit of measurement (px, pt, in, cm, mm, pc).

    Returns:
        float: Conversion ratio to multiply by to get pixels.
    """
    return {"px": 1.0, "pt": 4 / 3, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 2.54 * 10, "pc": 16.0}.get(unit, 1.0) if unit else 1.0
