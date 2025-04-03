import logging
import os
import platform
from urllib.parse import unquote

import uvicorn
import weasyprint  # type: ignore
from fastapi import FastAPI, Request, Response

from app import svg_utils  # type: ignore
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


@app.post(
    "/convert/html",
    responses={400: {"content": {"text/plain": {}}, "description": "Invalid Input"}, 500: {"content": {"text/plain": {}}, "description": "Internal PDF Conversion Error"}},
)
async def convert_html(
    request: Request,
    encoding: str = "utf-8",
    media_type: str = "print",
    file_name: str = "converted-document.pdf",
    pdf_variant: str | None = None,
    presentational_hints: bool = False,
    base_url: str | None = None,
) -> Response:
    """
    Convert HTML to PDF
    """
    try:
        if base_url:
            base_url = unquote(base_url, encoding=encoding)
        html = (await request.body()).decode(encoding)
        html = svg_utils.process_svg(html)
        weasyprint_html = weasyprint.HTML(string=html, base_url=base_url, media_type=media_type, encoding=encoding)
        output_pdf = weasyprint_html.write_pdf(pdf_variant=pdf_variant, presentational_hints=presentational_hints)

        response = Response(output_pdf, media_type="application/pdf", status_code=200)
        response.headers.append("Content-Disposition", "attachment; filename=" + file_name)
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


def process_error(e: Exception, err_msg: str, status: int) -> Response:
    logging.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), media_type="plain/text", status_code=status)


def start_server(port: int) -> None:
    uvicorn.run(app=app, host="", port=port)
