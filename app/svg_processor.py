"""
SVG processing utilities for WeasyPrint service.

Features:
- Convert SVG <svg> to <img src="data:image/svg+xml;base64,...">
- Replace base64 SVG <img> with base64 PNG using Chromium headless
- Handle SVG dimensions, including vw/vh/% via viewBox
"""

from __future__ import annotations

import base64
import contextlib
import logging
import math
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree as DET
from PIL import Image

if TYPE_CHECKING:  # used only for type hints
    from xml.etree.ElementTree import Element


class SvgProcessor:
    """
    Class for processing SVG images in HTML and converting them to PNG via Chromium.
    """

    # MIME/constants
    SPECIAL_UNITS = ("vw", "vh", "%")
    IMAGE_PNG = "image/png"
    IMAGE_SVG = "image/svg+xml"
    NON_SVG_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif")
    VIEWBOX_PARTS_COUNT = 4  # min-x, min-y, width, height
    DATA_PREFIX = "data:"
    SVG_NS = "http://www.w3.org/2000/svg"  # NOSONAR

    def __init__(
        self,
        chromium_executable: str | None = None,
        device_scale_factor: float | None = None,
        chromium_height_adjustment: int = 100,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Args:
            chromium_executable: Path to Chromium/Chrome executable. If None, reads CHROMIUM_EXECUTABLE_PATH.
            device_scale_factor: Device scale factor for rendering. If None, reads DEVICE_SCALE_FACTOR (default 1.0).
            chromium_height_adjustment: Extra height (px) added to window to avoid clipping; later cropped.
            logger: Optional logger; if None, a module-level logger is used.
        """
        self.chromium_executable = chromium_executable or os.environ.get("CHROMIUM_EXECUTABLE_PATH")
        self.device_scale_factor = self._parse_float(os.environ.get("DEVICE_SCALE_FACTOR"), 1.0) if device_scale_factor is None else float(device_scale_factor)
        self.chromium_height_adjustment = int(chromium_height_adjustment)
        self.log = logger or logging.getLogger(__name__)

    # ---------------- Public API ----------------

    def process_svg(self, input_html: BeautifulSoup) -> BeautifulSoup:
        """
        Process <svg> and <img src="data:..."> in the HTML:
        - Replace only top-level <svg> with <img data:image/svg+xml;base64,...>
        - Convert base64 SVG images inside <img> to base64 PNG via Chromium
        """
        self.log.info("Starting SVG processing in HTML")
        parsed_html = self.replace_inline_svgs_with_img(input_html)
        result = self.replace_img_base64(parsed_html)
        self.log.info("Completed SVG processing")
        return result

    def replace_inline_svgs_with_img(self, parsed_html: BeautifulSoup) -> BeautifulSoup:
        """
        Replace only top-level <svg>...</svg> with <img src="data:image/svg+xml;base64,...">.
        Skips nested <svg> (those having an <svg> ancestor). Preserves width/height if present.
        """
        top_level_svgs: list[Tag] = []
        for node in parsed_html.find_all("svg"):
            if isinstance(node, Tag) and node.find_parent("svg") is None:
                top_level_svgs.append(node)

        self.log.debug("Found %d top-level SVG tags to replace with img tags", len(top_level_svgs))
        for svg in top_level_svgs:
            svg_str = str(svg)
            self.log.debug("Converting inline SVG to data URL, size: %d characters", len(svg_str))
            b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
            img: Tag = parsed_html.new_tag("img")

            # Set attributes in the specific order expected by tests: height, src, width
            height = svg.get("height")
            if isinstance(height, str):
                img.attrs["height"] = height

            img.attrs["src"] = f"data:{self.IMAGE_SVG};base64,{b64}"

            width = svg.get("width")
            if isinstance(width, str):
                img.attrs["width"] = width

            svg.replace_with(img)

        return parsed_html

    def replace_img_base64(self, parsed_html: BeautifulSoup) -> BeautifulSoup:
        """
        Replace base64 SVG images with PNG equivalents in HTML <img> tags.
        """
        img_nodes = parsed_html.find_all("img")
        self.log.debug("Found %d img tags to check for SVG data URLs", len(img_nodes))
        converted_count = 0
        for node in img_nodes:
            if not isinstance(node, Tag):
                continue

            src = self._get_attr_str(node, "src")
            parsed = self._parse_data_url_base64(src) if src else None
            if not parsed:
                continue

            content_type, content_base64 = parsed

            svg = self.get_svg(content_type, content_base64)
            if svg is None:
                continue

            image_type, image_content = self.replace_svg_with_png(svg)
            replaced_content_base64 = self.to_base64(image_content)

            # Skip if nothing changed
            if replaced_content_base64 == content_base64:
                continue

            # Preserve original rendered size by setting explicit width on <img>
            self._apply_img_dimensions_from_svg(node, svg)

            node["src"] = f"data:{image_type};base64,{replaced_content_base64}"
            converted_count += 1

        if converted_count > 0:
            self.log.info("Converted %d SVG data URLs to PNG", converted_count)
        return parsed_html

    def _apply_img_dimensions_from_svg(self, node: Tag, svg: Element) -> None:
        """Best-effort: set only width attribute and inline style from SVG px dims."""
        try:
            w, _, _ = self.extract_svg_dimensions_as_px(svg)
            style_val = self._get_attr_str(node, "style") or ""
            style_parts = [s.strip() for s in style_val.split(";") if s.strip()]

            if isinstance(w, int):
                node["width"] = f"{w}px"
                style_parts = [p for p in style_parts if not p.lower().startswith("width:")]
                style_parts.append(f"width: {w}px")

            if style_parts:
                node["style"] = "; ".join(style_parts)

        except Exception as e:
            # Log at debug level to avoid noise but prevent silent pass
            logging.getLogger(__name__).debug("Failed to apply img dimensions from SVG: %s", e)

    # ---------------- Core helpers ----------------

    def _parse_data_url_base64(self, src: str | None) -> tuple[str, str] | None:
        """
        Parse a data URL of the form "data:<content-type>;base64,<payload>".
        Returns a tuple (content_type, base64_payload) or None if not applicable.
        """
        if not src or not src.startswith(self.DATA_PREFIX) or ";base64," not in src:
            return None
        header, b64data = src.split(";base64,", 1)
        if not header.startswith(self.DATA_PREFIX):
            return None
        content_type = header[len(self.DATA_PREFIX) :]
        return content_type, b64data

    def get_svg(self, content_type: str, content_base64: str) -> Element | None:
        """
        Decode and validate base64 content as SVG. Allows incorrect MIME types (common in the wild).
        """
        if content_type in self.NON_SVG_CONTENT_TYPES:
            self.log.debug("Skipping non-SVG content type: %s", content_type)
            return None

        try:
            decoded_content = base64.b64decode(content_base64)
            if b"\0" in decoded_content:
                self.log.debug("Skipping binary content (contains null bytes)")
                return None

            possible_svg_content = decoded_content.decode("utf-8")
            return self.svg_from_string(possible_svg_content)
        except Exception as e:
            self.log.error("Failed to decode base64 content: %s", e)
            return None

    def replace_svg_with_png(self, svg: Element) -> tuple[str, str | bytes]:
        """
        Convert SVG Element to PNG bytes using headless Chromium.
        Returns tuple of (mime, content). If conversion fails, returns original SVG.
        """
        updated_svg = self.ensure_mandatory_attributes(svg)

        width, height, updated_svg = self.extract_svg_dimensions_as_px(updated_svg)
        if not width or not height:
            self.log.warning("Invalid or undefined dimensions for SVG (width: %s, height: %s)", width, height)
            return self.without_changes(svg)
        self.log.debug("Converting SVG (%dx%d px) to PNG with scale factor %.2f", width, height, self.device_scale_factor)

        svg_content = self.svg_to_string(updated_svg)
        svg_filepath, png_filepath = self.prepare_temp_files(svg_content)
        if not svg_filepath or not png_filepath:
            self.log.error("Failed to prepare temporary files for SVG conversion")
            return self.without_changes(svg)

        # Add extra height to prevent clipping, then crop later
        if not self.convert_svg_to_png(width, height + self.chromium_height_adjustment, png_filepath, svg_filepath):
            self.log.error("Failed to convert SVG to PNG using Chromium")
            return self.without_changes(svg)

        if not self.crop_png(png_filepath, max(1, round(self.chromium_height_adjustment * self.device_scale_factor))):
            self.log.warning("Failed to crop PNG")
            return self.without_changes(svg)

        png_content = self.read_and_cleanup_png(png_filepath)
        if not png_content:
            self.log.error("Failed to read generated PNG file")
            return self.without_changes(svg)

        self.log.info("Successfully converted SVG to PNG, size: %d bytes", len(png_content) if isinstance(png_content, bytes) else len(str(png_content)))
        return self.IMAGE_PNG, png_content

    def ensure_mandatory_attributes(self, svg: Element) -> Element:
        # Ensure required XML namespace exists and non-empty
        if not svg.tag.startswith("{"):
            svg.tag = f"{{{SvgProcessor.SVG_NS}}}svg"
        return svg

    def without_changes(self, svg: Element) -> tuple[str, str | bytes]:
        return self.IMAGE_SVG, self.svg_to_string(svg)

    # ---------------- XML / SVG utilities ----------------

    def svg_from_string(self, content: str) -> Element | None:
        try:
            return DET.fromstring(content)
        except DET.ParseError as e:
            self.log.error("Failed to parse SVG content: %s", e)
            return None

    @staticmethod
    def svg_to_string(svg: Element) -> str:
        ET.register_namespace("", SvgProcessor.SVG_NS)  # NOSONAR
        return ET.tostring(svg, encoding="unicode")

    # ---------------- Image utilities ----------------

    def crop_png(self, file_path: Path, bottom_pixels_to_crop: int) -> bool:
        try:
            with Image.open(file_path) as img:
                img_width, img_height = img.size
                if bottom_pixels_to_crop >= img_height:
                    raise ValueError("Not possible to crop more than the height of the picture")
                cropped = img.crop((0, 0, img_width, img_height - bottom_pixels_to_crop))
                cropped.save(file_path)
                return True
        except Exception as e:
            self.log.error("PNG file to crop not found or crop failed: %s", e)
            return False

    # ---------------- Dimension parsing/conversion ----------------

    def extract_svg_dimensions_as_px(self, svg: Element) -> tuple[int | None, int | None, Element]:
        """
        Read width/height, convert to px. If units are relative (vw/vh/%), use viewBox where possible.
        If viewBox present and one/both dimensions missing, set explicit px attributes on the SVG.
        """
        width, width_unit = self.get_svg_dimension(svg, "width")
        height, height_unit = self.get_svg_dimension(svg, "height")
        vb_width, vb_height = self.parse_viewbox(svg)

        width_px = self.calculate_dimension(width, width_unit, vb_width)
        height_px = self.calculate_dimension(height, height_unit, vb_height)

        if vb_width is not None and vb_height is not None:
            if width_px is None:
                width_px = math.ceil(vb_width)
            if height_px is None:
                height_px = math.ceil(vb_height)
            svg = self.replace_svg_size_attributes(svg, width_px, height_px)

        if width_px is None or height_px is None:
            return None, None, svg

        return width_px, height_px, svg

    @staticmethod
    def get_svg_dimension(svg: Element, dimension: str) -> tuple[str | None, str | None]:
        value = svg.attrib.get(dimension)
        if value is None:
            return None, None

        match = re.search(
            r"^(?P<value>-?\d+(?:\.\d+)?)(?P<unit>[a-z%]+)?$",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group("value"), match.group("unit")
        return None, None

    @staticmethod
    def parse_viewbox(svg: Element) -> tuple[float | None, float | None]:
        viewbox = svg.attrib.get("viewBox")
        if viewbox is None:
            return None, None

        # SVG viewBox format: "min-x min-y width height" with spaces and/or commas.
        try:
            # Normalize commas to spaces and split on whitespace
            parts = viewbox.replace(",", " ").split()
            if len(parts) != SvgProcessor.VIEWBOX_PARTS_COUNT:
                return None, None
            vb_width = float(parts[2])
            vb_height = float(parts[3])
            return vb_width, vb_height
        except Exception:
            return None, None

    def calculate_dimension(
        self,
        value: str | None,
        unit: str | None,
        vb_dimension: float | None,
    ) -> int | None:
        if value is None:
            return None

        if unit in self.SPECIAL_UNITS:
            if vb_dimension is None:
                raise ValueError(f"{unit} units require a viewBox to be defined")
            return self.calculate_special_unit(value, unit, vb_dimension)

        return self.convert_to_px(value, unit)

    @staticmethod
    def replace_svg_size_attributes(svg: Element, width_px: int, height_px: int) -> Element:
        svg.set("width", f"{width_px}px")
        svg.set("height", f"{height_px}px")
        return svg

    def calculate_special_unit(self, value: str, unit: str | None, viewbox_dimension: float) -> int:
        try:
            val = float(value)
        except (ValueError, TypeError) as err:
            raise ValueError(f"could not convert string to float: '{value}'") from err

        if unit in self.SPECIAL_UNITS:
            return math.ceil((val / 100) * viewbox_dimension)

        fallback = self.convert_to_px(value, unit)
        if fallback is None:
            raise ValueError(f"Cannot convert unit '{unit}' to px")
        return fallback

    # ---------------- Files / Chromium ----------------

    def prepare_temp_files(self, content: str) -> tuple[Path | None, Path | None]:
        try:
            temp_folder = tempfile.gettempdir()
            uuid = str(uuid4())
            svg_filepath = Path(temp_folder, f"{uuid}.svg")
            png_filepath = Path(temp_folder, f"{uuid}.png")
            with svg_filepath.open("w", encoding="utf-8") as f:
                f.write(content)
            return svg_filepath, png_filepath
        except Exception as e:
            self.log.error("Failed to save SVG to temp file: %s", e)
            return None, None

    def convert_svg_to_png(self, width: int, height: int, png_filepath: Path, svg_filepath: Path) -> bool:
        command = self.create_chromium_command(width, height, png_filepath, svg_filepath)
        if not command:
            self.log.error("Could not determine Chromium executable path")
            return False
        self.log.debug("Running Chromium command for SVG to PNG conversion")

        try:
            result = subprocess.run(command, check=False)  # noqa: S603
            if result.returncode != 0:
                self.log.error("Error converting SVG to PNG, return code = %s", result.returncode)
                return False
            self.log.debug("Chromium screenshot command completed successfully")
            return True
        except Exception as e:
            self.log.error("Failed to run Chromium screenshot command: %s", e)
            return False
        finally:
            # Remove the temporary SVG file regardless of success
            with contextlib.suppress(Exception):
                svg_filepath.unlink(missing_ok=True)

    def read_and_cleanup_png(self, png_filepath: Path) -> bytes | None:
        try:
            with png_filepath.open("rb") as img_file:
                img_data = img_file.read()
            png_filepath.unlink(missing_ok=True)
            return img_data
        except Exception as e:
            self.log.error("Failed to read or clean up PNG file: %s", e)
            return None

    def create_chromium_command(
        self,
        width: int,
        height: int,
        png_filepath: Path,
        svg_filepath: Path,
    ) -> list[str] | None:
        executable = self.chromium_executable or os.environ.get("CHROMIUM_EXECUTABLE_PATH")
        if not executable:
            self.log.error("CHROMIUM_EXECUTABLE_PATH is not set.")
            return None

        return [
            executable,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage",
            "--default-background-color=00000000",
            "--hide-scrollbars",
            f"--force-device-scale-factor={self.device_scale_factor}",
            "--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb",
            f"--screenshot={png_filepath}",
            f"--window-size={width},{height}",
            str(svg_filepath),
        ]

    # ---------------- Generic helpers ----------------

    @staticmethod
    def to_base64(content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return base64.b64encode(content).decode("utf-8")

    def convert_to_px(self, value: str | None, unit: str | None) -> int | None:
        try:
            if value is None:
                raise ValueError()
            value_f64 = float(value)

            if unit in self.SPECIAL_UNITS:
                return None

            return math.ceil(value_f64 * self.get_px_conversion_ratio(unit))
        except ValueError:
            self.log.error("Invalid value for conversion: %s", value)
            return None

    def get_px_conversion_ratio(self, unit: str | None) -> float:
        """
        Convert CSS units to px at 96 DPI.
        Note: Device scale factor should NOT affect layout dimensions; it only controls rasterization DPI.
        """
        if not unit:
            return 1.0
        return {
            "px": 1.0,
            "pt": 4 / 3,
            "in": 96.0,
            "cm": 96 / 2.54,
            "mm": 96 / 2.54 * 10,
            "pc": 16.0,
            "ex": 8.0,
        }.get(unit, 1.0)

    @staticmethod
    def _get_attr_str(tag: Tag, name: str) -> str | None:
        val = tag.get(name)
        return val if isinstance(val, str) else None

    @staticmethod
    def _parse_float(value: str | None, default: float) -> float:
        try:
            return float(value) if value is not None else default
        except ValueError:
            return default
