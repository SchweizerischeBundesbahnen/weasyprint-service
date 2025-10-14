"""Tests for ChromiumManager CDP-based SVG conversion."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.chromium_manager import ChromiumConfig, ChromiumManager, get_chromium_manager
from app.html_parser import HtmlParser
from app.svg_processor import SvgProcessor


@pytest.mark.asyncio
async def test_chromium_manager_lifecycle():
    """Test ChromiumManager startup and shutdown lifecycle."""
    manager = ChromiumManager()

    # Should not be running initially
    assert not manager.is_running()

    # Start the browser
    await manager.start()
    assert manager.is_running()

    # Health check should pass
    assert manager.health_check()

    # Stop the browser
    await manager.stop()
    assert not manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_double_start():
    """Test that calling start twice doesn't cause issues."""
    manager = ChromiumManager()

    await manager.start()
    assert manager.is_running()

    # Second start should log warning but not fail
    await manager.start()
    assert manager.is_running()

    await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_convert_svg_basic():
    """Test basic SVG to PNG conversion via CDP."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'

        png_bytes = await manager.convert_svg_to_png(svg_content, 100, 100)

        # Verify PNG signature
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        # PNG should have reasonable size
        assert len(png_bytes) > 100

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_convert_svg_not_started():
    """Test that conversion fails if browser is not started."""
    manager = ChromiumManager()

    svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'

    with pytest.raises(RuntimeError, match="Chromium not started"):
        await manager.convert_svg_to_png(svg_content, 100, 100)


@pytest.mark.asyncio
async def test_chromium_manager_device_scale_factor():
    """Test that device scale factor is respected."""
    manager = ChromiumManager(config=ChromiumConfig(device_scale_factor=2.0))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="blue"/></svg>'

        # Convert with 2x scale factor
        png_bytes = await manager.convert_svg_to_png(svg_content, 100, 100)

        # PNG should be larger with higher scale factor
        assert len(png_bytes) > 100

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_health_check_not_running():
    """Test health check when browser is not running."""
    manager = ChromiumManager()

    # Health check should fail when not running
    assert not manager.health_check()


@pytest.mark.asyncio
async def test_chromium_manager_restart():
    """Test browser restart functionality."""
    manager = ChromiumManager()

    await manager.start()
    assert manager.is_running()

    await manager.restart()
    assert manager.is_running()

    # Should still be able to convert after restart
    svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'
    png_bytes = await manager.convert_svg_to_png(svg_content, 50, 50)
    assert png_bytes.startswith(b"\x89PNG")

    await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_get_version():
    """Test getting Chromium version."""
    manager = ChromiumManager()

    # Version should be None when not running
    version = manager.get_version()
    assert version is None

    # Start browser
    await manager.start()

    # Version should be a string when running
    version = manager.get_version()
    assert isinstance(version, str)
    assert len(version) > 0
    # Version format: major.minor.build.patch (e.g., "131.0.6778.69")
    assert "." in version

    await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_concurrent_conversions():
    """Test that concurrent SVG conversions work correctly."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="green"/></svg>'

        # Convert multiple SVGs concurrently
        tasks = [manager.convert_svg_to_png(svg_content, 100, 100) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All conversions should succeed
        assert len(results) == 5
        for png_bytes in results:
            assert png_bytes.startswith(b"\x89PNG")

    finally:
        await manager.stop()


def test_get_chromium_manager_singleton():
    """Test that get_chromium_manager returns a singleton."""
    manager1 = get_chromium_manager()
    manager2 = get_chromium_manager()

    # Should be the same instance
    assert manager1 is manager2


# Integration tests with SvgProcessor


@pytest.mark.asyncio
async def test_svg_processor_with_chromium_manager():
    """Test SvgProcessor integration with ChromiumManager."""
    chromium_manager = ChromiumManager()
    await chromium_manager.start()

    try:
        html_parser = HtmlParser()
        svg_processor = SvgProcessor(chromium_manager=chromium_manager)

        # Test inline SVG conversion
        html = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'
        parsed_html = html_parser.parse(html)
        result_html = await svg_processor.process_svg(parsed_html)
        result = html_parser.serialize(result_html)

        # Should convert to PNG
        assert "image/png" in result
        assert "base64" in result

    finally:
        await chromium_manager.stop()


@pytest.mark.asyncio
async def test_svg_processor_multiple_svgs():
    """Test async processing of multiple SVGs."""
    chromium_manager = ChromiumManager()
    await chromium_manager.start()

    try:
        html_parser = HtmlParser()
        svg_processor = SvgProcessor(chromium_manager=chromium_manager)

        # Multiple inline SVGs
        html = """
            <svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>
            <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>
        """
        parsed_html = html_parser.parse(html)
        result_html = await svg_processor.process_svg(parsed_html)
        result = html_parser.serialize(result_html)

        # Both should convert to PNG
        assert result.count("image/png") == 2

    finally:
        await chromium_manager.stop()


@pytest.mark.asyncio
async def test_svg_processor_without_chromium_manager():
    """Test that SvgProcessor returns original SVG without ChromiumManager."""
    html_parser = HtmlParser()
    svg_processor = SvgProcessor()  # No chromium_manager

    html = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
    parsed_html = html_parser.parse(html)

    # Should still work but return SVG (not PNG)
    result_html = await svg_processor.process_svg(parsed_html)
    result = html_parser.serialize(result_html)

    # Without chromium_manager, should convert to base64 SVG
    assert "image/svg+xml" in result
    assert "base64" in result


@pytest.mark.asyncio
async def test_svg_processor_invalid_inputs():
    """Test async processing with invalid inputs."""
    chromium_manager = ChromiumManager()
    await chromium_manager.start()

    try:
        html_parser = HtmlParser()
        svg_processor = SvgProcessor(chromium_manager=chromium_manager)

        # Invalid base64 should be passed through unchanged
        html = '<img src="data:image/svg+xml;base64,invalid==="/>'
        parsed_html = html_parser.parse(html)
        result_html = await svg_processor.process_svg(parsed_html)
        result = html_parser.serialize(result_html)

        assert result == html

        # Non-SVG images should be passed through unchanged
        html = '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="/>'
        parsed_html = html_parser.parse(html)
        result_html = await svg_processor.process_svg(parsed_html)
        result = html_parser.serialize(result_html)

        assert result == html

    finally:
        await chromium_manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_stop_when_not_running():
    """Test that stopping a non-running browser doesn't cause issues."""
    manager = ChromiumManager()

    # Stop should be safe even if never started
    await manager.stop()
    assert not manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_convert_with_custom_scale_factor():
    """Test SVG conversion with per-conversion scale factor override."""
    manager = ChromiumManager(config=ChromiumConfig(device_scale_factor=1.0))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="purple"/></svg>'

        # Convert with custom scale factor (overrides instance default)
        png_bytes = await manager.convert_svg_to_png(svg_content, 100, 100, device_scale_factor=3.0)

        # Verify PNG signature
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png_bytes) > 100

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_parse_float_from_env():
    """Test device_scale_factor parsing from environment variable."""
    # Test valid float from env
    os.environ["DEVICE_SCALE_FACTOR"] = "2.5"
    manager = ChromiumManager()
    assert manager.device_scale_factor == 2.5
    del os.environ["DEVICE_SCALE_FACTOR"]

    # Test invalid float from env (should default to 1.0)
    os.environ["DEVICE_SCALE_FACTOR"] = "invalid"
    manager = ChromiumManager()
    assert manager.device_scale_factor == 1.0
    del os.environ["DEVICE_SCALE_FACTOR"]

    # Test None from env (should default to 1.0)
    if "DEVICE_SCALE_FACTOR" in os.environ:
        del os.environ["DEVICE_SCALE_FACTOR"]
    manager = ChromiumManager()
    assert manager.device_scale_factor == 1.0


