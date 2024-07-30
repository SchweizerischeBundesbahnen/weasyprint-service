import logging
import os
import platform
from urllib.parse import unquote

import weasyprint
from flask import Flask, Response, request
from gevent.pywsgi import WSGIServer

import SvgUtils

app = Flask(__name__)


@app.route("/version", methods=["GET"])
def version():
    return {
        "python": platform.python_version(),
        "weasyprint": weasyprint.__version__,
        "serviceVersion": os.environ.get('SERVICE_VERSION')
    }


@app.route("/convert/html", methods=["POST"])
def convert_html():
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
        html = SvgUtils.process_svg(html)
        weasyprint_html = weasyprint.HTML(string=html, base_url=base_url, media_type=media_type, encoding=encoding)
        output_pdf = weasyprint_html.write_pdf(pdf_variant=pdf_variant, presentational_hints=presentational_hints)

        response = Response(output_pdf, mimetype="application/pdf", status=200)
        response.headers.add("Content-Disposition", "attachment; filename=" + file_name)
        response.headers.add("Weasyprint-Version", weasyprint.__version__)
        response.headers.add("Python-Version", platform.python_version())
        return response

    except AssertionError as e:
        return process_error(e, "Assertion error, check the request body html", 400)
    except (UnicodeDecodeError, LookupError) as e:
        return process_error(e, "Cannot decode request html body", 400)
    except Exception as e:
        return process_error(e, "Unexpected error due converting to PDF", 500)


def process_error(e, err_msg, status):
    logging.exception(msg=err_msg + ": " + str(e))
    return Response(err_msg, mimetype="plain/text", status=status)


def start_server(port):
    http_server = WSGIServer(("", port), app)
    http_server.serve_forever()
