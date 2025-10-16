import contextlib
import logging
import os
import platform
import shutil
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

import weasyprint  # type: ignore
from fastapi import Depends, FastAPI, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.attachment_manager import AttachmentManager
from app.chromium_manager import ChromiumManager, get_chromium_manager
from app.form_parser import FormParser
from app.html_parser import HtmlParser
from app.notes_processor import NotesProcessor
from app.sanitization import sanitize_path_for_logging, sanitize_url_for_logging
from app.schemas import ChromiumMetricsSchema, HealthSchema, VersionSchema
from app.svg_processor import SvgProcessor


@contextlib.asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None]:  # noqa: ARG001
    """
    Manage the lifecycle of the Chromium browser for SVG to PNG conversion.

    This ensures a single persistent Chromium instance is started when the
    FastAPI application starts and properly cleaned up on shutdown.

    If Chromium fails to start, the application will not start and the
    service will terminate (fail-fast behavior for containerized environments).
    """
    chromium_manager = get_chromium_manager()
    logger = logging.getLogger(__name__)

    logger.info("Prepare Chromium browser for SVG conversion...")
    await chromium_manager.start()
    logger.info("Chromium browser prepared successfully")

    yield  # Application runs here

    try:
        logger.info("Stopping Chromium browser...")
        await chromium_manager.stop()
        logger.info("Chromium browser stopped successfully")
    except Exception as e:  # noqa: BLE001
        logger.error("Error stopping Chromium browser: %s", e)


logger = logging.getLogger(__name__)

app = FastAPI(
    title="WeasyPrint Service API",
    version="1.0.0",
    openapi_url="/static/openapi.json",
    docs_url="/api/docs",
    openapi_version="3.1.0",
    lifespan=lifespan,
)


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Monitoring Dashboard",
    description="Interactive real-time monitoring dashboard with charts and metrics visualization",
    operation_id="getDashboard",
    tags=["meta"],
)
async def dashboard() -> HTMLResponse:
    """
    Serve the monitoring dashboard HTML page.

    Returns:
        HTML page with real-time monitoring dashboard
    """
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    with dashboard_path.open("r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get(
    "/static/{file_path:path}",
    response_class=FileResponse,
    summary="Static Files",
    description="Serve static files (CSS, JS, etc.)",
    operation_id="getStaticFile",
    tags=["meta"],
    include_in_schema=False,
    response_model=None,
)
async def static_files(file_path: str) -> FileResponse | Response:
    """
    Serve static files from the static directory.

    Args:
        file_path: Path to the static file

    Returns:
        FileResponse: The requested static file
        Response: 404 Not Found if file doesn't exist or path is invalid

    Security:
        Validates that the requested file path is within the static directory
        to prevent path traversal attacks.
    """
    # Reject paths with directory traversal patterns
    if ".." in file_path or file_path.startswith("/"):
        logger.warning("Rejected potentially malicious file path")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    static_dir = Path(__file__).parent / "static"
    full_path = (static_dir / file_path).resolve()

    # Security check: ensure the resolved path is within static directory
    try:
        if not full_path.is_relative_to(static_dir.resolve()):
            logger.warning("Attempted access to file outside static directory")
            return Response(status_code=status.HTTP_404_NOT_FOUND)
    except ValueError:
        # is_relative_to can raise ValueError on some platforms
        logger.warning("Invalid static file path provided")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    if not full_path.exists() or not full_path.is_file():
        logger.debug("Static file not found")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return FileResponse(full_path)