@pytest.mark.asyncio
async def test_chromium_manager_get_version_extraction():
    """Test Chromium version string extraction."""
    manager = ChromiumManager()
    await manager.start()

    try:
        version = manager.get_version()
        # Version should be extracted from "HeadlessChrome/131.0.6778.69" format
        assert version is not None
        assert "/" not in version  # Should be extracted, not the full string
        # Should have multiple version components
        parts = version.split(".")
        assert len(parts) >= 3  # At least major.minor.build

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_get_version_without_slash():
    """Test Chromium version when format doesn't contain '/'."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Use PropertyMock to mock the version property
        with patch.object(type(manager._browser), "version", new_callable=PropertyMock) as mock_version:
            mock_version.return_value = "131.0.6778.69"

            version = manager.get_version()
            # Should return the version string as-is when no "/" present
            assert version == "131.0.6778.69"

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_get_page_without_browser():
    """Test _get_page raises RuntimeError when browser is not started."""
    manager = ChromiumManager()

    # Browser is not started, _get_page should raise RuntimeError
    with pytest.raises(RuntimeError, match="Chromium browser is not started"):
        async with manager._get_page():
            pass


@pytest.mark.asyncio
async def test_chromium_manager_get_page_with_custom_scale():
    """Test _get_page with custom device scale factor."""
    manager = ChromiumManager(config=ChromiumConfig(device_scale_factor=1.0))
    await manager.start()

    try:
        # Use custom scale factor per page
        async with manager._get_page(device_scale_factor=2.5) as page:
            assert page is not None

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_start_playwright_import_error():
    """Test handling of ImportError when Playwright is not installed."""
    manager = ChromiumManager()

    with patch("app.chromium_manager.async_playwright") as mock_playwright:
        mock_playwright.side_effect = ImportError("Playwright not installed")

        with pytest.raises(RuntimeError, match="Playwright library is required"):
            await manager.start()

        # Manager should not be marked as started
        assert not manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_start_generic_error():
    """Test handling of generic error during Chromium start."""
    manager = ChromiumManager()

    with patch("app.chromium_manager.async_playwright") as mock_playwright:
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.start = AsyncMock(side_effect=Exception("Generic error"))
        mock_playwright.return_value = mock_playwright_instance

        with pytest.raises(Exception, match="Generic error"):
            await manager.start()

        # Manager should not be marked as started
        assert not manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_stop_with_errors():
    """Test error handling during stop operation."""
    manager = ChromiumManager()
    await manager.start()

    # Mock browser.close to raise an exception
    with patch.object(manager._browser, "close", side_effect=Exception("Browser close error")):
        # Stop should not raise exception, just log it
        await manager.stop()
        # Should still mark as not started
        assert not manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_health_check_with_error():
    """Test health check when browser connection check fails."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Mock is_connected to raise an exception
        with patch.object(manager._browser, "is_connected", side_effect=Exception("Connection check failed")):
            # Health check should return False, not raise exception
            result = manager.health_check()
            assert result is False

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_get_version_with_error():
    """Test get_version when browser raises exception."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Mock browser.version to raise an exception
        with patch.object(type(manager._browser), "version", new_callable=lambda: property(lambda self: (_ for _ in ()).throw(Exception("Version error")))):
            # get_version should return None, not raise exception
            version = manager.get_version()
            assert version is None

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_concurrent_limit():
    """Test that semaphore limits concurrent conversions and prevents resource exhaustion."""
    # Set a low limit to test semaphore behavior
    manager = ChromiumManager(config=ChromiumConfig(max_concurrent_conversions=3))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Run many conversions concurrently - semaphore should limit to 3 at a time
        tasks = [manager.convert_svg_to_png(svg_content, 50, 50) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All conversions should succeed
        assert len(results) == 10
        for png_bytes in results:
            assert png_bytes.startswith(b"\x89PNG")

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_max_concurrent_from_env():
    """Test that MAX_CONCURRENT_CONVERSIONS env var is respected."""
    # Set environment variable
    os.environ["MAX_CONCURRENT_CONVERSIONS"] = "5"
    try:
        manager = ChromiumManager()
        assert manager.max_concurrent_conversions == 5
    finally:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]

    # Test default value
    if "MAX_CONCURRENT_CONVERSIONS" in os.environ:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]
    manager = ChromiumManager()
    assert manager.max_concurrent_conversions == 10


@pytest.mark.asyncio
async def test_chromium_manager_restart_after_n_conversions():
    """Test that Chromium automatically restarts after N conversions."""
    manager = ChromiumManager(config=ChromiumConfig(restart_after_n_conversions=3))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="blue"/></svg>'

        # First conversion: counter increments to 1, no restart
        assert manager._conversion_count == 0
        await manager.convert_svg_to_png(svg_content, 50, 50)
        assert manager._conversion_count == 1

        # Second conversion: counter increments to 2, no restart
        await manager.convert_svg_to_png(svg_content, 50, 50)
        assert manager._conversion_count == 2

        # Third conversion: counter increments to 3, then restart (counter resets to 0)
        await manager.convert_svg_to_png(svg_content, 50, 50)
        assert manager._conversion_count == 0

        # Fourth conversion: counter increments to 1, no restart
        await manager.convert_svg_to_png(svg_content, 50, 50)
        assert manager._conversion_count == 1

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_restart_disabled_by_default():
    """Test that auto-restart is disabled when restart_after_n_conversions is 0."""
    manager = ChromiumManager(config=ChromiumConfig(restart_after_n_conversions=0))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Perform many conversions
        for _i in range(10):
            await manager.convert_svg_to_png(svg_content, 50, 50)

        # Counter should keep incrementing (no restart)
        assert manager._conversion_count == 10

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_restart_from_env():
    """Test that restart_after_n_conversions can be configured via environment variable."""
    os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"] = "2"

    try:
        manager = ChromiumManager()
        assert manager.restart_after_n_conversions == 2

        await manager.start()

        try:
            svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

            # First conversion: counter increments to 1, no restart
            await manager.convert_svg_to_png(svg_content, 50, 50)
            assert manager._conversion_count == 1

            # Second conversion: counter increments to 2, then restart (counter resets to 0)
            await manager.convert_svg_to_png(svg_content, 50, 50)
            assert manager._conversion_count == 0

            # Third conversion: counter increments to 1, no restart
            await manager.convert_svg_to_png(svg_content, 50, 50)
            assert manager._conversion_count == 1

        finally:
            await manager.stop()

    finally:
        # Cleanup
        del os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"]


@pytest.mark.asyncio
async def test_chromium_manager_auto_recovery_on_failure():
    """Test that Chromium automatically restarts and retries on conversion failure."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Mock _perform_conversion to fail once, then succeed
        original_perform = manager._perform_conversion
        call_count = 0

        async def mock_perform_conversion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Simulated Chromium crash")
            return await original_perform(*args, **kwargs)

        manager._perform_conversion = mock_perform_conversion

        # Should succeed after automatic restart
        png_bytes = await manager.convert_svg_to_png(svg_content, 50, 50)
        assert png_bytes.startswith(b"\x89PNG")
        assert call_count == 2  # Failed once, succeeded on retry

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_auto_recovery_fails_after_retries():
    """Test that conversion fails after max retry attempts."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Mock _perform_conversion to always fail
        async def mock_perform_conversion(*args, **kwargs):
            raise Exception("Persistent Chromium failure")

        manager._perform_conversion = mock_perform_conversion

        # Should raise RuntimeError after retries
        with pytest.raises(RuntimeError, match="SVG to PNG conversion failed after 2 attempts"):
            await manager.convert_svg_to_png(svg_content, 50, 50)

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_auto_recovery_restart_failure():
    """Test that conversion fails if restart itself fails."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Mock _perform_conversion to fail
        async def mock_perform_conversion(*args, **kwargs):
            raise Exception("Simulated Chromium crash")

        manager._perform_conversion = mock_perform_conversion

        # Mock restart to fail
        original_restart = manager.restart

        async def mock_restart():
            raise Exception("Restart failed")

        manager.restart = mock_restart

        # Should raise RuntimeError about restart failure
        with pytest.raises(RuntimeError, match="Chromium restart failed after conversion error"):
            await manager.convert_svg_to_png(svg_content, 50, 50)

        # Restore original restart for cleanup
        manager.restart = original_restart

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_max_retries_from_env():
    """Test that CHROMIUM_MAX_CONVERSION_RETRIES env var is respected."""
    os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"] = "5"

    try:
        manager = ChromiumManager()
        assert manager.max_conversion_retries == 5
    finally:
        del os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"]

    # Test default value
    if "CHROMIUM_MAX_CONVERSION_RETRIES" in os.environ:
        del os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"]
    manager = ChromiumManager()
    assert manager.max_conversion_retries == 2


