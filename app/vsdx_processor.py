"""
VSDX processing utilities for WeasyPrint service.

Features:
- Convert VSDX base64 data URLs to PNG using LibreOffice headless
- Handle VSDX dimensions and scaling
- Fallback to original content if conversion fails
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, Tag


class VsdxConversionError(Exception):
    """Base exception for VSDX conversion errors."""


class LibreOfficeNotAvailableError(VsdxConversionError):
    """LibreOffice is not available or not working."""


class VsdxCorruptedError(VsdxConversionError):
    """VSDX file is corrupted or invalid."""


class VsdxProcessor:
    """
    Class for processing VSDX images in HTML and converting them to PNG via LibreOffice.
    """

    # MIME/constants
    IMAGE_PNG = "image/png"
    VSDX_MIME_TYPE = "application/vnd.ms-visio.drawing"
    DATA_PREFIX = "data:"

    # Configuration from environment
    LIBREOFFICE_TIMEOUT = int(os.environ.get("LIBREOFFICE_TIMEOUT", "30"))

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize VsdxProcessor with LibreOffice-based conversion.

        Args:
            logger: Optional logger; if None, a module-level logger is used.
        """
        self.log = logger or logging.getLogger(__name__)
        self.libreoffice_available = self._check_libreoffice_availability()

    # ---------------- Public API ----------------

    async def process_vsdx(self, input_html: BeautifulSoup) -> BeautifulSoup:
        """
        Process VSDX data URLs in <img> tags and convert them to PNG.
        """
        self.log.info("Starting VSDX processing in HTML")
        result = await self.replace_vsdx_base64(input_html)
        self.log.info("Completed VSDX processing")
        return result

    async def replace_vsdx_base64(self, parsed_html: BeautifulSoup) -> BeautifulSoup:
        """
        Replace base64 VSDX images with PNG equivalents in HTML <img> tags via LibreOffice.
        """
        # Early exit if LibreOffice is not available
        if not self.libreoffice_available:
            self.log.warning("LibreOffice not available, skipping VSDX conversion")
            return parsed_html

        img_nodes = parsed_html.find_all("img")
        self.log.debug("Found %d img tags to check for VSDX data URLs", len(img_nodes))
        converted_count = 0

        for node in img_nodes:
            if not isinstance(node, Tag):
                continue

            src = self._get_attr_str(node, "src")
            parsed = self._parse_data_url_base64(src) if src else None
            if not parsed:
                continue

            content_type, content_base64 = parsed

            if not self._is_vsdx_content(content_type):
                continue

            try:
                png_content = await self._convert_vsdx_to_png(content_base64)
                png_base64 = base64.b64encode(png_content).decode("ascii")
                node["src"] = f"data:{self.IMAGE_PNG};base64,{png_base64}"
                converted_count += 1
                self.log.debug("Successfully converted VSDX to PNG")
            except VsdxConversionError as e:
                self.log.warning("VSDX conversion failed, keeping original: %s", e)
            except Exception as e:
                self.log.error("Unexpected error converting VSDX: %s", e)

        if converted_count > 0:
            self.log.info("Converted %d VSDX data URLs to PNG", converted_count)
        return parsed_html

    # ---------------- Core helpers ----------------

    def _check_libreoffice_availability(self) -> bool:
        """Check if LibreOffice is available. Returns True if available."""
        try:
            result = subprocess.run(
                ["libreoffice", "--version"],  # noqa: S603, S607
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                self.log.info("LibreOffice available: %s", result.stdout.strip())
                return True
            else:
                self.log.warning("LibreOffice not available, VSDX conversion will be disabled")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.log.warning("LibreOffice not found: %s, VSDX conversion will be disabled", e)
            return False

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

    def _is_vsdx_content(self, content_type: str) -> bool:
        """Check if content type indicates VSDX format."""
        return content_type == self.VSDX_MIME_TYPE

    async def _convert_vsdx_to_png(self, vsdx_base64: str) -> bytes:
        """
        Convert VSDX base64 content to PNG bytes using LibreOffice headless.
        Raises VsdxConversionError on failure.
        """
        temp_dir = None
        try:
            # Decode VSDX content
            vsdx_content = base64.b64decode(vsdx_base64)

            # Check if VSDX is valid ZIP (VSDX is ZIP format)
            if not vsdx_content.startswith(b"PK"):
                msg = f"VSDX missing ZIP header: {vsdx_content[:10]}"
                raise VsdxCorruptedError(msg)

            temp_dir = tempfile.mkdtemp()
            temp_path = Path(temp_dir)

            # Write VSDX file
            vsdx_file = temp_path / "input.vsdx"
            vsdx_file.write_bytes(vsdx_content)

            # Convert to PNG using LibreOffice
            png_file = temp_path / "input.png"

            cmd = ["libreoffice", "--headless", "--invisible", "--convert-to", "png", "--outdir", str(temp_path), str(vsdx_file)]

            self.log.debug("Running LibreOffice conversion: %s", " ".join(cmd))

            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=self.LIBREOFFICE_TIMEOUT,
                check=False,
            )

            if result.returncode != 0:
                msg = f"LibreOffice conversion failed (exit code {result.returncode}): {result.stderr.strip()}"
                raise VsdxConversionError(msg)

            if not png_file.exists():
                msg = "LibreOffice did not create PNG output file"
                raise VsdxConversionError(msg)

            png_content = png_file.read_bytes()
            self.log.debug("Successfully converted VSDX to PNG (%d bytes)", len(png_content))
            return png_content

        except subprocess.TimeoutExpired as e:
            msg = f"LibreOffice conversion timed out after {self.LIBREOFFICE_TIMEOUT} seconds"
            raise VsdxConversionError(msg) from e
        except binascii.Error as e:
            msg = f"Invalid base64 data: {e}"
            raise VsdxCorruptedError(msg) from e
        except VsdxConversionError:
            # Re-raise custom exceptions
            raise
        except Exception as e:
            msg = f"Unexpected error in VSDX conversion: {e}"
            raise VsdxConversionError(msg) from e
        finally:
            # Resource cleanup - ensure temp directory is always cleaned up
            if temp_dir and Path(temp_dir).exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    self.log.warning("Failed to cleanup temp directory %s: %s", temp_dir, e)

    # ---------------- Generic helpers ----------------

    @staticmethod
    def _get_attr_str(tag: Tag, name: str) -> str | None:
        val = tag.get(name)
        return val if isinstance(val, str) else None
