"""Pytest configuration and fixtures for weasyprint-service tests."""

import pytest


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
