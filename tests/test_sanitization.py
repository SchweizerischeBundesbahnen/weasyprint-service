"""Tests for the sanitization module."""

import pytest
from urllib.parse import urlparse
from app.sanitization import sanitize_for_logging, sanitize_path_for_logging, sanitize_url_for_logging


class TestSanitizeForLogging:
    """Test cases for sanitize_for_logging function."""

    def test_normal_text(self) -> None:
        """Test that normal text is preserved."""
        assert sanitize_for_logging("normal text") == "normal text"
        assert sanitize_for_logging("numbers 123") == "numbers 123"

    def test_newline_removal(self) -> None:
        """Test that newlines are replaced with spaces."""
        assert sanitize_for_logging("line1\nline2") == "line1 line2"
        assert sanitize_for_logging("line1\r\nline2") == "line1  line2"
        assert sanitize_for_logging("line1\rline2") == "line1 line2"

    def test_mixed_line_endings(self) -> None:
        """Test handling of mixed line endings."""
        text = "line1\nline2\r\nline3\rline4"
        expected = "line1 line2  line3 line4"
        assert sanitize_for_logging(text) == expected

    def test_control_character_removal(self) -> None:
        """Test that control characters are removed."""
        # Test various control characters
        text_with_controls = "test\x00\x01\x02\x1f\x7fdata"
        assert sanitize_for_logging(text_with_controls) == "testdata"

    def test_non_string_input(self) -> None:
        """Test handling of non-string input."""
        assert sanitize_for_logging(123) == "123"  # type: ignore[arg-type]
        assert sanitize_for_logging(None) == "None"  # type: ignore[arg-type]
        assert sanitize_for_logging(["list"]) == "['list']"  # type: ignore[arg-type]

    def test_special_characters_preserved(self) -> None:
        """Test that other special characters are preserved."""
        assert sanitize_for_logging("test@#$%^&*()") == "test@#$%^&*()"
        assert sanitize_for_logging("unicode: ñáéíóú") == "unicode: ñáéíóú"

    def test_truncation_default(self) -> None:
        """Test that text is truncated at default max_length (1000)."""
        long_text = "a" * 1500
        result = sanitize_for_logging(long_text)
        assert len(result) == 1000 + len("...[truncated]")
        assert result == "a" * 1000 + "...[truncated]"

    def test_truncation_custom_length(self) -> None:
        """Test that text is truncated at custom max_length."""
        long_text = "b" * 200
        result = sanitize_for_logging(long_text, max_length=50)
        assert len(result) == 50 + len("...[truncated]")
        assert result == "b" * 50 + "...[truncated]"

    def test_no_truncation_when_under_limit(self) -> None:
        """Test that short text is not truncated."""
        short_text = "short"
        assert sanitize_for_logging(short_text, max_length=1000) == "short"
        assert sanitize_for_logging(short_text, max_length=10) == "short"


class TestSanitizationIntegration:
    """Integration tests for sanitization functions."""

    def test_filename_sanitization_for_logging(self) -> None:
        """Test sanitizing dangerous filenames for logging."""
        dangerous_filename = "../../../etc/passwd\nwith\rlinebreaks"
        safe_for_log = sanitize_for_logging(dangerous_filename)
        assert safe_for_log == "../../../etc/passwd with linebreaks"

    def test_xml_declaration_sanitization(self) -> None:
        """Test sanitizing XML declarations for logging."""
        xml_decl = "<?xml version='1.0' encoding='UTF-8'?>\n"
        safe = sanitize_for_logging(xml_decl, max_length=50)
        assert "\n" not in safe
        assert " " in safe  # newline replaced with space

    def test_real_world_scenarios(self) -> None:
        """Test real-world scenarios from the application."""
        # Scenario 1: Logging user filename safely
        user_filename = "../../secret\nfile.pdf"
        log_safe = sanitize_for_logging(user_filename, max_length=100)
        assert "\n" not in log_safe
        assert log_safe == "../../secret file.pdf"

        # Scenario 2: Logging HTML content preview
        html_content = "<html>\n<head>\n<title>Test</title>\n</head>\n<body>Content</body></html>"
        log_safe = sanitize_for_logging(html_content, max_length=50)
        assert "\n" not in log_safe
        assert log_safe == "<html> <head> <title>Test</title> </head> <body>Co...[truncated]"


