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
from fastapi import Body, Depends, FastAPI, File, Form, Query, Response, UploadFile
from pydantic import BaseModel

from app import (
    attachment_utils,  # type: ignore
    svg_utils,  # type: ignore
)
from app.schemas import VersionSchema

app = FastAPI(openapi_url="/static/openapi.json", docs_url="/api/docs")


@app.get("/version", response_model=VersionSchema)
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
    """

    encoding: str = "utf-8"
    media_type: str = "print"
    presentational_hints: bool = False
    base_url: str | None = None


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
    encoding: str = Query("utf-8"),
    media_type: str = Query("print"),
    presentational_hints: bool = Query(False),
    base_url: str | None = Query(None),
) -> RenderOptions:
    return RenderOptions(
        encoding=encoding,
        media_type=media_type,
        presentational_hints=presentational_hints,
        base_url=base_url,
    )


def get_output_options(
    file_name: str = Query("converted-document.pdf"),
    pdf_variant: str | None = Query(None),
    custom_metadata: bool = Query(False),
) -> OutputOptions:
    return OutputOptions(
        file_name=file_name,
        pdf_variant=pdf_variant,
        custom_metadata=custom_metadata,
    )


@app.post(
    "/convert/html",
    responses={400: {"content": {"text/plain": {}}, "description": "Invalid Input"}, 500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"}},
)
async def convert_html(
    render: Annotated[RenderOptions, Depends(get_render_options)],
    output: Annotated[OutputOptions, Depends(get_output_options)],
    html: str = Body(..., media_type="text/html"),
) -> Response:
    """
    Convert HTML to PDF
    """
    try:
        base_url = unquote(render.base_url, encoding=render.encoding) if render.base_url else None

        html = html if render.encoding.lower() == "utf-8" else html.encode("utf-8").decode(render.encoding, errors="strict")
        html = svg_utils.process_svg(html)

        weasyprint_html = weasyprint.HTML(
            string=html,
            base_url=base_url,
            media_type=render.media_type,
            encoding=render.encoding,
        )
        output_pdf = weasyprint_html.write_pdf(
            pdf_variant=output.pdf_variant,
            presentational_hints=render.presentational_hints,
            custom_metadata=output.custom_metadata,
        )

        response = Response(output_pdf, media_type="application/pdf", status_code=200)
        response.headers.append("Content-Disposition", f"attachment; filename={output.file_name}")
        response.headers.append("Python-Version", platform.python_version())
        response.headers.append("Weasyprint-Version", weasyprint.__version__)
        response.headers.append("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION", ""))
        return response

    except AssertionError as e:
        return process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return process_error(e, "Unexpected error due converting to PDF", 500)


@app.post(
    "/convert/html-with-attachments",
    responses={
        400: {"content": {"text/plain": {}}, "description": "Invalid Input"},
        500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"},
    },
)
async def convert_html_with_attachments(
    render: Annotated[RenderOptions, Depends(get_render_options)],
    output: Annotated[OutputOptions, Depends(get_output_options)],
    html: str = Form(...),
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    """
    Convert HTML to PDF and embed provided files as PDF attachments.
    """
    tmpdir = tempfile.mkdtemp(prefix="weasyprint-attach-")
    try:
        base_url = unquote(render.base_url, encoding=render.encoding) if render.base_url else None

        # html from request body
        html = html if render.encoding.lower() == "utf-8" else html.encode("utf-8").decode(render.encoding, errors="strict")
        html = svg_utils.process_svg(html)

        # 1. find names referenced in HTML via rel="attachment"
        referenced: set[str] = attachment_utils.find_referenced_attachment_names(html)
        # 2. persist uploads into tmpdir and get mapping {name -> Path}
        name_to_path: dict[str, Path] = await attachment_utils.save_uploads_to_tmpdir(files, Path(tmpdir))
        # 3. build attachments only for files NOT referenced in HTML
        attachments: list[weasyprint.Attachment] = attachment_utils.build_attachments_for_unreferenced(name_to_path, referenced)
        # 4. rewrite rel="attachment" hrefs to absolute file:// URIs pointing to saved files
        html = attachment_utils.rewrite_attachment_links_to_file_uri(html, name_to_path)

        weasyprint_html = weasyprint.HTML(
            string=html,
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

        response = Response(output_pdf, media_type="application/pdf", status_code=200)
        response.headers.append("Content-Disposition", f"attachment; filename={output.file_name}")
        response.headers.append("Python-Version", platform.python_version())
        response.headers.append("Weasyprint-Version", weasyprint.__version__)
        response.headers.append("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION", ""))
        return response

    except AssertionError as e:
        return process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return process_error(e, "Unexpected error due converting to PDF", 500)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def process_error(e: Exception, err_msg: str, status: int) -> Response:
    logging.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), media_type="plain/text", status_code=status)


def start_server(port: int) -> None:
    uvicorn.run(app=app, host="", port=port)
