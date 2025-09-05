import contextlib
import logging
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

import uvicorn
import weasyprint  # type: ignore
from fastapi import Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel
from starlette.datastructures import FormData, UploadFile

from app.attachment_manager import AttachmentManager
from app.html_parser import HtmlParser
from app.schemas import VersionSchema
from app.svg_processor import SvgProcessor

app = FastAPI(
    title="WeasyPrint Service API",
    version="1.0.0",
    openapi_url="/static/openapi.json",
    docs_url="/api/docs",
    openapi_version="3.1.0",
)


def _get_int_env(name: str, default: int) -> int:
    """Read positive int from env var or fall back to default."""
    try:
        value = int(os.environ.get(name, str(default)))
        return max(0, value)
    except Exception:
        return default


async def _parse_form_with_limits(request: Request) -> FormData:
    max_files_env = _get_int_env("FORM_MAX_FILES", 1000)
    max_fields_env = _get_int_env("FORM_MAX_FIELDS", 1000)
    max_part_size_env = _get_int_env("FORM_MAX_PART_SIZE", 10 * 1024 * 1024)
    return await request.form(
        max_files=max_files_env,
        max_fields=max_fields_env,
        max_part_size=max_part_size_env,
    )


def _html_from_form(form: FormData, encoding: str) -> str:
    html_field = form.get("html")
    if html_field is None:
        raise AssertionError("Missing 'html' form field")
    return html_field.decode(encoding) if isinstance(html_field, bytes) else str(html_field)


def _collect_files_from_form(form: FormData) -> list[UploadFile]:
    files: list[UploadFile] = []
    seen_names: set[str] = set()
    for v in form.getlist("files"):
        if isinstance(v, UploadFile):
            name = Path(v.filename).name if v.filename else "attachment.bin"
            if name not in seen_names:
                files.append(v)
                seen_names.add(name)
    return files


@app.get(
    "/version",
    response_model=VersionSchema,
    summary="Service version information",
    description="Returns versions of Python, WeasyPrint, the service itself, build timestamp, and Chromium.",
    operation_id="getVersion",
    tags=["meta"],
)
async def version() -> dict[str, str | None]:
    """
    Get version information
    """
    return {
        "python": platform.python_version(),
        "weasyprint": weasyprint.__version__,
        "weasyprintService": os.environ.get("WEASYPRINT_SERVICE_VERSION"),
        "timestamp": os.environ.get("WEASYPRINT_SERVICE_BUILD_TIMESTAMP"),
        "chromium": os.environ.get("WEASYPRINT_SERVICE_CHROMIUM_VERSION"),
    }


class RenderOptions(BaseModel):
    """
    Options controlling how WeasyPrint renders the input HTML/CSS before PDF generation.

    Attributes:
        encoding: Text encoding used to decode the incoming HTML request body.
        media_type: CSS media type to apply when rendering ("print" or "screen" are typical).
        presentational_hints: Whether to honor presentational HTML attributes as CSS hints.
        base_url: Base URL used to resolve relative links (e.g., stylesheets, images).
        scale_factor: Device scale factor used for SVG/PNG rendering. If not provided, falls back to DEVICE_SCALE_FACTOR env var.
    """

    encoding: str = "utf-8"
    media_type: str = "print"
    presentational_hints: bool = False
    base_url: str | None = None
    scale_factor: float | None = None


class OutputOptions(BaseModel):
    """
    Options controlling characteristics of the produced PDF file.

    Attributes:
        file_name: The filename suggested in the Content-Disposition header.
        pdf_variant: PDF profile/variant passed to WeasyPrint (e.g., 'pdf/a-2b'); None for default.
        custom_metadata: Whether to include custom metadata in the generated PDF.
    """

    file_name: str = "converted-document.pdf"
    pdf_variant: str | None = None
    custom_metadata: bool = False


def get_render_options(
    encoding: str = Query(
        "utf-8",
        title="Encoding",
        description="Text encoding used to decode the incoming HTML body (e.g., utf-8).",
    ),
    media_type: str = Query(
        "print",
        title="CSS Media Type",
        description="CSS media type to apply when rendering (e.g., 'print' or 'screen').",
    ),
    presentational_hints: bool = Query(
        False,
        title="Presentational Hints",
        description="Honor presentational HTML attributes as CSS hints.",
    ),
    base_url: str | None = Query(
        None,
        title="Base URL",
        description="Base URL used to resolve relative links (stylesheets, images).",
    ),
    scale_factor: float | None = Query(
        None,
        title="Scale Factor",
        description="Device scale factor used for SVG/PNG rendering. Overrides DEVICE_SCALE_FACTOR if provided.",
    ),
) -> RenderOptions:
    return RenderOptions(
        encoding=encoding,
        media_type=media_type,
        presentational_hints=presentational_hints,
        base_url=base_url,
        scale_factor=scale_factor,
    )


