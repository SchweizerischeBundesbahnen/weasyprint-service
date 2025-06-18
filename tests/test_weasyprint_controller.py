import os
import platform

from fastapi.testclient import TestClient

from app.weasyprint_controller import app

test_script_path = "./tests/scripts/test_script.sh"


def test_version():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["WEASYPRINT_SERVICE_BUILD_TIMESTAMP"] = "test2"
    os.environ["WEASYPRINT_SERVICE_CHROMIUM_VERSION"] = "test3"
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

        assert version["python"] == platform.python_version()
        assert version["weasyprint"] is not None
        assert version["weasyprintService"] == "test1"
        assert version["timestamp"] == "test2"
        assert version["chromium"] == "test3"


def test_convert_html():
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    with TestClient(app) as test_client:
        result = test_client.post(
            "/convert/html?base_url=/",
            content='<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert result.status_code == 200
        result = test_client.post(
            "/convert/html",
            content=b'\x81<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert result.status_code == 400