@app.get(
    "/health",
    summary="Health check",
    description="Returns health status with optional detailed metrics. Use ?detailed=true for JSON response with metrics.",
    operation_id="getHealth",
    tags=["meta"],
    response_model=None,
    responses={
        200: {
            "content": {
                "text/plain": {"example": "OK"},
                "application/json": {
                    "schema": HealthSchema.model_json_schema(),
                },
            },
            "description": "Service is healthy",
        },
        503: {
            "content": {
                "text/plain": {"example": "Service Unavailable"},
                "application/json": {
                    "schema": HealthSchema.model_json_schema(),
                },
            },
            "description": "Service is unhealthy",
        },
    },
)
async def health(
    chromium_manager: Annotated[ChromiumManager, Depends(get_chromium_manager)],
    detailed: bool = Query(False, description="Return detailed JSON response with metrics"),
) -> Response:
    """
    Health check endpoint that verifies service and Chromium browser status.

    Args:
        detailed: If True, returns detailed JSON response with metrics. If False, returns simple text response.

    Returns:
        - Simple mode: 200 with "OK" text or 503 with "Service Unavailable" text
        - Detailed mode: 200/503 with JSON containing status, metrics, and browser info

    Note: If Chromium is not healthy, the service should have failed to start.
    This endpoint primarily serves as a runtime health verification.
    """
    chromium_healthy = chromium_manager.health_check()

    if detailed:
        # Return detailed JSON response with metrics
        metrics_data = chromium_manager.get_metrics()
        health_response = HealthSchema(
            status="healthy" if chromium_healthy else "unhealthy",
            version=os.environ.get("WEASYPRINT_SERVICE_VERSION", "unknown"),
            weasyprint_version=weasyprint.__version__,
            chromium_running=chromium_manager.is_running(),
            chromium_version=chromium_manager.get_version(),
            health_monitoring_enabled=chromium_manager.health_check_enabled,
            metrics=ChromiumMetricsSchema(**metrics_data),  # type: ignore[arg-type]
        )
        # Return with appropriate status code
        status_code = 200 if chromium_healthy else 503
        return Response(
            content=health_response.model_dump_json(),
            media_type="application/json",
            status_code=status_code,
        )

    # Return simple text response
    if chromium_healthy:
        return Response("OK", media_type="text/plain", status_code=200)
    return Response("Service Unavailable", media_type="text/plain", status_code=503)