@pytest.mark.asyncio
async def test_chromium_manager_validation_max_concurrent_out_of_range():
    """Test that MAX_CONCURRENT_CONVERSIONS is validated and clamped to valid range."""
    # Test value too low
    os.environ["MAX_CONCURRENT_CONVERSIONS"] = "0"
    try:
        manager = ChromiumManager()
        assert manager.max_concurrent_conversions == 10  # Should fall back to default
    finally:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]

    # Test value too high
    os.environ["MAX_CONCURRENT_CONVERSIONS"] = "200"
    try:
        manager = ChromiumManager()
        assert manager.max_concurrent_conversions == 10  # Should fall back to default
    finally:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]

    # Test valid value at boundary
    os.environ["MAX_CONCURRENT_CONVERSIONS"] = "100"
    try:
        manager = ChromiumManager()
        assert manager.max_concurrent_conversions == 100
    finally:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]


@pytest.mark.asyncio
async def test_chromium_manager_validation_restart_threshold_out_of_range():
    """Test that CHROMIUM_RESTART_AFTER_N_CONVERSIONS is validated."""
    # Test negative value
    os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"] = "-1"
    try:
        manager = ChromiumManager()
        assert manager.restart_after_n_conversions == 0  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"]

    # Test value too high
    os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"] = "20000"
    try:
        manager = ChromiumManager()
        assert manager.restart_after_n_conversions == 0  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_RESTART_AFTER_N_CONVERSIONS"]


