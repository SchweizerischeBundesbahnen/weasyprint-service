"""Pytest configuration and fixtures for weasyprint-service tests."""

import os

import pytest

# The suite runs in the chromium SVG mode, whatever the environment says: the controller reads SVG_RENDERER
# at import, and weasysvg patches WeasyPrint for the whole process. A fixture would come too late.
# The tests of weasysvg, the default mode, switch the mode themselves.
os.environ["SVG_RENDERER"] = "chromium"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command-line options to pytest."""
    parser.addoption(
        "--save-test-outputs",
        action="store_true",
        default=False,
        help="Save test output files (PDFs, images, etc.) to disk for manual inspection",
    )


@pytest.fixture
def save_test_outputs(request: pytest.FixtureRequest) -> bool:
    """Fixture to check if test outputs should be saved to disk."""
    return request.config.getoption("--save-test-outputs")
