"""Tests for ChromiumManager CDP-based SVG conversion."""

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