def get_output_options(
    file_name: str = Query(
        "converted-document.pdf",
        title="Output File Name",
        description="Filename suggested in the Content-Disposition header.",
    ),
    pdf_variant: str | None = Query(
        None,
        title="PDF Variant",
        description="PDF profile/variant passed to WeasyPrint (e.g., 'pdf/a-2b').",
    ),
    custom_metadata: bool = Query(
        False,
        title="Custom Metadata",
        description="Include custom metadata in the generated PDF.",
    ),
) -> OutputOptions:
    return OutputOptions(
        file_name=file_name,
        pdf_variant=pdf_variant,
        custom_metadata=custom_metadata,
    )


@app.post(
    "/convert/html",
    responses={400: {"content": {"text/plain": {}}, "description": "Invalid Input"}, 500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"}},
    summary="Convert HTML to PDF",
    description="Accepts raw HTML in the request body and returns a generated PDF.",
    operation_id="convert_html_post",
    tags=["convert"],
)
async def convert_html(
    request: Request,
    render: Annotated[RenderOptions, Depends(get_render_options)],
    output: Annotated[OutputOptions, Depends(get_output_options)],
) -> Response:
    """
    Convert HTML content from the request body to a PDF document.
    """
    raw: bytes = await request.body()
    encoding: str = await __get_encoding(request, render.encoding)
    try:
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None

        html = raw.decode(encoding)
        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)
        parsed_html = SvgProcessor(device_scale_factor=render.scale_factor).process_svg(parsed_html)
        processed_html = html_parser.serialize(parsed_html)

        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
        )

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return __process_error(e, "Unexpected error due converting to PDF", 500)


async def __get_encoding(request: Request, encoding: str | None) -> str:
    ct = request.headers.get("content-type", "")
    charset = None
    with contextlib.suppress(Exception):
        if "charset=" in ct:
            charset = ct.split("charset=", 1)[1].split(";", 1)[0].strip()
    return charset or encoding or "utf-8"


@app.post(
    "/convert/html-with-attachments",
    responses={
        400: {"content": {"text/plain": {}}, "description": "Invalid Input"},
        500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"},
    },
    summary="Convert HTML to PDF with attachments",
    description="Accepts HTML as a form field and optional files to be embedded as PDF attachments.",
    operation_id="convert_html_with_attachments_post",
    tags=["convert"],
)
async def convert_html_with_attachments(
    request: Request,
    render: Annotated[RenderOptions, Depends(get_render_options)],
    output: Annotated[OutputOptions, Depends(get_output_options)],
) -> Response:
    """
    Convert HTML to PDF and embed provided files as PDF attachments.

    Expects a multipart/form-data request where:
      - field 'html' contains the HTML content
      - remaining file parts are treated as attachments
    """
    tmpdir = tempfile.mkdtemp(prefix="weasyprint-attach-")
    try:
        encoding: str = await __get_encoding(request, render.encoding)
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None

        form = await _parse_form_with_limits(request)
        html = _html_from_form(form, encoding)
        files = _collect_files_from_form(form)

        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)
        parsed_html = SvgProcessor(device_scale_factor=render.scale_factor).process_svg(parsed_html)

        attachment_manager = AttachmentManager()
        parsed_html, attachments = await attachment_manager.process_html_and_uploads(
            parsed_html=parsed_html,
            files=files,
            tmpdir=Path(tmpdir),
        )

        processed_html = html_parser.serialize(parsed_html)

        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
            attachments=attachments,
        )

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return __process_error(e, "Unexpected error due converting to PDF", 500)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def __create_response(output: OutputOptions, output_pdf: bytes | None) -> Response:
    response = Response(output_pdf, media_type="application/pdf", status_code=200)
    response.headers.append("Content-Disposition", f"attachment; filename={output.file_name}")
    response.headers.append("Python-Version", platform.python_version())
    response.headers.append("Weasyprint-Version", weasyprint.__version__)
    response.headers.append("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION", ""))
    return response


def __process_error(e: Exception, err_msg: str, status: int) -> Response:
    logging.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), media_type="plain/text", status_code=status)


def start_server(port: int) -> None:
    uvicorn.run(app=app, host="", port=port)
