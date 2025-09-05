import io
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.datastructures import FormData, UploadFile

from app.form_parser import FormParser


# ---------- Unit: ENV and constructor ----------

def test_init_defaults_and_env(monkeypatch: pytest.MonkeyPatch):
    # Environment variables should be respected if provided
    monkeypatch.setenv("FORM_MAX_FILES", "11")
    monkeypatch.setenv("FORM_MAX_FIELDS", "22")
    monkeypatch.setenv("FORM_MAX_PART_SIZE", "333")

    parser = FormParser()

    assert parser.max_files == 11
    assert parser.max_fields == 22
    assert parser.max_part_size == 333


def test_init_constructor_overrides_env(monkeypatch: pytest.MonkeyPatch):
    # Values passed to the constructor should override environment variables
    monkeypatch.setenv("FORM_MAX_FILES", "1000")
    monkeypatch.setenv("FORM_MAX_FIELDS", "1000")
    monkeypatch.setenv("FORM_MAX_PART_SIZE", "999999")

    parser = FormParser(max_files=5, max_fields=6, max_part_size=7)

    assert parser.max_files == 5
    assert parser.max_fields == 6
    assert parser.max_part_size == 7


def test_init_invalid_env(monkeypatch: pytest.MonkeyPatch):
    # Invalid environment variables should fall back to defaults
    monkeypatch.setenv("FORM_MAX_FILES", "not-an-int")
    monkeypatch.setenv("FORM_MAX_FIELDS", "")
    monkeypatch.setenv("FORM_MAX_PART_SIZE", "None")

    parser = FormParser()

    assert parser.max_files == 1000
    assert parser.max_fields == 1000
    assert parser.max_part_size == 10 * 1024 * 1024


# ---------- Unit: html_from_form ----------

def test_html_from_form_accepts_str():
    # String input should be returned as-is
    form = FormData([("html", "Hello <b>world</b>")])
    got = FormParser.html_from_form(form)
    assert got == "Hello <b>world</b>"


def test_html_from_form_accepts_bytes_utf8():
    # Bytes input should be decoded using UTF-8 by default
    form = FormData([("html", "Hello".encode("utf-8"))])
    got = FormParser.html_from_form(form)
    assert got == "Hello"


def test_html_from_form_missing_raises():
    # Missing "html" field should raise AssertionError
    form = FormData([])
    with pytest.raises(AssertionError) as ei:
        FormParser.html_from_form(form)
    assert ei.value.args == (400, "Missing html form field")


# ---------- Unit: collect_files_from_form ----------

def _uf(name: str | None, data: bytes = b"x") -> UploadFile:
    # Helper to construct UploadFile with given name and content
    return UploadFile(
        filename=name,
        file=io.BytesIO(data),
        headers=None,
    )

def test_collect_files_dedup_by_basename_and_default_name():
    form = FormData([
        ("files", _uf("A.txt", b"1")),
        ("files", _uf("A.txt", b"2")),
        ("files", _uf("B.txt", b"3")),
        ("files", _uf(None, b"4")), # -> attachment.bin
        ("files", _uf("B.txt", b"5")),
        ("files", _uf(None, b"6")),  # -> attachment.bin
    ])

    files = FormParser.collect_files_from_form(form)
    names = [f.filename for f in files]

    assert names == ["A.txt", "A.txt", "B.txt", "attachment.bin", "B.txt", "attachment.bin"]


# ---------- Integration: FastAPI + parse() ----------

def build_app(parser: FormParser) -> FastAPI:
    app = FastAPI()

    @app.post("/upload")
    async def upload(request: Request) -> dict[str, Any]:
        form = await parser.parse(request)
        html = FormParser.html_from_form(form)
        files = FormParser.collect_files_from_form(form)
        return {
            "html": html,
            "file_names": [f.filename for f in files],
            "limits": {
                "max_files": parser.max_files,
                "max_fields": parser.max_fields,
                "max_part_size": parser.max_part_size,
            },
        }

    return app


def test_parse_integration_with_fastapi(monkeypatch: pytest.MonkeyPatch):
    # Integration test with real multipart form parsing
    monkeypatch.setenv("FORM_MAX_FILES", "3")
    monkeypatch.setenv("FORM_MAX_FIELDS", "10")
    monkeypatch.setenv("FORM_MAX_PART_SIZE", "1048576")  # 1 MiB

    parser = FormParser()
    app = build_app(parser)
    client = TestClient(app)

    files = [
        ("files", ("a.txt", b"A")),
        ("files", ("b.txt", b"B1")),
        ("files", ("b.txt", b"B2")),
    ]
    resp = client.post("/upload", data={"html": "hi"}, files=files)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["html"] == "hi"
    assert payload["file_names"] == ["a.txt", "b.txt", "b.txt"]
    assert payload["limits"] == {
        "max_files": 3,
        "max_fields": 10,
        "max_part_size": 1048576,
    }


def test_parse_integration_html_bytes():
    # Integration test with bytes in the "html" field
    parser = FormParser()
    app = build_app(parser)
    client = TestClient(app)

    resp = client.post(
        "/upload",
        data={"html": "Hello".encode("utf-8")},
        files=[("files", ("x.bin", b"\x00\x01"))],
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["html"] == "Hello"
    assert payload["file_names"] == ["x.bin"]
