import contextlib
import logging
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

import weasyprint  # type: ignore
from fastapi import Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel

from app.attachment_manager import AttachmentManager
from app.form_parser import FormParser
from app.html_parser import HtmlParser
from app.schemas import VersionSchema
from app.svg_processor import SvgProcessor

logger = logging.getLogger(__name__)

app = FastAPI(
    title="WeasyPrint Service API",
    version="1.0.0",
    openapi_url="/static/openapi.json",
    docs_url="/api/docs",
    openapi_version="3.1.0",
)


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
    logger.info("Version endpoint called")
    version_info = {
        "python": platform.python_version(),
        "weasyprint": weasyprint.__version__,
        "weasyprintService": os.environ.get("WEASYPRINT_SERVICE_VERSION"),
        "timestamp": os.environ.get("WEASYPRINT_SERVICE_BUILD_TIMESTAMP"),
        "chromium": os.environ.get("WEASYPRINT_SERVICE_CHROMIUM_VERSION"),
    }
    logger.debug("Version info: %s", version_info)
    return version_info


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
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF file generated from the provided HTML"},
        400: {"content": {"text/plain": {}}, "description": "Invalid Input"},
        500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"},
    },
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
    logger.info("HTML to PDF conversion requested")
    logger.debug("Render options: encoding=%s, media_type=%s, base_url=%s, scale_factor=%s",
                 render.encoding, render.media_type, render.base_url, render.scale_factor)
    logger.debug("Output options: file_name=%s, pdf_variant=%s, custom_metadata=%s",
                 output.file_name, output.pdf_variant, output.custom_metadata)

    raw: bytes = await request.body()
    logger.debug("Received HTML body of %d bytes", len(raw))

    encoding: str = await __get_encoding(request, render.encoding)
    try:
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None

        html = raw.decode(encoding)
        logger.debug("Successfully decoded HTML with encoding: %s", encoding)

        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)
        logger.debug("HTML parsed successfully")

        parsed_html = SvgProcessor(device_scale_factor=render.scale_factor).process_svg(parsed_html)
        logger.debug("SVG processing completed")

        processed_html = html_parser.serialize(parsed_html)
        logger.debug("HTML serialization completed")

        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        logger.debug("WeasyPrint HTML object created")

        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
        )
        logger.info("PDF generation successful, size: %d bytes", len(output_pdf) if output_pdf else 0)

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        logger.warning("Assertion error during HTML conversion: %s", str(e))
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        logger.warning("Encoding error during HTML conversion: %s", str(e))
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        logger.error("Unexpected error during HTML to PDF conversion: %s", str(e), exc_info=True)
        return __process_error(e, "Unexpected error due converting to PDF", 500)


async def __get_encoding(request: Request, encoding: str | None) -> str:
    ct = request.headers.get("content-type", "")
    charset = None
    with contextlib.suppress(Exception):
        if "charset=" in ct:
            charset = ct.split("charset=", 1)[1].split(";", 1)[0].strip()
            logger.debug("Extracted charset from content-type header: %s", charset)
    result_encoding = charset or encoding or "utf-8"
    logger.debug("Using encoding: %s", result_encoding)
    return result_encoding


@app.post(
    "/convert/html-with-attachments",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF file generated from the provided HTML (with optional attachments)"},
        400: {"content": {"text/plain": {}}, "description": "Invalid Input"},
        500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"},
    },
    summary="Convert HTML to PDF with attachments",
    description="Accepts HTML as a form field and optional files to be embedded as PDF attachments.",
    operation_id="convert_html_with_attachments_post",
    tags=["convert"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "multipart/form-data with form fields: html — a string containing HTML; files — one or more file attachments. The html field is required. The files field is optional.",
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "html": {"type": "string", "description": "HTML document content. Can be provided as a regular text form field.", "example": "<html><body><h1>Hello</h1></body></html>"},
                            "files": {
                                "type": "array",
                                "description": "List of files to be embedded into the resulting PDF as attachments. Submit multiple form parts with the same name 'files'.",
                                "items": {"type": "string", "format": "binary"},
                            },
                        },
                        "required": ["html"],
                    }
                }
            },
        }
    },
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
    logger.info("HTML to PDF conversion with attachments requested")
    logger.debug("Render options: encoding=%s, media_type=%s, base_url=%s, scale_factor=%s",
                 render.encoding, render.media_type, render.base_url, render.scale_factor)
    logger.debug("Output options: file_name=%s, pdf_variant=%s, custom_metadata=%s",
                 output.file_name, output.pdf_variant, output.custom_metadata)

    tmpdir = tempfile.mkdtemp(prefix="weasyprint-attach-")
    logger.debug("Created temporary directory: %s", tmpdir)
    try:
        encoding: str = await __get_encoding(request, render.encoding)
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None

        form_parser = FormParser()
        form = await form_parser.parse(request)
        logger.debug("Multipart form parsed successfully")

        html = form_parser.html_from_form(form, encoding)
        logger.debug("Extracted HTML from form")

        files = form_parser.collect_files_from_form(form)
        logger.debug("Collected %d file attachments from form", len(files))

        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)
        logger.debug("HTML parsed successfully")

        parsed_html = SvgProcessor(device_scale_factor=render.scale_factor).process_svg(parsed_html)
        logger.debug("SVG processing completed")

        attachment_manager = AttachmentManager()
        parsed_html, attachments = await attachment_manager.process_html_and_uploads(
            parsed_html=parsed_html,
            files=files,
            tmpdir=Path(tmpdir),
        )
        logger.debug("Processed %d attachments", len(attachments))

        processed_html = html_parser.serialize(parsed_html)
        logger.debug("HTML serialization completed")

        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        logger.debug("WeasyPrint HTML object created")

        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
            attachments=attachments,
        )
        logger.info("PDF with attachments generation successful, size: %d bytes", len(output_pdf) if output_pdf else 0)

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        logger.warning("Assertion error during HTML with attachments conversion: %s", str(e))
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        logger.warning("Encoding error during HTML with attachments conversion: %s", str(e))
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        logger.error("Unexpected error during HTML to PDF with attachments conversion: %s", str(e), exc_info=True)
        return __process_error(e, "Unexpected error due converting to PDF", 500)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.debug("Cleaned up temporary directory: %s", tmpdir)


async def __create_response(output: OutputOptions, output_pdf: bytes | None) -> Response:
    response = Response(output_pdf, media_type="application/pdf", status_code=200)
    response.headers.append("Content-Disposition", f"attachment; filename={output.file_name}")
    response.headers.append("Python-Version", platform.python_version())
    response.headers.append("Weasyprint-Version", weasyprint.__version__)
    response.headers.append("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION", ""))
    logger.debug("Response created with file name: %s", output.file_name)
    return response


def __process_error(e: Exception, err_msg: str, status: int) -> Response:
    logger.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), media_type="plain/text", status_code=status)
