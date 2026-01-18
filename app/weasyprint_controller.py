from __future__ import annotations

import contextlib
import logging
import os
import platform
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import unquote

import weasyprint  # type: ignore
from fastapi import Depends, FastAPI, Query, Request, Response

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from bs4 import BeautifulSoup

from fastapi.responses import HTMLResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from app.attachment_manager import AttachmentManager
from app.chromium_manager import ChromiumManager, get_chromium_manager
from app.form_parser import FormParser
from app.html_parser import HtmlParser
from app.metrics_server import MetricsServer, get_metrics_port, is_metrics_server_enabled
from app.notes_processor import NotesProcessor
from app.prometheus_metrics import (
    increment_pdf_generation_failure,
    increment_pdf_generation_success,
    pdf_generation_duration_seconds,
)
from app.sanitization import sanitize_path_for_logging, sanitize_url_for_logging
from app.schemas import ChromiumMetricsSchema, HealthSchema, VersionSchema
from app.svg_processor import SvgProcessor
from app.vsdx_processor import VsdxProcessor


@contextlib.asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None]:  # noqa: ARG001
    """
    Manage the lifecycle of the Chromium browser and metrics server.

    This ensures a single persistent Chromium instance is started when the
    FastAPI application starts and properly cleaned up on shutdown.

    If Chromium fails to start, the application will not start and the
    service will terminate (fail-fast behavior for containerized environments).

    The metrics server is started on a dedicated port (default: 9180) for
    security isolation from the main application API.
    """
    chromium_manager = get_chromium_manager()
    lifespan_logger = logging.getLogger(__name__)

    lifespan_logger.info("Prepare Chromium browser for SVG conversion...")
    await chromium_manager.start()
    lifespan_logger.info("Chromium browser prepared successfully")

    # Start metrics server if enabled
    metrics_server: MetricsServer | None = None
    if is_metrics_server_enabled():
        metrics_port = get_metrics_port()
        metrics_server = MetricsServer(port=metrics_port)
        await metrics_server.start()

    yield  # Application runs here

    # Stop metrics server
    if metrics_server:
        try:
            await metrics_server.stop()
        except Exception as e:  # noqa: BLE001
            lifespan_logger.error("Error stopping metrics server: %s", e)

    try:
        lifespan_logger.info("Stopping Chromium browser...")
        await chromium_manager.stop()
        lifespan_logger.info("Chromium browser stopped successfully")
    except Exception as e:  # noqa: BLE001
        lifespan_logger.error("Error stopping Chromium browser: %s", e)


logger = logging.getLogger(__name__)

app = FastAPI(
    title="WeasyPrint Service API",
    version="1.0.0",
    openapi_url="/static/openapi.json",
    docs_url="/api/docs",
    openapi_version="3.1.0",
    lifespan=lifespan,
)

