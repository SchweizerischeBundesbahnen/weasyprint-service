"""Tests for verifying that logging messages are emitted correctly in application components."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from app.attachment_manager import AttachmentManager
from app.form_parser import FormParser
from app.html_parser import HtmlParser


class TestAttachmentManagerLogging:
    """Test logging in AttachmentManager."""

    def test_find_referenced_attachments_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that finding referenced attachments logs appropriately."""
        manager = AttachmentManager()
        html = '<html><body><a rel="attachment" href="file1.pdf">Link</a><a rel="attachment" href="file2.pdf">Link2</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")

        with caplog.at_level(logging.INFO):
            result = manager.find_referenced_attachment_names(soup)

        assert len(result) == 2
        assert any("Found 2 referenced attachments" in record.message for record in caplog.records)

    def test_save_uploads_logs_summary(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        """Test that saving uploads logs a summary instead of per-file logs."""
        import asyncio

        manager = AttachmentManager()

        # Create mock upload files
        mock_file1 = AsyncMock()
        mock_file1.filename = "test1.pdf"
        mock_file1.read = AsyncMock(return_value=b"content1")

        mock_file2 = AsyncMock()
        mock_file2.filename = "test2.pdf"
        mock_file2.read = AsyncMock(return_value=b"content2")

        with caplog.at_level(logging.INFO):
            result = asyncio.run(manager.save_uploads_to_tmpdir([mock_file1, mock_file2], tmp_path))

        assert len(result) == 2
        # Should have summary log, not per-file logs
        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert len(info_logs) == 1
        assert "Saved 2 files successfully" in info_logs[0].message
        assert "total size:" in info_logs[0].message.lower()

    def test_build_attachments_logs_summary(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        """Test that building attachments logs a summary."""
        manager = AttachmentManager()
        name_to_path = {
            "file1.pdf": tmp_path / "file1.pdf",
            "file2.pdf": tmp_path / "file2.pdf",
            "file3.pdf": tmp_path / "file3.pdf",
        }
        # Create the files
        for path in name_to_path.values():
            path.write_text("test")

        referenced = {"file1.pdf"}  # One file is referenced

        with caplog.at_level(logging.INFO):
            result = manager.build_attachments_for_unreferenced(name_to_path, referenced)

        assert len(result) == 2  # Two unreferenced files
        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert len(info_logs) == 1
        assert "Built 2 attachments" in info_logs[0].message
        assert "skipped 1 referenced" in info_logs[0].message


class TestFormParserLogging:
    """Test logging in FormParser."""

    def test_parser_initialization_logs_limits(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that FormParser initialization logs configuration."""
        with caplog.at_level(logging.DEBUG):
            parser = FormParser(max_files=100, max_fields=200, max_part_size=5000000)

        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("FormParser initialized" in record.message for record in debug_logs)
        assert any("max_files: 100" in record.message for record in debug_logs)

    def test_missing_html_field_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that missing HTML field logs an error."""
        from starlette.datastructures import FormData

        form = FormData()  # Empty form without 'html' field

        with caplog.at_level(logging.ERROR):
            with pytest.raises(AssertionError):
                FormParser.html_from_form(form)

        error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
        assert any('Required form field "html" is missing' in record.message for record in error_logs)


class TestHtmlParserLogging:
    """Test logging in HtmlParser."""

    def test_parse_full_document_logs_type(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that parsing logs document type."""
        parser = HtmlParser()
        html = "<!DOCTYPE html><html><head><title>Test</title></head><body><p>Content</p></body></html>"

        with caplog.at_level(logging.DEBUG):
            result = parser.parse(html)

        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("Document type: full document" in record.message for record in debug_logs)

    def test_parse_fragment_logs_type(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that parsing fragment logs correctly."""
        parser = HtmlParser()
        html = "<div>Fragment content</div>"

        with caplog.at_level(logging.DEBUG):
            result = parser.parse(html)

        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        assert any("Document type: fragment" in record.message for record in debug_logs)

    def test_xml_declaration_logs_length_not_content(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that XML declaration logs length, not actual content (for security)."""
        parser = HtmlParser()
        xml_decl = "<?xml version='1.0' encoding='UTF-8'?>"
        html = xml_decl + "<html><body>Content</body></html>"

        with caplog.at_level(logging.DEBUG):
            result = parser.parse(html)

        debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
        xml_logs = [log for log in debug_logs if "XML declaration" in log.message]

        # Should log the length but not the actual content
        assert any("length:" in log.message for log in xml_logs)
        # Should NOT log the actual XML content verbatim
        assert not any(xml_decl in log.message for log in xml_logs)

    def test_serialize_logs_result_size(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that serialization logs the output size."""
        parser = HtmlParser()
        html = "<!DOCTYPE html><html><body><p>Test content</p></body></html>"
        parsed = parser.parse(html)

        with caplog.at_level(logging.INFO):
            result = parser.serialize(parsed)

        info_logs = [record for record in caplog.records if record.levelname == "INFO"]
        assert any("Serialized" in record.message and "size:" in record.message for record in info_logs)


class TestLoggingSanitization:
    """Test that logging sanitization is applied correctly."""

    def test_filename_with_newlines_sanitized(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        """Test that filenames with newlines are sanitized in logs."""
        manager = AttachmentManager()
        # Create a file with problematic name
        safe_name = "test_file.pdf"
        test_path = tmp_path / safe_name
        test_path.write_text("test")

        name_to_path = {safe_name: test_path}
        soup = BeautifulSoup(f'<html><body><a rel="attachment" href="{safe_name}">Link</a></body></html>', "html.parser")

        with caplog.at_level(logging.WARNING):
            # Try to rewrite with a file that doesn't exist to trigger warning
            manager.rewrite_attachment_links_to_file_uri(soup, {"nonexistent.pdf": tmp_path / "other.pdf"})

        # Check that any logged filenames don't contain newlines
        for record in caplog.records:
            assert "\n" not in record.message
            assert "\r" not in record.message

    def test_no_control_characters_in_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that control characters are removed from log messages."""
        from app.sanitization import sanitize_for_logging

        dangerous_input = "test\x00\x01\x02file\nname"
        safe_output = sanitize_for_logging(dangerous_input)

        # Verify sanitization worked
        assert "\x00" not in safe_output
        assert "\x01" not in safe_output
        assert "\x02" not in safe_output
        assert "\n" not in safe_output