@pytest.mark.asyncio
async def test_chromium_manager_validation_max_retries_out_of_range():
    """Test that CHROMIUM_MAX_CONVERSION_RETRIES is validated."""
    # Test value too low
    os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"] = "0"
    try:
        manager = ChromiumManager()
        assert manager.max_conversion_retries == 2  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"]

    # Test value too high
    os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"] = "20"
    try:
        manager = ChromiumManager()
        assert manager.max_conversion_retries == 2  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_MAX_CONVERSION_RETRIES"]


@pytest.mark.asyncio
async def test_chromium_manager_validation_device_scale_out_of_range():
    """Test that DEVICE_SCALE_FACTOR is validated."""
    # Test value too low
    os.environ["DEVICE_SCALE_FACTOR"] = "0"
    try:
        manager = ChromiumManager()
        assert manager.device_scale_factor == 1.0  # Should fall back to default
    finally:
        del os.environ["DEVICE_SCALE_FACTOR"]

    # Test value too high
    os.environ["DEVICE_SCALE_FACTOR"] = "15"
    try:
        manager = ChromiumManager()
        assert manager.device_scale_factor == 1.0  # Should fall back to default
    finally:
        del os.environ["DEVICE_SCALE_FACTOR"]


@pytest.mark.asyncio
async def test_chromium_manager_validation_invalid_string_values():
    """Test that invalid string values fall back to defaults."""
    # Test non-numeric MAX_CONCURRENT_CONVERSIONS
    os.environ["MAX_CONCURRENT_CONVERSIONS"] = "invalid"
    try:
        manager = ChromiumManager()
        assert manager.max_concurrent_conversions == 10
    finally:
        del os.environ["MAX_CONCURRENT_CONVERSIONS"]

    # Test non-numeric DEVICE_SCALE_FACTOR
    os.environ["DEVICE_SCALE_FACTOR"] = "abc"
    try:
        manager = ChromiumManager()
        assert manager.device_scale_factor == 1.0
    finally:
        del os.environ["DEVICE_SCALE_FACTOR"]


