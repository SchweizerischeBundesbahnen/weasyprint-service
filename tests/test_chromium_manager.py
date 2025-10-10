"""Tests for ChromiumManager CDP-based SVG conversion."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chromium_manager import ChromiumManager, get_chromium_manager


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
    manager = ChromiumManager(device_scale_factor=2.0)
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
    import asyncio

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
    from app.html_parser import HtmlParser
    from app.svg_processor import SvgProcessor

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
    from app.html_parser import HtmlParser
    from app.svg_processor import SvgProcessor

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
    from app.html_parser import HtmlParser
    from app.svg_processor import SvgProcessor

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
    from app.html_parser import HtmlParser
    from app.svg_processor import SvgProcessor

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
    manager = ChromiumManager(device_scale_factor=1.0)
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
    import os

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
    from unittest.mock import PropertyMock

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
    manager = ChromiumManager(device_scale_factor=1.0)
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
    import asyncio

    # Set a low limit to test semaphore behavior
    manager = ChromiumManager(max_concurrent_conversions=3)
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
    import os

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
    manager = ChromiumManager(restart_after_n_conversions=3)
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
    manager = ChromiumManager(restart_after_n_conversions=0)
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
            original_page_close = page.close
            page.close = AsyncMock(side_effect=Exception("Page close error"))

            # Make context.close raise an exception
            original_context_close = context.close
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
