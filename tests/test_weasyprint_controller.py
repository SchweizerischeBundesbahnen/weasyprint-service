import os
import platform

from app.weasyprint_controller import app

test_script_path = "python3.13|./tests/scripts/test_script.py"


def test_version():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["WEASYPRINT_SERVICE_BUILD_TIMESTAMP"] = "test2"
    os.environ["WEASYPRINT_SERVICE_CHROMIUM_VERSION"] = "test3"
    with app.test_client() as test_client:
        version = test_client.get("/version").json

        assert version["python"] == platform.python_version()
        assert version["weasyprint"] is not None
        assert version["weasyprintService"] == "test1"
        assert version["timestamp"] == "test2"
        assert version["chromium"] == "test3"


def test_convert_html():
    os.environ["SET_TEST_FLAG"] = "true"
    os.environ["CHROMIUM_EXECUTABLE_PATH"] = test_script_path
    with app.test_client() as test_client:
        result = test_client.post("/convert/html?base_url=/", json='<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"')
        assert result.status_code == 200
        result = test_client.post("/convert/html", data=b'\x81<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>"')
        assert result.status_code == 400