@pytest.mark.asyncio
async def test_chromium_manager_get_page_cleanup_errors():
    """Test _get_page cleanup when page/context close fails."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Mock context.new_page to return a page that fails to close
        original_new_context = manager._browser.new_context

        async def mock_new_context(*args, **kwargs):
            context = await original_new_context(*args, **kwargs)
            page = await context.new_page()

            # Make page.close raise an exception
            page.close = AsyncMock(side_effect=Exception("Page close error"))

            # Make context.close raise an exception
            context.close = AsyncMock(side_effect=Exception("Context close error"))

            # Return mock context that returns the failing page
            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(return_value=page)
            mock_context.close = context.close
            return mock_context

        with patch.object(manager._browser, "new_context", side_effect=mock_new_context):
            # Should not raise exception despite close errors
            async with manager._get_page() as page:
                assert page is not None

    finally:
        await manager.stop()


# Additional critical test cases for race conditions and edge cases


@pytest.mark.asyncio
async def test_chromium_manager_concurrent_restart_during_conversions():
    """
    Test concurrent restart behavior when restart threshold is hit while other conversions are in progress.

    This tests the race condition fix where restart must happen outside the counter lock.
    """
    # Set low restart threshold to trigger restart quickly
    manager = ChromiumManager(config=ChromiumConfig(restart_after_n_conversions=2, max_concurrent_conversions=5))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><circle cx="25" cy="25" r="20" fill="orange"/></svg>'

        # Track which conversions complete
        conversion_count = 10

        async def convert_with_tracking(index: int) -> tuple[int, bytes]:
            png_bytes = await manager.convert_svg_to_png(svg_content, 50, 50)
            return (index, png_bytes)

        # Run many conversions concurrently - restart will happen during execution
        tasks = [convert_with_tracking(i) for i in range(conversion_count)]
        completed = await asyncio.gather(*tasks)

        # All conversions should succeed even though restart happened
        assert len(completed) == conversion_count
        for index, png_bytes in completed:
            assert png_bytes.startswith(b"\x89PNG"), f"Conversion {index} failed"

        # Counter should have wrapped around due to restart
        # With 10 conversions and restart_after_n=2, we should have multiple restarts
        # Due to race conditions in concurrent operations, the final counter can be 0 or 1
        # (counter is reset to 0 when it reaches 2, so observable values are only 0 or 1)
        assert 0 <= manager._conversion_count <= 1

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_cancellation_handling():
    """
    Test task cancellation during convert_svg_to_png (e.g., timeout).

    This tests the semaphore leak fix - ensures semaphore is released even on cancellation.
    """
    manager = ChromiumManager(config=ChromiumConfig(max_concurrent_conversions=2, conversion_timeout=5))
    await manager.start()

    try:
        # Create an SVG that will cause timeout
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'

        # Mock _perform_conversion to hang longer than timeout
        original_perform = manager._perform_conversion

        async def slow_conversion(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than 5-second timeout
            return await original_perform(*args, **kwargs)

        manager._perform_conversion = slow_conversion

        # First conversion should timeout and be cancelled
        with pytest.raises(RuntimeError, match="SVG to PNG conversion failed after"):
            await manager.convert_svg_to_png(svg_content, 100, 100)

        # Restore original method
        manager._perform_conversion = original_perform

        # Semaphore should have been released - subsequent conversions should work
        svg_content_fast = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="green"/></svg>'
        png_bytes = await manager.convert_svg_to_png(svg_content_fast, 50, 50)
        assert png_bytes.startswith(b"\x89PNG")

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_large_svg_stress_test():
    """
    Test memory behavior with very large SVGs (e.g., 10MB).

    Ensures the system can handle large SVG files without memory issues.
    """
    manager = ChromiumManager()
    await manager.start()

    try:
        # Generate a large SVG with many elements (~10MB)
        # Each circle element is about 80 bytes, so ~200,000 circles = ~10MB
        num_circles = 200_000
        circles = []
        for i in range(num_circles):
            x = (i % 1000) * 2
            y = (i // 1000) * 2
            circles.append(f'<circle cx="{x}" cy="{y}" r="1" fill="blue"/>')

        svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="2000" viewBox="0 0 2000 2000">
            {"".join(circles)}
        </svg>'''

        # Verify SVG is actually large
        svg_size_mb = len(svg_content.encode('utf-8')) / (1024 * 1024)
        assert svg_size_mb >= 8, f"SVG should be ~10MB, got {svg_size_mb:.2f}MB"

        # Conversion should succeed without memory issues
        png_bytes = await manager.convert_svg_to_png(svg_content, 2000, 2000)
        assert png_bytes.startswith(b"\x89PNG")

        # PNG should be reasonable size (compressed)
        png_size_mb = len(png_bytes) / (1024 * 1024)
        assert png_size_mb < 50, f"PNG should be compressed, got {png_size_mb:.2f}MB"

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_browser_crash_simulation():
    """
    Test Chromium crash simulation - mock _perform_conversion to simulate browser process crash.

    This ensures the retry mechanism works correctly when the browser crashes.
    """
    manager = ChromiumManager(config=ChromiumConfig(max_conversion_retries=3))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="purple"/></svg>'

        # Mock _perform_conversion to crash on first attempt
        original_perform = manager._perform_conversion
        crash_count = 0

        async def mock_perform_with_crash(*args, **kwargs):
            nonlocal crash_count
            crash_count += 1
            if crash_count == 1:
                # Simulate browser crash
                raise Exception("Browser process crashed")
            # Subsequent calls succeed with original method
            return await original_perform(*args, **kwargs)

        manager._perform_conversion = mock_perform_with_crash

        # First call should crash, then restart and succeed
        png_bytes = await manager.convert_svg_to_png(svg_content, 50, 50)
        assert png_bytes.startswith(b"\x89PNG")
        assert crash_count == 2  # Crashed once, then succeeded on retry

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_semaphore_exhaustion_prevented():
    """
    Test that semaphore exhaustion is prevented even with failures and timeouts.

    This is a comprehensive test of the semaphore leak fix.
    """
    manager = ChromiumManager(config=ChromiumConfig(max_concurrent_conversions=3, conversion_timeout=5))
    await manager.start()

    try:
        # Create slow conversion that will timeout
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        async def slow_conversion(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than 5-second timeout
            return b"fake"

        manager._perform_conversion = slow_conversion

        # Try to exhaust semaphore with timeouts
        tasks = []
        for _ in range(5):
            task = asyncio.create_task(manager.convert_svg_to_png(svg_content, 50, 50))
            tasks.append(task)
            await asyncio.sleep(0.1)  # Stagger slightly

        # All should timeout/fail
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            assert isinstance(result, (RuntimeError, Exception))

        # Now verify semaphore is not exhausted - a fast conversion should still work
        # Restore fast conversion
        manager._perform_conversion = ChromiumManager._perform_conversion.__get__(manager, ChromiumManager)

        # This should succeed if semaphore was properly released
        svg_content_fast = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="red"/></svg>'
        png_bytes = await manager.convert_svg_to_png(svg_content_fast, 50, 50)
        assert png_bytes.startswith(b"\x89PNG")

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_timeout_configuration():
    """Test that conversion timeout is configurable via environment variable."""
    os.environ["CHROMIUM_CONVERSION_TIMEOUT"] = "5"

    try:
        manager = ChromiumManager()
        assert manager.conversion_timeout == 5
    finally:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]

    # Test default value
    if "CHROMIUM_CONVERSION_TIMEOUT" in os.environ:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]
    manager = ChromiumManager()
    assert manager.conversion_timeout == 30


@pytest.mark.asyncio
async def test_chromium_manager_timeout_validation_out_of_range():
    """Test that CHROMIUM_CONVERSION_TIMEOUT is validated."""
    # Test value too low (minimum is 5)
    os.environ["CHROMIUM_CONVERSION_TIMEOUT"] = "2"
    try:
        manager = ChromiumManager()
        assert manager.conversion_timeout == 30  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]

    # Test value too high (maximum is 300)
    os.environ["CHROMIUM_CONVERSION_TIMEOUT"] = "500"
    try:
        manager = ChromiumManager()
        assert manager.conversion_timeout == 30  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]

    # Test valid boundary values
    os.environ["CHROMIUM_CONVERSION_TIMEOUT"] = "5"
    try:
        manager = ChromiumManager()
        assert manager.conversion_timeout == 5  # Minimum valid value
    finally:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]

    os.environ["CHROMIUM_CONVERSION_TIMEOUT"] = "300"
    try:
        manager = ChromiumManager()
        assert manager.conversion_timeout == 300  # Maximum valid value
    finally:
        del os.environ["CHROMIUM_CONVERSION_TIMEOUT"]


# Background health monitoring tests


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_enabled_by_default():
    """Test that health monitoring is enabled by default."""
    manager = ChromiumManager()
    assert manager.health_check_enabled is True
    assert manager.health_check_interval == 30


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_from_env():
    """Test health monitoring configuration from environment variables."""
    os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"] = "false"
    os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"] = "60"

    try:
        manager = ChromiumManager()
        assert manager.health_check_enabled is False
        assert manager.health_check_interval == 60
    finally:
        del os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"]
        del os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"]


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_starts_with_browser():
    """Test that health monitoring starts when browser starts."""
    manager = ChromiumManager(config=ChromiumConfig(health_check_enabled=True, health_check_interval=10))
    assert manager._health_monitor_task is None

    await manager.start()
    try:
        # Health monitor task should be running
        assert manager._health_monitor_task is not None
        assert not manager._health_monitor_task.done()
    finally:
        await manager.stop()
        # Health monitor task should be stopped
        assert manager._health_monitor_task is None


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_disabled():
    """Test that health monitoring can be disabled."""
    manager = ChromiumManager(config=ChromiumConfig(health_check_enabled=False))
    await manager.start()

    try:
        # Health monitor task should not be created
        assert manager._health_monitor_task is None
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_get_metrics():
    """Test metrics collection and retrieval."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Get initial metrics
        metrics = manager.get_metrics()

        assert "total_conversions" in metrics
        assert "failed_conversions" in metrics
        assert "error_rate_percent" in metrics
        assert "total_restarts" in metrics
        assert "avg_conversion_time_ms" in metrics
        assert "last_health_check" in metrics
        assert "last_health_status" in metrics
        assert "consecutive_failures" in metrics
        assert "uptime_seconds" in metrics

        # Initial values
        assert metrics["total_conversions"] == 0
        assert metrics["failed_conversions"] == 0
        assert metrics["error_rate_percent"] == 0.0
        assert metrics["total_restarts"] == 0
        assert metrics["uptime_seconds"] >= 0.0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_metrics_after_conversion():
    """Test that metrics are updated after conversions."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Perform conversion
        await manager.convert_svg_to_png(svg_content, 50, 50)

        # Check metrics
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 1
        assert metrics["failed_conversions"] == 0
        assert metrics["error_rate_percent"] == 0.0
        assert metrics["avg_conversion_time_ms"] > 0.0
        assert metrics["consecutive_failures"] == 0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_metrics_after_failure():
    """Test that metrics are updated after conversion failures."""
    manager = ChromiumManager(config=ChromiumConfig(max_conversion_retries=1))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Mock _perform_conversion to always fail
        async def mock_perform_conversion(*args, **kwargs):
            raise Exception("Simulated failure")

        manager._perform_conversion = mock_perform_conversion

        # Attempt conversion (should fail)
        with pytest.raises(RuntimeError, match="SVG to PNG conversion failed"):
            await manager.convert_svg_to_png(svg_content, 50, 50)

        # Check metrics
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 0
        assert metrics["failed_conversions"] == 1
        assert metrics["error_rate_percent"] == 100.0
        assert metrics["consecutive_failures"] == 1

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_interval():
    """Test that health monitoring runs at specified interval."""
    manager = ChromiumManager(config=ChromiumConfig(health_check_enabled=True, health_check_interval=10))  # 10 second interval (minimum)
    await manager.start()

    try:
        # Wait for at least 1 health check
        await asyncio.sleep(11)

        # Get metrics
        metrics = manager.get_metrics()

        # Last health check should be recent
        import time

        time_since_last_check = time.time() - metrics["last_health_check"]
        assert time_since_last_check < 11.0  # Should have checked within last 11 seconds

        # Health should be passing
        assert metrics["last_health_status"] is True

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_health_monitoring_validation():
    """Test validation of health monitoring configuration."""
    # Test interval too low
    os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"] = "5"
    try:
        manager = ChromiumManager()
        assert manager.health_check_interval == 30  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"]

    # Test interval too high
    os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"] = "500"
    try:
        manager = ChromiumManager()
        assert manager.health_check_interval == 30  # Should fall back to default
    finally:
        del os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"]

    # Test valid values
    os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"] = "10"
    try:
        manager = ChromiumManager()
        assert manager.health_check_interval == 10  # Minimum valid value
    finally:
        del os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"]

    os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"] = "300"
    try:
        manager = ChromiumManager()
        assert manager.health_check_interval == 300  # Maximum valid value
    finally:
        del os.environ["CHROMIUM_HEALTH_CHECK_INTERVAL"]


@pytest.mark.asyncio
async def test_chromium_manager_health_enabled_boolean_parsing():
    """Test parsing of CHROMIUM_HEALTH_CHECK_ENABLED from various string values."""
    # Test "true" (case-insensitive)
    for value in ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]:
        os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"] = value
        try:
            manager = ChromiumManager()
            assert manager.health_check_enabled is True
        finally:
            del os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"]

    # Test "false" (case-insensitive)
    for value in ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF"]:
        os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"] = value
        try:
            manager = ChromiumManager()
            assert manager.health_check_enabled is False
        finally:
            del os.environ["CHROMIUM_HEALTH_CHECK_ENABLED"]


@pytest.mark.asyncio
async def test_chromium_manager_auto_restart_on_health_degradation():
    """Test that Chromium automatically restarts when health degrades (3 consecutive failures)."""
    manager = ChromiumManager(config=ChromiumConfig(health_check_enabled=True, health_check_interval=10))
    await manager.start()

    try:
        # Track restart calls
        restart_count = 0
        original_restart = manager.restart

        async def mock_restart():
            nonlocal restart_count
            restart_count += 1
            await original_restart()

        manager.restart = mock_restart

        # Mock health_check to fail 3 times, then succeed
        health_check_calls = 0
        original_health_check = manager.health_check

        def mock_health_check():
            nonlocal health_check_calls
            health_check_calls += 1
            # Fail first 3 times, then succeed
            if health_check_calls <= 3:
                manager._metrics.record_health_check(False)
                return False
            return original_health_check()

        manager.health_check = mock_health_check

        # Wait for health monitor to detect failures and trigger restart
        # Need to wait for: 3 failed checks + restart trigger
        await asyncio.sleep(35)  # 3 intervals + some buffer

        # Should have triggered auto-restart after 3 consecutive failures
        assert restart_count >= 1, f"Expected at least 1 restart, got {restart_count}"
        assert health_check_calls >= 3, f"Expected at least 3 health checks, got {health_check_calls}"

        # Restore original methods
        manager.restart = original_restart
        manager.health_check = original_health_check

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_metrics_survive_restart():
    """Test that metrics persist correctly across browser restarts."""
    manager = ChromiumManager()
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Perform some conversions
        await manager.convert_svg_to_png(svg_content, 50, 50)
        await manager.convert_svg_to_png(svg_content, 50, 50)

        # Get metrics before restart
        metrics_before = manager.get_metrics()
        assert metrics_before["total_conversions"] == 2
        assert metrics_before["total_restarts"] == 0

        # Restart browser
        await manager.restart()

        # Get metrics after restart
        metrics_after = manager.get_metrics()

        # Conversions should persist
        assert metrics_after["total_conversions"] == 2
        # Restarts should increment
        assert metrics_after["total_restarts"] == 1
        # Uptime should reset
        assert metrics_after["uptime_seconds"] < metrics_before["uptime_seconds"]

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_concurrent_conversions_metrics():
    """Test that metrics are correctly tracked with concurrent conversions."""
    manager = ChromiumManager(config=ChromiumConfig(max_concurrent_conversions=5))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><circle cx="25" cy="25" r="20" fill="blue"/></svg>'

        # Perform many concurrent conversions
        tasks = [manager.convert_svg_to_png(svg_content, 50, 50) for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed
        successful = [r for r in results if isinstance(r, bytes)]
        assert len(successful) == 10

        # Check metrics
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 10
        assert metrics["failed_conversions"] == 0
        assert metrics["error_rate_percent"] == 0.0
        assert metrics["avg_conversion_time_ms"] > 0.0
        assert metrics["consecutive_failures"] == 0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_metrics_with_disabled_health_monitoring():
    """Test that metrics collection works even when health monitoring is disabled."""
    manager = ChromiumManager(config=ChromiumConfig(health_check_enabled=False))
    await manager.start()

    try:
        # Health monitor task should not be running
        assert manager._health_monitor_task is None

        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Perform conversion
        await manager.convert_svg_to_png(svg_content, 50, 50)

        # Metrics should still work
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 1
        assert metrics["failed_conversions"] == 0
        assert metrics["avg_conversion_time_ms"] > 0.0
        assert metrics["uptime_seconds"] >= 0.0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_error_rate_calculation():
    """Test error rate calculation with various success/failure combinations."""
    manager = ChromiumManager(config=ChromiumConfig(max_conversion_retries=1))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Successful conversion
        await manager.convert_svg_to_png(svg_content, 50, 50)
        metrics = manager.get_metrics()
        assert metrics["error_rate_percent"] == 0.0

        # Mock failure
        original_perform = manager._perform_conversion

        async def mock_perform_failure(*args, **kwargs):
            raise Exception("Simulated failure")

        manager._perform_conversion = mock_perform_failure

        # Failed conversion
        with pytest.raises(RuntimeError):
            await manager.convert_svg_to_png(svg_content, 50, 50)

        # Restore
        manager._perform_conversion = original_perform

        # Check error rate: 1 success, 1 failure = 50%
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 1
        assert metrics["failed_conversions"] == 1
        assert metrics["error_rate_percent"] == 50.0

        # Another successful conversion
        await manager.convert_svg_to_png(svg_content, 50, 50)

        # Check error rate: 2 success, 1 failure = 33.33%
        metrics = manager.get_metrics()
        assert metrics["total_conversions"] == 2
        assert metrics["failed_conversions"] == 1
        assert 33.0 <= metrics["error_rate_percent"] <= 34.0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_consecutive_failures_reset():
    """Test that consecutive failures counter resets after successful conversion."""
    manager = ChromiumManager(config=ChromiumConfig(max_conversion_retries=1))
    await manager.start()

    try:
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"></svg>'

        # Mock to fail once
        original_perform = manager._perform_conversion
        fail_next = True

        async def mock_perform_sometimes_fail(*args, **kwargs):
            nonlocal fail_next
            if fail_next:
                fail_next = False
                raise Exception("Simulated failure")
            return await original_perform(*args, **kwargs)

        manager._perform_conversion = mock_perform_sometimes_fail

        # First conversion fails
        with pytest.raises(RuntimeError):
            await manager.convert_svg_to_png(svg_content, 50, 50)

        metrics = manager.get_metrics()
        assert metrics["consecutive_failures"] == 1

        # Restore for successful conversion
        manager._perform_conversion = original_perform

        # Successful conversion should reset consecutive failures
        await manager.convert_svg_to_png(svg_content, 50, 50)

        metrics = manager.get_metrics()
        assert metrics["consecutive_failures"] == 0
        assert metrics["total_conversions"] == 1
        assert metrics["failed_conversions"] == 1

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_uptime_tracking():
    """Test that uptime is tracked correctly."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Get initial uptime
        metrics1 = manager.get_metrics()
        uptime1 = metrics1["uptime_seconds"]
        assert uptime1 >= 0.0

        # Wait a bit
        await asyncio.sleep(1.5)

        # Get uptime again
        metrics2 = manager.get_metrics()
        uptime2 = metrics2["uptime_seconds"]

        # Uptime should have increased
        assert uptime2 > uptime1
        assert uptime2 >= 1.0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_metrics_initial_state():
    """Test that metrics have correct initial values."""
    manager = ChromiumManager()

    # Before starting
    metrics = manager.get_metrics()
    assert metrics["total_conversions"] == 0
    assert metrics["failed_conversions"] == 0
    assert metrics["error_rate_percent"] == 0.0
    assert metrics["total_restarts"] == 0
    assert metrics["avg_conversion_time_ms"] == 0.0
    assert metrics["last_health_check"] == 0.0
    assert metrics["last_health_status"] is False
    assert metrics["consecutive_failures"] == 0
    assert metrics["uptime_seconds"] >= 0.0

    await manager.start()
    try:
        # After starting, uptime should be tracked
        metrics = manager.get_metrics()
        assert metrics["uptime_seconds"] >= 0.0

    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_chromium_manager_multiple_restarts_tracking():
    """Test that multiple restarts are correctly tracked in metrics."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Perform multiple restarts
        await manager.restart()
        await manager.restart()
        await manager.restart()

        # Check restart counter
        metrics = manager.get_metrics()
        assert metrics["total_restarts"] == 3

    finally:
        await manager.stop()
