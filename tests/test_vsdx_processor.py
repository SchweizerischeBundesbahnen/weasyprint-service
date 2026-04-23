"""Tests for VsdxProcessor with mocked LibreOffice."""

import base64
from unittest.mock import AsyncMock, Mock

import pytest
from bs4 import BeautifulSoup

from app.vsdx_processor import VsdxCorruptedError, VsdxProcessor


@pytest.fixture(autouse=True)
def _reset_libreoffice_cache():
    """Reset the class-level LibreOffice availability cache between tests."""
    VsdxProcessor._libreoffice_available = None
    yield
    VsdxProcessor._libreoffice_available = None


@pytest.mark.asyncio
async def test_vsdx_processor_initialization_libreoffice_available(mocker):
    """Test VsdxProcessor initialization when LibreOffice is available."""
    # Mock successful LibreOffice check
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=0, stdout="LibreOffice 7.0.0")

    processor = VsdxProcessor()

    assert processor.libreoffice_available is True
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_vsdx_processor_initialization_libreoffice_unavailable(mocker):
    """Test VsdxProcessor initialization when LibreOffice is not available."""
    # Mock failed LibreOffice check
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=1, stderr="command not found")

    processor = VsdxProcessor()

    assert processor.libreoffice_available is False
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_vsdx_processor_initialization_libreoffice_not_found(mocker):
    """Test VsdxProcessor initialization when LibreOffice command not found."""
    # Mock FileNotFoundError
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = FileNotFoundError("libreoffice not found")

    processor = VsdxProcessor()

    assert processor.libreoffice_available is False
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_vsdx_processor_convert_invalid_base64(mocker):
    """Test conversion with invalid base64 data."""
    # Mock LibreOffice availability
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=0, stdout="LibreOffice 7.0.0")

    processor = VsdxProcessor()

    # Test with invalid base64
    with pytest.raises(VsdxCorruptedError, match="Invalid base64 data"):
        await processor._convert_vsdx_to_png("invalid_base64!")


@pytest.mark.asyncio
async def test_vsdx_processor_convert_invalid_zip_header(mocker):
    """Test conversion with invalid ZIP header."""
    # Mock LibreOffice availability
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=0, stdout="LibreOffice 7.0.0")

    processor = VsdxProcessor()

    # Test with valid base64 but invalid ZIP header
    invalid_data = base64.b64encode(b"NOT_A_ZIP_FILE").decode("ascii")

    with pytest.raises(VsdxCorruptedError, match="VSDX missing ZIP header"):
        await processor._convert_vsdx_to_png(invalid_data)


@pytest.mark.asyncio
async def test_vsdx_processor_replace_vsdx_base64_successful_conversion(mocker):
    """Test successful VSDX to PNG replacement in HTML img tags."""
    # Mock LibreOffice availability
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=0, stdout="LibreOffice 7.0.0")

    processor = VsdxProcessor()

    # Create a fake PNG (1x1 pixel)
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    mock_convert = AsyncMock(return_value=fake_png)
    mocker.patch.object(processor, "_convert_vsdx_to_png", mock_convert)

    # Build HTML with a VSDX data URL img tag
    vsdx_base64 = base64.b64encode(b"PK\x03\x04fake_vsdx_content").decode("ascii")
    html = f'<html><body><img src="data:application/vnd.ms-visio.drawing;base64,{vsdx_base64}"/></body></html>'
    soup = BeautifulSoup(html, "html.parser")

    result = await processor.replace_vsdx_base64(soup)

    # Verify _convert_vsdx_to_png was called with the base64 payload
    mock_convert.assert_called_once_with(vsdx_base64)

    # Verify the img src was replaced with a PNG data URL
    img_tag = result.find("img")
    expected_png_b64 = base64.b64encode(fake_png).decode("ascii")
    assert img_tag["src"] == f"data:image/png;base64,{expected_png_b64}"


@pytest.mark.asyncio
async def test_vsdx_processor_replace_vsdx_base64_skips_non_vsdx(mocker):
    """Test that non-VSDX img tags are left unchanged."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=0, stdout="LibreOffice 7.0.0")

    processor = VsdxProcessor()

    png_src = "data:image/png;base64,iVBORw0KGgo="
    html = f'<html><body><img src="{png_src}"/></body></html>'
    soup = BeautifulSoup(html, "html.parser")

    result = await processor.replace_vsdx_base64(soup)

    img_tag = result.find("img")
    assert img_tag["src"] == png_src


@pytest.mark.asyncio
async def test_vsdx_processor_replace_vsdx_base64_skipped_when_unavailable(mocker):
    """Test that VSDX conversion is skipped when LibreOffice is unavailable."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = Mock(returncode=1, stderr="not found")

    processor = VsdxProcessor()

    vsdx_base64 = base64.b64encode(b"PK\x03\x04fake").decode("ascii")
    original_src = f"data:application/vnd.ms-visio.drawing;base64,{vsdx_base64}"
    html = f'<html><body><img src="{original_src}"/></body></html>'
    soup = BeautifulSoup(html, "html.parser")

    result = await processor.replace_vsdx_base64(soup)

    img_tag = result.find("img")
    assert img_tag["src"] == original_src


@pytest.mark.asyncio
async def test_vsdx_processor_parse_data_url_base64():
    """Test data URL parsing."""
    processor = VsdxProcessor()

    # Valid VSDX data URL
    vsdx_url = "data:application/vnd.ms-visio.drawing;base64,UEsDBBQAAAAI"
    result = processor._parse_data_url_base64(vsdx_url)
    assert result == ("application/vnd.ms-visio.drawing", "UEsDBBQAAAAI")

    # Invalid data URL
    assert processor._parse_data_url_base64("http://example.com/image.png") is None
    assert processor._parse_data_url_base64("data:image/png,notbase64") is None
    assert processor._parse_data_url_base64(None) is None


@pytest.mark.asyncio
async def test_vsdx_processor_is_vsdx_content():
    """Test VSDX content type detection."""
    processor = VsdxProcessor()

    assert processor._is_vsdx_content("application/vnd.ms-visio.drawing") is True
    assert processor._is_vsdx_content("image/png") is False
    assert processor._is_vsdx_content("image/svg+xml") is False


@pytest.mark.asyncio
async def test_vsdx_processor_get_attr_str():
    """Test attribute string extraction."""
    html = '<img src="test.png" alt="test"/>'
    soup = BeautifulSoup(html, "html.parser")
    img_tag = soup.find("img")

    assert VsdxProcessor._get_attr_str(img_tag, "src") == "test.png"
    assert VsdxProcessor._get_attr_str(img_tag, "alt") == "test"
    assert VsdxProcessor._get_attr_str(img_tag, "nonexistent") is None
