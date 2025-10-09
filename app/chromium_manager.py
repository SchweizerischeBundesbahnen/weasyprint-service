"""
Chromium browser management via Chrome DevTools Protocol (CDP).

This module provides a singleton ChromiumManager that maintains a persistent
Chromium browser process for fast SVG to PNG conversion, avoiding the overhead
of starting a new browser process for each conversion.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from playwright.async_api import ViewportSize, async_playwright

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser, BrowserContext, Page, Playwright


class ChromiumManager:
    """
    Singleton manager for a persistent Chromium browser process.

    Manages the lifecycle of a headless Chromium instance for converting
    SVG images to PNG using Chrome DevTools Protocol via Playwright.
    """

    def __init__(self, device_scale_factor: float | None = None, logger: logging.Logger | None = None, max_concurrent_conversions: int | None = None, restart_after_n_conversions: int | None = None) -> None:
        """
        Initialize ChromiumManager.

        Args:
            device_scale_factor: Device scale factor for rendering. If None, reads DEVICE_SCALE_FACTOR (default 1.0).
            logger: Optional logger; if None, a module-level logger is used.
            max_concurrent_conversions: Maximum concurrent SVG conversions. If None, reads MAX_CONCURRENT_CONVERSIONS (default 10).
            restart_after_n_conversions: Restart Chromium after N conversions. If None, reads CHROMIUM_RESTART_AFTER_N_CONVERSIONS (default 0 = disabled).
        """
        self.device_scale_factor = self._parse_float(os.environ.get("DEVICE_SCALE_FACTOR"), 1.0) if device_scale_factor is None else float(device_scale_factor)
        self.log = logger or logging.getLogger(__name__)

        # Parse max concurrent conversions from env or use provided value
        if max_concurrent_conversions is None:
            max_concurrent_conversions = int(os.environ.get("MAX_CONCURRENT_CONVERSIONS", "10"))
        self.max_concurrent_conversions = max_concurrent_conversions

        # Parse restart threshold from env or use provided value
        if restart_after_n_conversions is None:
            restart_after_n_conversions = int(os.environ.get("CHROMIUM_RESTART_AFTER_N_CONVERSIONS", "0"))
        self.restart_after_n_conversions = restart_after_n_conversions

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self.max_concurrent_conversions)
        self._started = False
        self._conversion_count = 0

    async def start(self) -> None:
        """Start the persistent Chromium browser process."""
        async with self._lock:
            if self._started:
                self.log.warning("Chromium already started")
                return

            try:
                self.log.info("Starting Chromium browser process via Playwright...")
                self._playwright = await async_playwright().start()

                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-software-rasterizer",
                        "--disable-dev-shm-usage",
                        "--disable-web-security",  # Allow rendering of local and data URLs without CORS restrictions
                        "--disable-features=IsolateOrigins,site-per-process",  # Disable strict site isolation (needed for local/data URLs to access embedded resources)
                        "--hide-scrollbars",
                    ],
                )

                self._started = True
                self.log.info("Chromium browser started successfully")
            except ImportError as e:
                self.log.error("Playwright not installed: %s", e)
                raise RuntimeError("Playwright library is required for ChromiumManager") from e
            except Exception as e:
                self.log.error("Failed to start Chromium: %s", e)
                self._started = False
                raise

    async def stop(self) -> None:
        """Stop the persistent Chromium browser process."""
        async with self._lock:
            if not self._started:
                return

            try:
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception as e:  # noqa: BLE001
                        self.log.error("Error closing browser: %s", e)
                    finally:
                        self._browser = None

                if self._playwright:
                    try:
                        await self._playwright.stop()
                    except Exception as e:  # noqa: BLE001
                        self.log.error("Error stopping Playwright: %s", e)
                    finally:
                        self._playwright = None

                self.log.info("Chromium browser stopped successfully")
            finally:
                # Always mark as stopped and clear resources, even if cleanup fails
                self._started = False
                self._browser = None
                self._playwright = None

    def is_running(self) -> bool:
        """Check if the Chromium browser is running."""
        return self._started and self._browser is not None

    async def health_check(self) -> bool:
        """
        Perform a health check on the Chromium browser.

        Returns:
            True if the browser is healthy, False otherwise.
        """
        try:
            if not self.is_running():
                return False

            # Quick check: create and close a page
            async with self._get_page() as page:
                await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)

            return True
        except Exception as e:  # noqa: BLE001
            self.log.error("Health check failed: %s", e)
            return False

    async def get_version(self) -> str | None:
        """
        Get the Chromium browser version.

        Returns:
            Chromium version string (e.g., "131.0.6778.69") or None if browser is not running.
        """
        try:
            if not self.is_running() or not self._browser:
                return None

            version_string = self._browser.version
            # Extract version number from "HeadlessChrome/131.0.6778.69" format
            if "/" in version_string:
                return version_string.split("/")[1]
            return version_string
        except Exception as e:  # noqa: BLE001
            self.log.error("Failed to get Chromium version: %s", e)
            return None

    async def restart(self) -> None:
        """Restart the Chromium browser (useful for recovering from errors)."""
        self.log.info("Restarting Chromium browser...")
        await self.stop()
        await self.start()
        # Reset conversion counter after restart
        self._conversion_count = 0

    async def _check_and_restart_if_needed(self) -> None:
        """
        Check if Chromium needs to be restarted based on conversion count.

        If restart_after_n_conversions > 0 and conversion count reaches the threshold,
        restarts Chromium automatically.
        """
        if self.restart_after_n_conversions <= 0:
            return  # Auto-restart disabled

        if self._conversion_count >= self.restart_after_n_conversions:
            conversions_before_restart = self._conversion_count
            self.log.info(
                "Conversion count (%d) reached threshold (%d), restarting Chromium...",
                conversions_before_restart,
                self.restart_after_n_conversions,
            )
            await self.restart()
            self.log.info("Chromium restarted successfully after %d conversions", conversions_before_restart)

    async def convert_svg_to_png(self, svg_content: str, width: int, height: int, device_scale_factor: float | None = None) -> bytes:
        """
        Convert SVG content to PNG using the persistent Chromium instance.

        Args:
            svg_content: SVG content as a string (XML).
            width: Target width in pixels.
            height: Target height in pixels.
            device_scale_factor: Device scale factor for this conversion. If None, uses instance default.

        Returns:
            PNG image data as bytes.

        Raises:
            RuntimeError: If Chromium is not started or conversion fails.
        """
        if not self.is_running():
            raise RuntimeError("Chromium not started. Call start() first.")

        # Increment conversion counter BEFORE performing conversion
        self._conversion_count += 1

        # Check if restart is needed (after incrementing counter)
        await self._check_and_restart_if_needed()

        # Use provided scale factor or fall back to instance default
        scale_factor = device_scale_factor if device_scale_factor is not None else self.device_scale_factor

        # Encode SVG as base64 for data URL
        svg_base64 = base64.b64encode(svg_content.encode("utf-8")).decode("ascii")

        # Create HTML wrapper for SVG
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ width: {width}px; height: {height}px; overflow: hidden; }}
        body {{ background: transparent; display: flex; align-items: center; justify-content: center; }}
        img {{ display: block; max-width: 100%; max-height: 100%; }}
    </style>
</head>
<body>
    <img src="data:image/svg+xml;base64,{svg_base64}" alt="SVG" />
</body>
</html>"""

        async with self._get_page(scale_factor) as page:
            # Set viewport to exact dimensions
            await page.set_viewport_size(ViewportSize(width=width, height=height))

            # Load HTML content with data URL (no network requests, so domcontentloaded is sufficient)
            await page.set_content(html_content, wait_until="domcontentloaded", timeout=5000)

            # Take screenshot with transparent background
            png_bytes = await page.screenshot(
                type="png",
                omit_background=True,  # Transparent background
                full_page=False,  # Only viewport
            )

            return png_bytes

    @asynccontextmanager
    async def _get_page(self, device_scale_factor: float | None = None) -> AsyncGenerator[Page]:
        """
        Context manager to get a new browser page (tab).

        Args:
            device_scale_factor: Device scale factor for this page. If None, uses instance default.

        Yields:
            A Playwright Page object.

        Note:
            The page and its context are automatically closed when exiting the context.
            Uses a semaphore to limit concurrent conversions and prevent memory leaks.
        """
        if not self._browser:
            raise RuntimeError("Chromium browser is not started")

        # Acquire semaphore to limit concurrent conversions
        async with self._semaphore:
            context: BrowserContext | None = None
            page: Page | None = None

            # Use provided scale factor or fall back to instance default
            scale_factor = device_scale_factor if device_scale_factor is not None else self.device_scale_factor

            try:
                # Create new context with device scale factor
                context = await self._browser.new_context(
                    device_scale_factor=scale_factor,
                    viewport=ViewportSize(width=800, height=600),  # Default, will be overridden
                )

                page = await context.new_page()
                yield page

            finally:
                # Clean up: close page and context to prevent memory leaks
                try:
                    if page:
                        await page.close()
                except Exception as e:  # noqa: BLE001
                    self.log.warning("Error closing page: %s", e)

                try:
                    if context:
                        await context.close()
                except Exception as e:  # noqa: BLE001
                    self.log.warning("Error closing context: %s", e)

    @staticmethod
    def _parse_float(value: str | None, default: float) -> float:
        """Parse a string to float with a default fallback."""
        try:
            return float(value) if value is not None else default
        except ValueError:
            return default


# Global singleton instance
_chromium_manager: ChromiumManager | None = None


def get_chromium_manager() -> ChromiumManager:
    """
    Get the global ChromiumManager singleton instance.

    Returns:
        The ChromiumManager instance.

    Note:
        This is intended for dependency injection in FastAPI endpoints.
    """
    global _chromium_manager  # noqa: PLW0603
    if _chromium_manager is None:
        _chromium_manager = ChromiumManager()
    return _chromium_manager