@app.get(
    "/version",
    response_model=VersionSchema,
    summary="Service version information",
    description="Returns versions of Python, WeasyPrint, the service itself, build timestamp, and Chromium.",
    operation_id="getVersion",
    tags=["meta"],
)
async def version(chromium_manager: Annotated[ChromiumManager, Depends(get_chromium_manager)]) -> dict[str, str | None]:
    """
    Get version information
    """
    logger.info("Version endpoint called")
    version_info = {
        "python": platform.python_version(),
        "weasyprint": weasyprint.__version__,
        "weasyprintService": os.environ.get("WEASYPRINT_SERVICE_VERSION"),
        "timestamp": os.environ.get("WEASYPRINT_SERVICE_BUILD_TIMESTAMP"),
        "chromium": chromium_manager.get_version(),
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
    chromium_manager: Annotated[ChromiumManager, Depends(get_chromium_manager)],
) -> Response:
    """
    Convert HTML content from the request body to a PDF document.
    """
    start_time = time.time()
    logger.info("HTML to PDF conversion requested")
    raw: bytes = await request.body()
    logger.debug("Received HTML body of size: %d bytes", len(raw))
    encoding: str = await __get_encoding(request, render.encoding)
    logger.debug("Using encoding: %s", encoding)
    try:
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None
        if base_url:
            logger.debug("Using base URL: %s", sanitize_url_for_logging(base_url))

        html = raw.decode(encoding)
        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)

        notes_processor = NotesProcessor()
        notes = notes_processor.replace_notes(parsed_html)

        # Use CDP-based async SVG processing
        svg_processor = SvgProcessor(chromium_manager=chromium_manager, device_scale_factor=render.scale_factor)
        parsed_html = await svg_processor.process_svg(parsed_html)

        processed_html = html_parser.serialize(parsed_html)

        logger.debug("Creating WeasyPrint HTML object with media_type=%s", render.media_type)
        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        logger.debug("Generating PDF with options: pdf_variant=%s, presentational_hints=%s, custom_metadata=%s", output.pdf_variant, render.presentational_hints, output.custom_metadata)
        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
        )
        logger.info("PDF generated successfully, size: %d bytes", len(output_pdf) if output_pdf else 0)

        output_pdf = notes_processor.process_pdf_with_notes(output_pdf, notes)

        # Record conversion success metrics
        duration_ms = (time.time() - start_time) * 1000
        chromium_manager._metrics.record_success(duration_ms)

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        logger.warning("Assertion error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        logger.warning("Encoding error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        logger.error("Unexpected error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
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
    chromium_manager: Annotated[ChromiumManager, Depends(get_chromium_manager)],
) -> Response:
    """
    Convert HTML to PDF and embed provided files as PDF attachments.

    Expects a multipart/form-data request where:
      - field 'html' contains the HTML content
      - remaining file parts are treated as attachments
    """
    start_time = time.time()
    logger.info("HTML to PDF with attachments conversion requested")
    tmpdir = tempfile.mkdtemp(prefix="weasyprint-attach-")
    logger.debug("Created temporary directory: %s", sanitize_path_for_logging(tmpdir, show_basename_only=False))
    try:
        encoding: str = await __get_encoding(request, render.encoding)
        base_url = unquote(render.base_url, encoding=encoding) if render.base_url else None

        form_parser = FormParser()
        form = await form_parser.parse(request)
        html = form_parser.html_from_form(form, encoding)
        files = form_parser.collect_files_from_form(form)
        logger.debug("Parsed form with %d file attachments", len(files))

        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)

        notes_processor = NotesProcessor()
        notes = notes_processor.replace_notes(parsed_html)

        # Use CDP-based async SVG processing
        svg_processor = SvgProcessor(chromium_manager=chromium_manager, device_scale_factor=render.scale_factor)
        parsed_html = await svg_processor.process_svg(parsed_html)

        attachment_manager = AttachmentManager()
        parsed_html, attachments = await attachment_manager.process_html_and_uploads(
            parsed_html=parsed_html,
            files=files,
            tmpdir=Path(tmpdir),
        )

        processed_html = html_parser.serialize(parsed_html)

        logger.debug("Creating WeasyPrint HTML object with media_type=%s", render.media_type)
        weasyprint_html = weasyprint.HTML(
            string=processed_html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        logger.debug("Generating PDF with options: pdf_variant=%s, presentational_hints=%s, custom_metadata=%s, attachments=%d", output.pdf_variant, render.presentational_hints, output.custom_metadata, len(attachments))
        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
            attachments=attachments,
        )
        logger.info("PDF with attachments generated successfully, size: %d bytes", len(output_pdf) if output_pdf else 0)

        output_pdf = notes_processor.process_pdf_with_notes(output_pdf, notes)

        # Record conversion success metrics
        duration_ms = (time.time() - start_time) * 1000
        chromium_manager._metrics.record_success(duration_ms)

        return await __create_response(output, output_pdf)

    except AssertionError as e:
        logger.warning("Assertion error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
        return __process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        logger.warning("Encoding error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
        return __process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        logger.error("Unexpected error in HTML conversion: %s", str(e), exc_info=True)
        chromium_manager._metrics.record_failure()
        return __process_error(e, "Unexpected error due converting to PDF", 500)
    finally:
        logger.debug("Cleaning up temporary directory: %s", sanitize_path_for_logging(tmpdir, show_basename_only=False))
        shutil.rmtree(tmpdir, ignore_errors=True)


async def __create_response(output: OutputOptions, output_pdf: bytes | None) -> Response:
    logger.debug("Creating response with filename: %s", output.file_name)
    response = Response(output_pdf, media_type="application/pdf", status_code=200)
    response.headers.append("Content-Disposition", f"attachment; filename={output.file_name}")
    response.headers.append("Python-Version", platform.python_version())
    response.headers.append("Weasyprint-Version", weasyprint.__version__)
    response.headers.append("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION", ""))
    return response


def __process_error(e: Exception, err_msg: str, status: int) -> Response:
    logger.exception("%s: %s", err_msg, str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), media_type="plain/text", status_code=status)
