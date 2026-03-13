"""Tests for VsdxProcessor with mocked LibreOffice."""

import base64
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from app.vsdx_processor import VsdxCorruptedError, VsdxProcessor


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
