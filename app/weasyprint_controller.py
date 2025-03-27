import logging
import os
import platform
from pathlib import Path
from urllib.parse import unquote

import weasyprint  # type: ignore
from flask import Flask, Response, request, send_from_directory
from flask_swagger_ui import get_swaggerui_blueprint  # type: ignore
from gevent.pywsgi import WSGIServer  # type: ignore

from app import svg_utils  # type: ignore

app = Flask(__name__)
SWAGGER_URL = "/api/docs"
API_URL = "/static/openapi.json"

swaggerui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL, config={"app_name": "WeasyPrint Service API"})

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)


@app.route("/static/openapi.json")
def send_swagger() -> Response:
    directory = Path(app.root_path) / "static"
    return send_from_directory(str(directory), "openapi.json")


@app.route("/version", methods=["GET"])
def version() -> dict[str, str | None]:
    """
    Get version information
    ---
    get:
      tags:
        - Service Info
      summary: Get version info
      responses:
        200:
          description: Version data
          content:
            application/json:
              schema: VersionSchema
    """
    return {
        "python": platform.python_version(),
        "weasyprint": weasyprint.__version__,
        "weasyprintService": os.environ.get("WEASYPRINT_SERVICE_VERSION"),
        "timestamp": os.environ.get("WEASYPRINT_SERVICE_BUILD_TIMESTAMP"),
        "chromium": os.environ.get("WEASYPRINT_SERVICE_CHROMIUM_VERSION"),
    }


@app.route("/convert/html", methods=["POST"])
def convert_html() -> Response:
    """
    Convert HTML to PDF
    ---
    post:
      tags:
        - Conversion
      summary: Convert HTML to PDF
      parameters:
        - in: query
          name: encoding
          schema: { type: string, default: "utf-8" }
        - in: query
          name: media_type
          schema: { type: string, default: "print" }
        - in: query
          name: file_name
          schema: { type: string, default: "converted-document.pdf" }
        - in: query
          name: pdf_variant
          schema: { type: string }
        - in: query
          name: presentational_hints
          schema: { type: boolean, default: false }
        - in: query
          name: base_url
          schema: { type: string }
      requestBody:
        required: true
        content:
          text/html:
            schema:
              type: string
      responses:
        200:
          description: PDF successfully generated
          content:
            application/pdf:
              schema:
                type: string
                format: binary
        400:
          description: Invalid input
        500:
          description: Internal server error
    """
    try:
        encoding = request.args.get("encoding", default="utf-8")
        media_type = request.args.get("media_type", default="print")
        file_name = request.args.get("file_name", default="converted-document.pdf")
        pdf_variant = request.args.get("pdf_variant", default=None)
        presentational_hints = request.args.get("presentational_hints", default=False)

        base_url = request.args.get("base_url", default=None)
        if base_url:
            base_url = unquote(base_url, encoding=encoding)

        html = request.get_data().decode(encoding)
        html = svg_utils.process_svg(html)
        weasyprint_html = weasyprint.HTML(string=html, base_url=base_url, media_type=media_type, encoding=encoding)
        output_pdf = weasyprint_html.write_pdf(pdf_variant=pdf_variant, presentational_hints=presentational_hints)

        response = Response(output_pdf, mimetype="application/pdf", status=200)
        response.headers.add("Content-Disposition", "attachment; filename=" + file_name)
        response.headers.add("Python-Version", platform.python_version())
        response.headers.add("Weasyprint-Version", weasyprint.__version__)
        response.headers.add("Weasyprint-Service-Version", os.environ.get("WEASYPRINT_SERVICE_VERSION"))
        return response

    except AssertionError as e:
        return process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return process_error(e, "Unexpected error due converting to PDF", 500)


def process_error(e: Exception, err_msg: str, status: int) -> Response:
    logging.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg + ": " + getattr(e, "message", repr(e)), mimetype="plain/text", status=status)


def start_server(port: int) -> None:
    http_server = WSGIServer(("", port), app)
    http_server.serve_forever()