@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("normal text", "normal text"),
        ("line1\nline2", "line1 line2"),
        ("line1\r\nline2", "line1  line2"),
        ("line1\rline2", "line1 line2"),
        ("mixed\nline\r\nendings\r", "mixed line  endings "),
        ("control\x00chars\x01here", "controlcharshere"),
    ],
)
def test_sanitize_for_logging_parametrized(input_text: str, expected: str) -> None:
    """Parametrized tests for sanitize_for_logging function."""
    assert sanitize_for_logging(input_text) == expected


@pytest.mark.parametrize(
    "input_text,max_length,expected_length",
    [
        ("a" * 50, 100, 50),
        ("b" * 150, 100, 100 + len("...[truncated]")),
        ("c" * 10, 20, 10),
        ("d" * 2000, 1000, 1000 + len("...[truncated]")),
    ],
)
def test_sanitize_for_logging_truncation_parametrized(input_text: str, max_length: int, expected_length: int) -> None:
    """Parametrized tests for truncation behavior."""
    result = sanitize_for_logging(input_text, max_length=max_length)
    assert len(result) == expected_length


class TestSanitizeUrlForLogging:
    """Test cases for sanitize_url_for_logging function."""

    def test_none_input(self) -> None:
        """Test that None input returns 'None'."""
        assert sanitize_url_for_logging(None) == "None"

    def test_simple_url(self) -> None:
        """Test that simple URLs are preserved."""
        assert sanitize_url_for_logging("https://example.com/path") == "https://example.com/path"

    def test_url_with_query_parameters(self) -> None:
        """Test that query parameters are removed for security."""
        url = "https://example.com/path?token=secret123&api_key=sensitive"
        result = sanitize_url_for_logging(url)
        assert "token" not in result
        assert "secret123" not in result
        assert "api_key" not in result
        assert "example.com" in result
        assert "/path" in result

    def test_url_with_credentials(self) -> None:
        """Test that user credentials are removed."""
        url = "https://user:password@example.com/path"
        result = sanitize_url_for_logging(url)
        assert "user" not in result
        assert "password" not in result
        assert "example.com" in result

    def test_url_with_port(self) -> None:
        """Test that port numbers are preserved."""
        url = "https://example.com:8080/path"
        result = sanitize_url_for_logging(url)
        assert "8080" in result
        assert urlparse(result).hostname == "example.com"

    def test_malformed_url(self) -> None:
        """Test that malformed URLs don't cause crashes."""
        result = sanitize_url_for_logging("not a valid url")
        assert result is not None
        assert len(result) > 0

    def test_url_with_newlines(self) -> None:
        """Test that URLs with newlines are sanitized."""
        url = "https://example.com/path\nwith\nnewlines"
        result = sanitize_url_for_logging(url)
        assert "\n" not in result


class TestSanitizePathForLogging:
    """Test cases for sanitize_path_for_logging function."""

    def test_none_input(self) -> None:
        """Test that None input returns 'None'."""
        assert sanitize_path_for_logging(None) == "None"

    def test_basename_only_default(self) -> None:
        """Test that only basename is shown by default."""
        path = "/var/tmp/weasyprint-attach-abc123/file.pdf"
        result = sanitize_path_for_logging(path)
        assert result == "file.pdf"
        assert "/var/tmp" not in result

    def test_show_full_path(self) -> None:
        """Test showing full path when requested."""
        path = "/home/user/document.pdf"
        result = sanitize_path_for_logging(path, show_basename_only=False)
        assert "document.pdf" in result

    def test_temp_directory_indication(self) -> None:
        """Test that temp directories are indicated as such."""
        path = "/tmp/weasyprint-attach-xyz/file.pdf"
        result = sanitize_path_for_logging(path, show_basename_only=False)
        assert "<temp>" in result
        assert "file.pdf" in result
        assert "/tmp/" not in result  # Full path should be hidden

    def test_windows_temp_directory(self) -> None:
        """Test Windows temp directory handling."""
        path = "C:\\Temp\\weasyprint\\file.pdf"
        result = sanitize_path_for_logging(path, show_basename_only=False)
        assert "<temp>" in result
        assert "file.pdf" in result

    def test_path_with_newlines(self) -> None:
        """Test that paths with newlines are sanitized."""
        path = "/path/to/file\nwith\nnewlines.pdf"
        result = sanitize_path_for_logging(path)
        assert "\n" not in result

    def test_malformed_path(self) -> None:
        """Test that malformed paths don't cause crashes."""
        result = sanitize_path_for_logging("not\x00a\x01valid\x02path")
        assert result is not None
        assert "\x00" not in result
        assert "\x01" not in result
