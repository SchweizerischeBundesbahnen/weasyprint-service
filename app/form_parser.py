from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starlette.datastructures import FormData, UploadFile

if TYPE_CHECKING:  # noqa: TCH004
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
        self.max_files = max_files or self._get_int_env("FORM_MAX_FILES", 1000)
        self.max_fields = max_fields or self._get_int_env("FORM_MAX_FIELDS", 1000)
        self.max_part_size = max_part_size or self._get_int_env("FORM_MAX_PART_SIZE", 10 * 1024 * 1024)

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
        return await request.form(
            max_files=self.max_files,
            max_fields=self.max_fields,
            max_part_size=self.max_part_size,
        )

    @staticmethod
    def html_from_form(form: FormData, encoding: str = "utf-8") -> str:
        """
        Extract the "html" field from the form and decode if needed.
        """
        html_field = form.get("html")
        if html_field is None:
            raise AssertionError(400, "Missing html form field")
        return html_field.decode(encoding) if isinstance(html_field, bytes) else str(html_field)

    @staticmethod
    def collect_files_from_form(form: FormData) -> list[UploadFile]:
        """
        Collect files from the "files" field.
        """
        files: list[UploadFile] = []
        for v in form.getlist("files"):
            if isinstance(v, UploadFile):
                if not v.filename:
                    v.filename = "attachment.bin"
                files.append(v)
        return files