# Initialize Prometheus Instrumentator for automatic HTTP metrics
# Note: We instrument but don't expose() - metrics are served on a dedicated port via metrics_server
Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    env_var_name="ENABLE_METRICS",
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
    Serve the monitoring dashboard HTML page with theme configuration.

    Theme can be configured via DASHBOARD_THEME environment variable.
    Supported values: 'light' (default), 'dark'

    Returns:
        HTML page with real-time monitoring dashboard
    """
    dashboard_path = Path(__file__).parent / "resources" / "dashboard.html"
    with dashboard_path.open("r", encoding="utf-8") as f:
        html_content = f.read()

    # Get theme from environment variable (default to 'light')
    theme = os.environ.get("DASHBOARD_THEME", "light").lower()
    if theme not in ("light", "dark"):
        logger.warning("Invalid DASHBOARD_THEME value '%s', defaulting to 'light'", theme)
        theme = "light"

    # Replace placeholder with actual theme value
    html_content = html_content.replace("{{DASHBOARD_THEME}}", theme)

    return HTMLResponse(content=html_content)


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
        html = raw.decode(encoding)
        output_pdf = await __process_html_to_pdf(html, render, output, chromium_manager)
        response = await __create_response(output, output_pdf)
        __record_conversion_metrics(chromium_manager, start_time, success=True)
        return response
    except Exception as e:
        return __handle_conversion_error(e, chromium_manager, start_time)


async def __get_encoding(request: Request, encoding: str | None) -> str:
    ct = request.headers.get("content-type", "")
    charset = None
    with contextlib.suppress(Exception):
        if "charset=" in ct:
            charset = ct.split("charset=", 1)[1].split(";", 1)[0].strip()
    return charset or encoding or "utf-8"


async def __process_html_to_pdf(
    html: str,
    render: RenderOptions,
    output: OutputOptions,
    chromium_manager: ChromiumManager,
    attachments: list | None = None,
) -> bytes:
    """
    Common logic for HTML to PDF conversion with SVG processing.

    This function handles the complete pipeline from raw HTML string to final PDF:
    - Parses HTML
    - Processes notes
    - Converts SVG to PNG
    - Generates PDF with WeasyPrint
    - Applies note processing to PDF

    Args:
        html: HTML content to convert
        render: Rendering options
        output: Output options
        chromium_manager: Chromium manager instance
        attachments: Optional list of PDF attachments

    Returns:
        Generated PDF as bytes
    """
    html_parser = HtmlParser()
    parsed_html = html_parser.parse(html)

    return await __generate_pdf_from_parsed_html(parsed_html, html_parser, render, output, chromium_manager, attachments)


async def __generate_pdf_from_parsed_html(
    parsed_html: BeautifulSoup,
    html_parser: HtmlParser,
    render: RenderOptions,
    output: OutputOptions,
    chromium_manager: ChromiumManager,
    attachments: list | None = None,
) -> bytes:
    """
    Generate PDF from already-parsed HTML element tree.

    This helper function contains the common PDF generation logic that can be used
    by both convert_html and convert_html_with_attachments endpoints.

    Args:
        parsed_html: Pre-parsed HTML element tree
        html_parser: HtmlParser instance for serialization
        render: Rendering options
        output: Output options
        chromium_manager: Chromium manager instance
        attachments: Optional list of PDF attachments

    Returns:
        Generated PDF as bytes
    """
    notes_processor = NotesProcessor()
    notes = notes_processor.replace_notes(parsed_html)

    # Use CDP-based async SVG processing
    svg_processor = SvgProcessor(chromium_manager=chromium_manager, device_scale_factor=render.scale_factor)
    parsed_html = await svg_processor.process_svg(parsed_html)

    # Use LibreOffice-based async VSDX processing
    vsdx_processor = VsdxProcessor()
    parsed_html = await vsdx_processor.process_vsdx(parsed_html)

    processed_html = html_parser.serialize(parsed_html)

    base_url = unquote(render.base_url, render.encoding) if render.base_url else None
    if base_url:
        logger.debug("Using base URL: %s", sanitize_url_for_logging(base_url))

    logger.debug("Creating WeasyPrint HTML object with media_type=%s", render.media_type)
    weasyprint_html = weasyprint.HTML(
        string=processed_html,
        base_url=base_url,
        media_type=render.media_type,
        encoding=render.encoding,
    )

    logger.debug(
        "Generating PDF with options: pdf_variant=%s, presentational_hints=%s, custom_metadata=%s%s",
        output.pdf_variant,
        render.presentational_hints,
        output.custom_metadata,
        f", attachments={len(attachments)}" if attachments else "",
    )

    output_pdf = weasyprint_html.write_pdf(
        target=None,  # Explicitly set to default (returns bytes); included for clarity
        pdf_variant=output.pdf_variant,
        presentational_hints=render.presentational_hints,
        custom_metadata=output.custom_metadata,
        attachments=attachments,
    )

    logger.info("PDF generated successfully, size: %d bytes", len(output_pdf))
    return notes_processor.process_pdf_with_notes(output_pdf, notes)


def __record_conversion_metrics(chromium_manager: ChromiumManager, start_time: float, success: bool) -> None:
    """
    Record conversion metrics for both internal tracking and Prometheus.

    Args:
        chromium_manager: Chromium manager instance
        start_time: Conversion start time from time.time()
        success: Whether conversion succeeded
    """
    duration_ms = (time.time() - start_time) * 1000

    if success:
        chromium_manager._metrics.record_success(duration_ms)
        increment_pdf_generation_success(duration_ms / 1000.0)  # Convert ms to seconds
    else:
        chromium_manager._metrics.record_failure()
        increment_pdf_generation_failure()


def __handle_conversion_error(e: Exception, chromium_manager: ChromiumManager, start_time: float) -> Response:
    """
    Handle conversion errors with appropriate logging and metrics.

    Args:
        e: Exception that occurred
        chromium_manager: Chromium manager instance
        start_time: Conversion start time from time.time()

    Returns:
        Error response with appropriate status code
    """
    duration_ms = (time.time() - start_time) * 1000
    chromium_manager._metrics.record_failure()
    increment_pdf_generation_failure()
    pdf_generation_duration_seconds.observe(duration_ms / 1000.0)

    if isinstance(e, AssertionError):
        logger.warning("Assertion error in HTML conversion: %s", str(e), exc_info=True)
        return __process_error(e, "Assertion error, check the request body html", 400)
    if isinstance(e, (UnicodeDecodeError, LookupError)):
        logger.warning("Encoding error in HTML conversion: %s", str(e), exc_info=True)
        return __process_error(e, "Cannot decode request html body", 400)

    logger.error("Unexpected error in HTML conversion: %s", str(e), exc_info=True)
    return __process_error(e, "Unexpected error due converting to PDF", 500)


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

        form_parser = FormParser()
        form = await form_parser.parse(request)
        html = form_parser.html_from_form(form, encoding)
        files = form_parser.collect_files_from_form(form)
        logger.debug("Parsed form with %d file attachments", len(files))

        # Process attachments and update HTML with attachment references
        attachment_manager = AttachmentManager()
        html_parser = HtmlParser()
        parsed_html = html_parser.parse(html)
        parsed_html, attachments = await attachment_manager.process_html_and_uploads(
            parsed_html=parsed_html,
            files=files,
            tmpdir=Path(tmpdir),
        )

        # Use common PDF generation logic (handles notes, SVG, WeasyPrint)
        output_pdf = await __generate_pdf_from_parsed_html(parsed_html, html_parser, render, output, chromium_manager, attachments)
        response = await __create_response(output, output_pdf)
        __record_conversion_metrics(chromium_manager, start_time, success=True)
        return response
    except Exception as e:
        return __handle_conversion_error(e, chromium_manager, start_time)
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
