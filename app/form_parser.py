from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from starlette.datastructures import FormData, UploadFile

if TYPE_CHECKING:
    from fastapi import Request

logger = logging.getLogger(__name__)


class FormParser:
    """
    Helper class to parse multipart form data with configurable limits
    from environment variables.
    """

    def __init__(
        self,
        max_files: int | None = None,
        max_fields: int | None = None,
        max_part_size: int | None = None,
    ) -> None:
        self.max_files = max_files or self._get_int_env("FORM_MAX_FILES", 1000)
        self.max_fields = max_fields or self._get_int_env("FORM_MAX_FIELDS", 1000)
        self.max_part_size = max_part_size or self._get_int_env("FORM_MAX_PART_SIZE", 10 * 1024 * 1024)
        logger.debug("FormParser initialized with limits - max_files: %d, max_fields: %d, max_part_size: %d", self.max_files, self.max_fields, self.max_part_size)

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        """Read positive int from env var or fall back to default."""
        try:
            value = int(os.environ.get(name, str(default)))
            return max(0, value)
        except (ValueError, TypeError):
            return default

    async def parse(self, request: Request) -> FormData:
        """
        Parse the form with configured limits.
        """
        logger.debug("Parsing multipart form data with configured limits")
        form_data = await request.form(
            max_files=self.max_files,
            max_fields=self.max_fields,
            max_part_size=self.max_part_size,
        )
        logger.info("Parsed form data successfully")
        return form_data

    @staticmethod
    def html_from_form(form: FormData, encoding: str = "utf-8") -> str:
        """
        Extract the "html" field from the form and decode if needed.
        """
        logger.debug("Extracting HTML field from form with encoding: %s", encoding)
        html_field = form.get("html")
        if html_field is None:
            logger.error('Required form field "html" is missing from multipart request')
            raise AssertionError('Required form field "html" is missing from multipart request')
        html_content = html_field.decode(encoding) if isinstance(html_field, bytes) else str(html_field)
        logger.debug("Extracted HTML content, size: %d characters", len(html_content))
        return html_content

    @staticmethod
    def _sanitize_filename_for_logging(filename: str | None) -> str:
        """Sanitize filename for safe logging by removing control characters."""
        if not filename:
            return "unknown"
        # Remove control characters and newlines that could break log parsing
        return "".join(c if c.isprintable() and c not in "\n\r" else "_" for c in filename)

    @staticmethod
    def collect_files_from_form(form: FormData) -> list[UploadFile]:
        """
        Collect files from the "files" field.
        """
        logger.debug("Collecting files from form data")
        files: list[UploadFile] = []
        for v in form.getlist("files"):
            if isinstance(v, UploadFile):
                if not v.filename:
                    v.filename = "attachment.bin"
                    logger.debug("Assigned default filename: attachment.bin")
                files.append(v)
                logger.debug("Collected file: %s", FormParser._sanitize_filename_for_logging(v.filename))
        logger.info("Collected %d files from form", len(files))
        return files
