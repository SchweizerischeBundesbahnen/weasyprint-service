"""
Chromium browser management via Chrome DevTools Protocol (CDP).

This module provides a singleton ChromiumManager that maintains a persistent
Chromium browser process for fast SVG to PNG conversion, avoiding the overhead
of starting a new browser process for each conversion.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import psutil
from playwright.async_api import ViewportSize, async_playwright

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser, BrowserContext, Page, Playwright


@dataclass
class ChromiumConfig:
    """
    Configuration settings for ChromiumManager.

    Groups all configuration parameters into a single dataclass to improve
    maintainability and reduce constructor parameter count.

    Attributes:
        device_scale_factor: Device scale factor for rendering (1.0-10.0, default 1.0).
        max_concurrent_conversions: Maximum concurrent SVG conversions (1-100, default 10).
        restart_after_n_conversions: Restart Chromium after N conversions (0-10000, default 0 = disabled).
        max_conversion_retries: Maximum retry attempts on conversion failure (1-10, default 2).
        conversion_timeout: Timeout in seconds for each conversion (5-300, default 30).
        health_check_interval: Interval in seconds for background health checks (10-300, default 30).
        health_check_enabled: Enable background health monitoring (default True).
    """

    device_scale_factor: float | None = None
    max_concurrent_conversions: int | None = None
    restart_after_n_conversions: int | None = None
    max_conversion_retries: int | None = None
    conversion_timeout: int | None = None
    health_check_interval: int | None = None
    health_check_enabled: bool | None = None


@dataclass
class ChromiumMetrics:
    """
    Metrics for Chromium browser health and performance monitoring.

    Attributes:
        total_conversions: Total number of successful HTML to PDF conversions since start.
        failed_conversions: Total number of failed HTML to PDF conversions since start.
        total_svg_conversions: Total number of successful SVG to PNG conversions since start.
        failed_svg_conversions: Total number of failed SVG to PNG conversions since start.
        total_chromium_restarts: Total number of browser restarts since start.
        last_health_check: Timestamp of last health check.
        last_health_status: Result of last health check (True=healthy, False=unhealthy).
        consecutive_failures: Number of consecutive conversion failures.
        uptime_seconds: Time since browser was started (in seconds).
        avg_conversion_time_ms: Average HTML to PDF conversion time in milliseconds.
        total_conversion_time_ms: Total time spent on HTML to PDF conversions (for averaging).
        avg_svg_conversion_time_ms: Average SVG to PNG conversion time in milliseconds.
        total_svg_conversion_time_ms: Total time spent on SVG conversions (for averaging).
        current_cpu_percent: Current CPU usage percentage.
        avg_cpu_percent: Average CPU usage percentage.
        current_chromium_memory_mb: Current Chromium physical memory usage in MB.
        avg_chromium_memory_mb: Average Chromium physical memory usage in MB.
        total_cpu_samples: Total CPU samples collected (for averaging).
        total_cpu_sum: Total CPU sum (for averaging).
        total_memory_samples: Total memory samples collected (for averaging).
        total_memory_sum: Total memory sum in MB (for averaging).
        queue_size: Current number of requests in queue (waiting for semaphore).
        max_queue_size: Maximum queue size observed.
        active_conversions: Current number of active conversions.
        total_queue_time_ms: Total time requests spent waiting in queue (for averaging).
        avg_queue_time_ms: Average time requests wait in queue.
    """

    # HTML to PDF conversion metrics
    total_conversions: int = 0
    failed_conversions: int = 0
    avg_conversion_time_ms: float = 0.0
    total_conversion_time_ms: float = 0.0

    # SVG to PNG conversion metrics
    total_svg_conversions: int = 0
    failed_svg_conversions: int = 0
    avg_svg_conversion_time_ms: float = 0.0
    total_svg_conversion_time_ms: float = 0.0

    # Browser health metrics
    total_chromium_restarts: int = 0
    last_health_check: float = 0.0
    last_health_status: bool = False
    consecutive_failures: int = 0
    uptime_seconds: float = 0.0
    start_time: float = field(default_factory=time.time)

    # Resource usage metrics
    current_cpu_percent: float = 0.0
    avg_cpu_percent: float = 0.0
    current_chromium_memory_mb: float = 0.0
    avg_chromium_memory_mb: float = 0.0
    total_cpu_samples: int = 0
    total_cpu_sum: float = 0.0
    total_memory_samples: int = 0
    total_memory_sum: float = 0.0

    # Queue metrics
    queue_size: int = 0
    max_queue_size: int = 0
    active_conversions: int = 0
    total_queue_time_ms: float = 0.0
    avg_queue_time_ms: float = 0.0

    def record_success(self, duration_ms: float) -> None:
        """Record a successful HTML to PDF conversion."""
        self.total_conversions += 1
        self.consecutive_failures = 0
        self.total_conversion_time_ms += duration_ms
        if self.total_conversions > 0:
            self.avg_conversion_time_ms = self.total_conversion_time_ms / self.total_conversions

    def record_svg_success(self, duration_ms: float) -> None:
        """Record a successful SVG to PNG conversion."""
        self.total_svg_conversions += 1
        self.consecutive_failures = 0
        self.total_svg_conversion_time_ms += duration_ms
        if self.total_svg_conversions > 0:
            self.avg_svg_conversion_time_ms = self.total_svg_conversion_time_ms / self.total_svg_conversions

    def record_failure(self) -> None:
        """Record a failed HTML to PDF conversion."""
        self.failed_conversions += 1
        self.consecutive_failures += 1

    def record_svg_failure(self) -> None:
        """Record a failed SVG to PNG conversion."""
        self.failed_svg_conversions += 1
        self.consecutive_failures += 1

    def record_restart(self) -> None:
        """Record a browser restart."""
        self.total_chromium_restarts += 1

    def record_health_check(self, is_healthy: bool) -> None:
        """Record a health check result."""
        self.last_health_check = time.time()
        self.last_health_status = is_healthy

    def update_uptime(self) -> None:
        """Update uptime calculation."""
        self.uptime_seconds = time.time() - self.start_time

    def reset_start_time(self) -> None:
        """Reset start time (used after restart)."""
        self.start_time = time.time()
        self.uptime_seconds = 0.0

    def get_error_rate(self) -> float:
        """Calculate error rate as percentage (considers both HTML->PDF and SVG->PNG conversions)."""
        total_successful = self.total_conversions + self.total_svg_conversions
        total_failed = self.failed_conversions + self.failed_svg_conversions
        total_attempts = total_successful + total_failed
        if total_attempts == 0:
            return 0.0
        return (total_failed / total_attempts) * 100.0

    def record_resource_usage(self, browser_process: psutil.Process | None) -> None:
        """
        Record CPU and memory usage for the browser process.

        Args:
            browser_process: psutil.Process object for the browser, or None if not available.
        """
        if browser_process is None:
            return

        try:
            # Get CPU and memory usage
            # cpu_percent() returns percentage since last call (or since process start if first call)
            # For accurate measurement, we need to call it with interval or multiple times
            cpu_percent = browser_process.cpu_percent()
            memory_info = browser_process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)  # Convert bytes to MB

            # Update current values
            self.current_cpu_percent = cpu_percent
            self.current_chromium_memory_mb = memory_mb

            # Update averages
            self.total_cpu_samples += 1
            self.total_cpu_sum += cpu_percent
            self.avg_cpu_percent = self.total_cpu_sum / self.total_cpu_samples

            self.total_memory_samples += 1
            self.total_memory_sum += memory_mb
            self.avg_chromium_memory_mb = self.total_memory_sum / self.total_memory_samples

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process no longer exists or we don't have access
            pass

    def record_queue_entry(self, queue_time_ms: float) -> None:
        """
        Record metrics when a request enters the queue.

        Args:
            queue_time_ms: Time spent waiting in queue in milliseconds.
        """
        self.total_queue_time_ms += queue_time_ms
        total_processed = self.total_conversions + self.total_svg_conversions
        if total_processed > 0:
            self.avg_queue_time_ms = self.total_queue_time_ms / total_processed

    def update_queue_metrics(self, queue_size: int, active_conversions: int) -> None:
        """
        Update current queue metrics.

        Args:
            queue_size: Current number of requests waiting in queue.
            active_conversions: Current number of active conversions.
        """
        self.queue_size = queue_size
        self.active_conversions = active_conversions
        self.max_queue_size = max(self.max_queue_size, queue_size)


class ChromiumManager:
    """
    Singleton manager for a persistent Chromium browser process.

    Manages the lifecycle of a headless Chromium instance for converting
    SVG images to PNG using Chrome DevTools Protocol via Playwright.
    """

    def __init__(
        self,
        config: ChromiumConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize ChromiumManager.

        Args:
            config: Configuration settings. If None, creates default config from environment variables.
            logger: Optional logger; if None, a module-level logger is used.

        Raises:
            ValueError: If any configuration parameter is out of valid range.
        """
        self.log = logger or logging.getLogger(__name__)

        # Use provided config or create default
        if config is None:
            config = ChromiumConfig()

        # Parse and validate all configuration parameters
        self.device_scale_factor = self._validate_device_scale_factor(config.device_scale_factor)
        self.max_concurrent_conversions = self._validate_max_concurrent_conversions(config.max_concurrent_conversions)
        self.restart_after_n_conversions = self._validate_restart_after_n_conversions(config.restart_after_n_conversions)
        self.max_conversion_retries = self._validate_max_conversion_retries(config.max_conversion_retries)
        self.conversion_timeout = self._validate_conversion_timeout(config.conversion_timeout)
        self.health_check_interval = self._validate_health_check_interval(config.health_check_interval)
        self.health_check_enabled = self._validate_health_check_enabled(config.health_check_enabled)

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_process: psutil.Process | None = None
        self._lock = asyncio.Lock()
        self._counter_lock = asyncio.Lock()  # Separate lock for conversion counter
        self._semaphore = asyncio.Semaphore(self.max_concurrent_conversions)
        self._started = False
        self._conversion_count = 0

        # Metrics and health monitoring
        self._metrics = ChromiumMetrics()
        self._health_monitor_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        # Track waiting and active conversions
        self._waiting_in_queue = 0  # Requests waiting to acquire semaphore
        self._active_conversions = 0  # Requests that acquired semaphore
        self._queue_lock = asyncio.Lock()  # Lock for both counters

    async def start(self) -> None:
        """Start the persistent Chromium browser process."""
        async with self._lock:
            await self._start_internal()

    async def _start_internal(self) -> None:
        """Internal start logic without lock acquisition (for use in restart())."""
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
            self._metrics.reset_start_time()

            # Get browser process for resource monitoring
            try:
                # Get browser process PID from Playwright
                # Note: Playwright doesn't expose PID directly, so we need to find it
                # The browser process is the parent of CDP websocket connections
                if self._browser:
                    # Try to get process info from browser service workers
                    # This is a workaround since Playwright doesn't expose PID
                    # We'll use pgrep to find the chromium process asynchronously
                    process = await asyncio.create_subprocess_exec(
                        "pgrep",
                        "-f",
                        "chrome.*--headless",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, _ = await process.communicate()

                    if process.returncode == 0 and stdout.strip():
                        # Get the first (oldest) chromium process PID
                        pids = [int(pid) for pid in stdout.decode().strip().split("\n")]
                        if pids:
                            self._browser_process = psutil.Process(pids[0])
                            self.log.debug("Found Chromium process PID: %d", pids[0])
            except Exception as e:  # noqa: BLE001
                self.log.warning("Could not attach to Chromium process for resource monitoring: %s", e)
                self._browser_process = None

            self.log.info("Chromium browser started successfully")

            # Start background health monitoring if enabled
            if self.health_check_enabled and self._health_monitor_task is None:
                self._shutdown_event.clear()
                self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())
                self.log.info("Background health monitoring started (interval: %ds)", self.health_check_interval)

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
            await self._stop_internal()

    async def _stop_internal(self) -> None:
        """Internal stop logic without lock acquisition (for use in restart())."""
        if not self._started:
            return

        try:
            # Stop health monitoring first
            if self._health_monitor_task is not None:
                self.log.info("Stopping background health monitoring...")
                self._shutdown_event.set()
                try:
                    await asyncio.wait_for(self._health_monitor_task, timeout=5.0)
                except TimeoutError:
                    self.log.warning("Health monitor task did not stop within timeout, cancelling...")
                    self._health_monitor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._health_monitor_task
                except Exception as e:  # noqa: BLE001
                    self.log.error("Error stopping health monitor: %s", e)
                finally:
                    self._health_monitor_task = None
                    self.log.info("Background health monitoring stopped")

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
            self._browser_process = None

    def is_running(self) -> bool:
        """Check if the Chromium browser is running."""
        return self._started and self._browser is not None

    def health_check(self) -> bool:
        """
        Perform a health check on the Chromium browser.

        Returns:
            True if the browser is healthy, False otherwise.
        """
        try:
            # Check if browser is running and connection is active
            is_healthy = self.is_running() and self._browser is not None and self._browser.is_connected()
            self._metrics.record_health_check(is_healthy)
            return is_healthy
        except Exception as e:  # noqa: BLE001
            self.log.error("Health check failed: %s", e)
            self._metrics.record_health_check(False)
            return False

    def get_version(self) -> str | None:
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
        """
        Restart the Chromium browser (useful for recovering from errors).

        This method ensures thread-safety by:
        1. Using _lock to serialize restarts (prevent multiple concurrent restarts)
        2. Acquiring all semaphore permits to wait for active conversions to finish
        3. Blocking new conversions from starting during restart
        4. Safely stopping and restarting the browser
        5. Releasing all permits to allow new conversions
        """
        self.log.info("Restarting Chromium browser...")

        # Use _lock to ensure only one restart at a time (prevents concurrent restarts from deadlocking)
        async with self._lock:
            # Acquire all semaphore permits to wait for active conversions to complete
            # and prevent new conversions from starting during restart
            permits_acquired = []
            try:
                for _ in range(self.max_concurrent_conversions):
                    await self._semaphore.acquire()
                    permits_acquired.append(True)

                # Now that all active conversions are done and new ones are blocked,
                # safely restart the browser using internal methods (to avoid re-acquiring _lock)
                await self._stop_internal()
                await self._start_internal()

                # Record restart in metrics
                self._metrics.record_restart()

            finally:
                # Always release all acquired permits, even if restart fails
                for _ in permits_acquired:
                    self._semaphore.release()

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
            RuntimeError: If Chromium is not started or conversion fails after retry attempts.
        """
        if not self.is_running():
            raise RuntimeError("Chromium not started. Call start() first.")

        # Atomically increment counter and check if restart is needed
        # IMPORTANT: Restart must happen OUTSIDE the lock to avoid blocking other conversions
        should_restart = False
        conversions_before_restart = 0
        async with self._counter_lock:
            self._conversion_count += 1
            # Check if restart is needed (after incrementing counter)
            if 0 < self.restart_after_n_conversions <= self._conversion_count:
                should_restart = True
                conversions_before_restart = self._conversion_count
                # Reset counter immediately inside lock to prevent other threads from also triggering restart
                self._conversion_count = 0

        # Perform restart OUTSIDE the counter lock to avoid blocking other conversions
        if should_restart:
            self.log.info(
                "Conversion count (%d) reached threshold (%d), restarting Chromium...",
                conversions_before_restart,
                self.restart_after_n_conversions,
            )
            await self.restart()
            self.log.info("Chromium restarted successfully after %d conversions", conversions_before_restart)

        # Try conversion with automatic recovery on failure
        last_error: Exception | None = None
        start_time = time.time()

        for attempt in range(self.max_conversion_retries):
            try:
                # Apply timeout to prevent hanging conversions
                result = await asyncio.wait_for(
                    self._perform_conversion(svg_content, width, height, device_scale_factor),
                    timeout=self.conversion_timeout,
                )
                # Record SVG success metrics
                duration_ms = (time.time() - start_time) * 1000
                self._metrics.record_svg_success(duration_ms)
                return result
            except TimeoutError:
                last_error = TimeoutError(f"Conversion timed out after {self.conversion_timeout} seconds")
                self.log.error("SVG conversion timed out (attempt %d/%d): %d seconds", attempt + 1, self.max_conversion_retries, self.conversion_timeout)
                await self._handle_conversion_retry(attempt, last_error, "timeout")
            except Exception as e:
                last_error = e
                self.log.warning(
                    "SVG conversion failed (attempt %d/%d): %s. Attempting to restart Chromium...",
                    attempt + 1,
                    self.max_conversion_retries,
                    str(e),
                )
                await self._handle_conversion_retry(attempt, e, "conversion error")

        # If we get here, all retries failed
        self._metrics.record_svg_failure()
        self.log.error("SVG conversion failed after %d attempts: %s", self.max_conversion_retries, str(last_error))
        raise RuntimeError(f"SVG to PNG conversion failed after {self.max_conversion_retries} attempts") from last_error

    async def _handle_conversion_retry(self, attempt: int, error: Exception, error_type: str) -> None:
        """
        Handle retry logic after a conversion failure.

        Args:
            attempt: Current attempt number (0-based).
            error: The exception that caused the failure.
            error_type: Description of the error type (for logging).

        Raises:
            RuntimeError: If this is not the last attempt and restart fails.
        """
        is_last_attempt = attempt >= self.max_conversion_retries - 1
        if is_last_attempt:
            return  # Don't restart on last attempt, let caller handle final error

        try:
            await self.restart()
            self.log.info("Chromium restarted successfully after %s", error_type)
        except Exception as restart_error:
            self.log.error("Failed to restart Chromium: %s", restart_error)
            raise RuntimeError(f"Chromium restart failed after {error_type}: {restart_error}") from error

    async def _perform_conversion(self, svg_content: str, width: int, height: int, device_scale_factor: float | None = None) -> bytes:
        """
        Perform the actual SVG to PNG conversion.

        This method is separated to allow retry logic in convert_svg_to_png().
        """
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

    async def _cleanup_page_resources(self, page: Page | None, context: BrowserContext | None, is_cancelled: bool = False) -> None:
        """
        Clean up page and context resources.

        Args:
            page: The page to close (or None if not created).
            context: The context to close (or None if not created).
            is_cancelled: Whether cleanup is happening due to cancellation.
        """
        error_prefix = "during cancellation" if is_cancelled else ""

        if page is not None:
            try:
                await page.close()
            except Exception as e:  # noqa: BLE001
                self.log.warning("Error closing page %s: %s", error_prefix, e)

        if context is not None:
            try:
                await context.close()
            except Exception as e:  # noqa: BLE001
                self.log.warning("Error closing context %s: %s", error_prefix, e)

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
            Handles cancellation (e.g., from timeout) gracefully to ensure semaphore is always released.
        """
        if not self._browser:
            raise RuntimeError("Chromium browser is not started")

        # Track queue entry time
        queue_entry_time = time.time()

        # Mark as waiting in queue (before trying to acquire semaphore)
        async with self._queue_lock:
            self._waiting_in_queue += 1
            self._metrics.update_queue_metrics(self._waiting_in_queue, self._active_conversions)

        try:
            # Acquire semaphore to limit concurrent conversions
            async with self._semaphore:
                # Record time spent waiting in queue
                queue_time_ms = (time.time() - queue_entry_time) * 1000
                self._metrics.record_queue_entry(queue_time_ms)

                # Now we have the semaphore - move from waiting to active
                async with self._queue_lock:
                    self._waiting_in_queue -= 1
                    self._active_conversions += 1
                    self._metrics.update_queue_metrics(self._waiting_in_queue, self._active_conversions)

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

                except asyncio.CancelledError:
                    # Handle cancellation (e.g., from timeout in wait_for)
                    # Explicitly clean up resources before re-raising
                    self.log.warning("Conversion cancelled (timeout or external cancellation), cleaning up page and context")
                    await self._cleanup_page_resources(page, context, is_cancelled=True)
                    # Mark as cleaned up to prevent duplicate close in finally
                    page = None
                    context = None
                    # Re-raise CancelledError to propagate cancellation
                    raise

                finally:
                    # Decrement active conversions counter and update metrics
                    async with self._queue_lock:
                        self._active_conversions -= 1
                        self._metrics.update_queue_metrics(self._waiting_in_queue, self._active_conversions)

                    # Clean up: close page and context to prevent memory leaks (for normal exit path)
                    # Note: If CancelledError was caught above, these will be None and skip cleanup
                    await self._cleanup_page_resources(page, context, is_cancelled=False)

        except asyncio.CancelledError:
            # If cancelled while waiting for semaphore, decrement waiting counter
            async with self._queue_lock:
                self._waiting_in_queue -= 1
            raise
        except Exception:
            # If error while waiting for semaphore, decrement waiting counter
            async with self._queue_lock:
                self._waiting_in_queue -= 1
            raise

    async def _health_monitor_loop(self) -> None:
        """
        Background task that periodically checks Chromium health.

        This runs in the background while the browser is running and:
        - Performs periodic health checks
        - Updates metrics (uptime, etc.)
        - Automatically restarts browser if health degrades

        The loop exits when _shutdown_event is set.
        """
        self.log.info("Health monitor loop started")
        consecutive_failures = 0
        max_consecutive_failures = 3

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for interval or shutdown signal
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.health_check_interval,
                    )
                    # If we get here, shutdown was signaled
                    break
                except TimeoutError:
                    # Timeout is expected - time to perform health check
                    pass

                # Update metrics
                self._metrics.update_uptime()

                # Record resource usage (CPU and memory)
                self._metrics.record_resource_usage(self._browser_process)

                # Perform health check
                is_healthy = self.health_check()

                if is_healthy:
                    consecutive_failures = 0
                    self.log.debug("Health check passed (uptime: %.1fs, conversions: %d, errors: %d)", self._metrics.uptime_seconds, self._metrics.total_conversions, self._metrics.failed_conversions)
                else:
                    consecutive_failures += 1
                    self.log.warning("Health check failed (%d/%d consecutive failures)", consecutive_failures, max_consecutive_failures)

                    # Auto-restart if consecutive failures exceed threshold
                    if consecutive_failures >= max_consecutive_failures:
                        self.log.error("Chromium health degraded after %d consecutive failures, restarting...", consecutive_failures)
                        try:
                            await self.restart()
                            consecutive_failures = 0
                            self.log.info("Chromium restarted successfully after health check failure")
                        except Exception as e:
                            self.log.error("Failed to restart Chromium after health check failure: %s", e)
                            # Continue monitoring even if restart fails

        except asyncio.CancelledError:
            self.log.info("Health monitor loop cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            self.log.error("Unexpected error in health monitor loop: %s", e)
        finally:
            self.log.info("Health monitor loop stopped")

    def get_metrics(self) -> dict[str, float | int | bool | str]:
        """
        Get current metrics for monitoring and observability.

        Returns:
            Dictionary containing current metrics:
            - total_conversions: Total successful HTML to PDF conversions
            - failed_conversions: Total failed HTML to PDF conversions
            - total_svg_conversions: Total successful SVG to PNG conversions
            - failed_svg_conversions: Total failed SVG to PNG conversions
            - error_rate_percent: Overall conversion error rate as percentage (includes both HTML->PDF and SVG->PNG)
            - total_chromium_restarts: Total browser restarts
            - avg_conversion_time_ms: Average HTML to PDF conversion time
            - avg_svg_conversion_time_ms: Average SVG to PNG conversion time
            - last_health_check: Formatted timestamp of last health check
            - last_health_status: Result of last health check
            - consecutive_failures: Current consecutive failures count
            - uptime_seconds: Browser uptime in seconds
            - current_cpu_percent: Current CPU usage percentage
            - avg_cpu_percent: Average CPU usage percentage
            - total_memory_mb: Total system memory in MB
            - available_memory_mb: Available system memory in MB
            - current_chromium_memory_mb: Current Chromium physical memory usage in MB
            - avg_chromium_memory_mb: Average Chromium physical memory usage in MB
            - queue_size: Current number of requests in queue
            - max_queue_size: Maximum queue size observed
            - active_conversions: Current number of active conversions
            - avg_queue_time_ms: Average time requests wait in queue
            - max_concurrent_conversions: Maximum allowed concurrent conversions
        """
        self._metrics.update_uptime()

        # Get system memory info
        system_memory = psutil.virtual_memory()
        total_memory_mb = system_memory.total / (1024 * 1024)
        available_memory_mb = system_memory.available / (1024 * 1024)

        # Format last_health_check as readable timestamp
        last_health_check_str = ""
        if self._metrics.last_health_check > 0:
            dt = datetime.fromtimestamp(self._metrics.last_health_check)
            last_health_check_str = dt.strftime("%H:%M:%S %d.%m.%Y")

        return {
            "total_conversions": self._metrics.total_conversions,
            "failed_conversions": self._metrics.failed_conversions,
            "total_svg_conversions": self._metrics.total_svg_conversions,
            "failed_svg_conversions": self._metrics.failed_svg_conversions,
            "error_rate_percent": round(self._metrics.get_error_rate(), 2),
            "total_chromium_restarts": self._metrics.total_chromium_restarts,
            "avg_conversion_time_ms": round(self._metrics.avg_conversion_time_ms, 2),
            "avg_svg_conversion_time_ms": round(self._metrics.avg_svg_conversion_time_ms, 2),
            "last_health_check": last_health_check_str,
            "last_health_status": self._metrics.last_health_status,
            "consecutive_failures": self._metrics.consecutive_failures,
            "uptime_seconds": round(self._metrics.uptime_seconds, 2),
            "current_cpu_percent": round(self._metrics.current_cpu_percent, 2),
            "avg_cpu_percent": round(self._metrics.avg_cpu_percent, 2),
            "total_memory_mb": round(total_memory_mb, 2),
            "available_memory_mb": round(available_memory_mb, 2),
            "current_chromium_memory_mb": round(self._metrics.current_chromium_memory_mb, 2),
            "avg_chromium_memory_mb": round(self._metrics.avg_chromium_memory_mb, 2),
            "queue_size": self._metrics.queue_size,
            "max_queue_size": self._metrics.max_queue_size,
            "active_conversions": self._metrics.active_conversions,
            "avg_queue_time_ms": round(self._metrics.avg_queue_time_ms, 2),
            "max_concurrent_conversions": self.max_concurrent_conversions,
        }

    def _validate_int_config(
        self,
        value: int | None,
        env_var: str,
        default: int,
        min_value: int,
        max_value: int,
    ) -> int:
        """
        Validate integer configuration parameters.

        Args:
            value: Value to validate or None to read from env.
            env_var: Environment variable name.
            default: Default value if env var not set or invalid.
            min_value: Minimum valid value (inclusive).
            max_value: Maximum valid value (inclusive).

        Returns:
            Validated integer configuration value.
        """
        # Parse value from environment variable or use provided value
        if value is None:
            env_value = os.environ.get(env_var)
            value = self._parse_int(env_value, default)
        else:
            value = int(value)

        # Check bounds
        if not (min_value <= value <= max_value):
            self.log.warning("%s must be between %s and %s, using default: %s", env_var, min_value, max_value, default)
            return default

        return value

    def _validate_float_config(
        self,
        value: float | None,
        env_var: str,
        default: float,
        min_value: float,
        max_value: float,
    ) -> float:
        """
        Validate float configuration parameters.

        Args:
            value: Value to validate or None to read from env.
            env_var: Environment variable name.
            default: Default value if env var not set or invalid.
            min_value: Minimum valid value (inclusive).
            max_value: Maximum valid value (inclusive).

        Returns:
            Validated float configuration value.
        """
        # Parse value from environment variable or use provided value
        if value is None:
            env_value = os.environ.get(env_var)
            value = self._parse_float(env_value, default)
        else:
            value = float(value)

        # Check bounds
        if not (min_value <= value <= max_value):
            self.log.warning("%s must be between %s and %s, using default: %s", env_var, min_value, max_value, default)
            return default

        return value

    def _validate_device_scale_factor(self, value: float | None) -> float:
        """
        Validate device scale factor.

        Args:
            value: Device scale factor or None to read from env.

        Returns:
            Validated device scale factor (1.0 - 10.0).
        """
        return self._validate_float_config(
            value=value,
            env_var="DEVICE_SCALE_FACTOR",
            default=1.0,
            min_value=1.0,
            max_value=10.0,
        )

    def _validate_max_concurrent_conversions(self, value: int | None) -> int:
        """
        Validate max concurrent conversions.

        Args:
            value: Max concurrent conversions or None to read from env.

        Returns:
            Validated max concurrent conversions (1 - 100).
        """
        return self._validate_int_config(
            value=value,
            env_var="MAX_CONCURRENT_CONVERSIONS",
            default=10,
            min_value=1,
            max_value=100,
        )

    def _validate_restart_after_n_conversions(self, value: int | None) -> int:
        """
        Validate restart after N conversions threshold.

        Args:
            value: Restart threshold or None to read from env.

        Returns:
            Validated restart threshold (0 - 10000).
        """
        return self._validate_int_config(
            value=value,
            env_var="CHROMIUM_RESTART_AFTER_N_CONVERSIONS",
            default=0,
            min_value=0,
            max_value=10000,
        )

    def _validate_max_conversion_retries(self, value: int | None) -> int:
        """
        Validate max conversion retry attempts.

        Args:
            value: Max retry attempts or None to read from env.

        Returns:
            Validated max retry attempts (1 - 10).
        """
        return self._validate_int_config(
            value=value,
            env_var="CHROMIUM_MAX_CONVERSION_RETRIES",
            default=2,
            min_value=1,
            max_value=10,
        )

    def _validate_conversion_timeout(self, value: int | None) -> int:
        """
        Validate conversion timeout.

        Args:
            value: Timeout in seconds or None to read from env.

        Returns:
            Validated timeout in seconds (5 - 300).
        """
        return self._validate_int_config(
            value=value,
            env_var="CHROMIUM_CONVERSION_TIMEOUT",
            default=30,
            min_value=5,
            max_value=300,
        )

    def _validate_health_check_interval(self, value: int | None) -> int:
        """
        Validate health check interval.

        Args:
            value: Interval in seconds or None to read from env.

        Returns:
            Validated interval in seconds (10 - 300).
        """
        return self._validate_int_config(
            value=value,
            env_var="CHROMIUM_HEALTH_CHECK_INTERVAL",
            default=30,
            min_value=10,
            max_value=300,
        )

    def _validate_health_check_enabled(self, value: bool | None) -> bool:
        """
        Validate health check enabled flag.

        Args:
            value: Enable flag or None to read from env.

        Returns:
            Validated enable flag (default True).
        """
        if value is not None:
            return bool(value)

        env_value = os.environ.get("CHROMIUM_HEALTH_CHECK_ENABLED")
        if env_value is None:
            return True  # Default to enabled

        # Parse boolean from string (case-insensitive)
        return env_value.lower() in ("true", "1", "yes", "on")

    @staticmethod
    def _parse_float(value: str | None, default: float) -> float:
        """Parse a string to float with a default fallback."""
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_int(value: str | None, default: int) -> int:
        """Parse a string to int with a default fallback."""
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
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
