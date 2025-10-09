"""Tests for ChromiumManager CDP-based SVG conversion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chromium_manager import ChromiumManager, get_chromium_manager


@pytest.mark.asyncio
async def test_chromium_manager_lifecycle():
    """Test ChromiumManager startup and shutdown lifecycle."""
    manager = ChromiumManager()

    # Should not be running initially
    assert not await manager.is_running()

    # Start the browser
    await manager.start()
    assert await manager.is_running()

    # Health check should pass
    assert await manager.health_check()

    # Stop the browser
    await manager.stop()
    assert not await manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_double_start():
    """Test that calling start twice doesn't cause issues."""
    manager = ChromiumManager()

    await manager.start()
    assert await manager.is_running()

    # Second start should log warning but not fail
    await manager.start()
    assert await manager.is_running()

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
    assert not await manager.health_check()


@pytest.mark.asyncio
async def test_chromium_manager_restart():
    """Test browser restart functionality."""
    manager = ChromiumManager()

    await manager.start()
    assert await manager.is_running()

    await manager.restart()
    assert await manager.is_running()

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
    version = await manager.get_version()
    assert version is None

    # Start browser
    await manager.start()

    # Version should be a string when running
    version = await manager.get_version()
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
    assert not await manager.is_running()


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
        version = await manager.get_version()
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

            version = await manager.get_version()
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
        assert not await manager.is_running()


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
        assert not await manager.is_running()


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
        assert not await manager.is_running()


@pytest.mark.asyncio
async def test_chromium_manager_health_check_with_error():
    """Test health check when page navigation fails."""
    manager = ChromiumManager()
    await manager.start()

    try:
        # Mock _get_page to raise an exception
        with patch.object(manager, "_get_page") as mock_get_page:
            mock_get_page.side_effect = Exception("Page creation failed")

            # Health check should return False, not raise exception
            result = await manager.health_check()
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
            version = await manager.get_version()
            assert version is None

    finally:
        await manager.stop()


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
