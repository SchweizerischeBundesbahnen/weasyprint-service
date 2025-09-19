from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from starlette.datastructures import FormData, UploadFile

if TYPE_CHECKING:  # ruff: noqa: TCH004
    from fastapi import Request


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
        self.logger = logging.getLogger(__name__)
        self.max_files = max_files or self._get_int_env("FORM_MAX_FILES", 1000)
        self.max_fields = max_fields or self._get_int_env("FORM_MAX_FIELDS", 1000)
        self.max_part_size = max_part_size or self._get_int_env("FORM_MAX_PART_SIZE", 10 * 1024 * 1024)
        self.logger.debug("FormParser initialized with limits: max_files=%d, max_fields=%d, max_part_size=%d",
                          self.max_files, self.max_fields, self.max_part_size)

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
        self.logger.debug("Parsing multipart form with limits")
        try:
            form = await request.form(
                max_files=self.max_files,
                max_fields=self.max_fields,
                max_part_size=self.max_part_size,
            )
            self.logger.debug("Form parsed successfully")
            return form
        except Exception as e:
            self.logger.error("Error parsing form: %s", str(e))
            raise

    def html_from_form(self, form: FormData, encoding: str = "utf-8") -> str:
        """
        Extract the "html" field from the form and decode if needed.
        """
        html_field = form.get("html")
        if html_field is None:
            self.logger.error("Missing html form field in multipart form")
            raise AssertionError(400, "Missing html form field")

        if isinstance(html_field, bytes):
            self.logger.debug("Decoding HTML field from bytes with encoding: %s", encoding)
            result = html_field.decode(encoding)
        else:
            self.logger.debug("Converting HTML field to string")
            result = str(html_field)

        self.logger.debug("Extracted HTML field of length: %d", len(result))
        return result

    def collect_files_from_form(self, form: FormData) -> list[UploadFile]:
        """
        Collect files from the "files" field.
        """
        files: list[UploadFile] = []
        file_list = form.getlist("files")
        self.logger.debug("Processing %d entries from 'files' field", len(file_list))

        for v in file_list:
            if isinstance(v, UploadFile):
                if not v.filename:
                    v.filename = "attachment.bin"
                    self.logger.debug("Assigned default filename to upload: attachment.bin")
                else:
                    self.logger.debug("Found uploaded file: %s", v.filename)
                files.append(v)

        self.logger.info("Collected %d files from form", len(files))
        return files
