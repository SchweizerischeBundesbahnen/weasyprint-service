"""Tests for the dedicated metrics server module."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.metrics_server import (
    DEFAULT_METRICS_PORT,
    MAX_VALID_PORT,
    MIN_VALID_PORT,
    MetricsServer,
    get_metrics_port,
    is_metrics_server_enabled,
)


class TestGetMetricsPort:
    """Tests for get_metrics_port function."""

    def test_default_port(self):
        """Test default metrics port when env var not set."""
        os.environ.pop("METRICS_PORT", None)
        assert get_metrics_port() == DEFAULT_METRICS_PORT

    def test_port_from_env(self):
        """Test metrics port from environment variable."""
        os.environ["METRICS_PORT"] = "9200"
        try:
            assert get_metrics_port() == 9200
        finally:
            os.environ.pop("METRICS_PORT")

    def test_invalid_port_string(self):
        """Test invalid port value falls back to default."""
        os.environ["METRICS_PORT"] = "invalid"
        try:
            assert get_metrics_port() == DEFAULT_METRICS_PORT
        finally:
            os.environ.pop("METRICS_PORT")

    def test_port_too_low(self):
        """Test port below valid range falls back to default."""
        os.environ["METRICS_PORT"] = str(MIN_VALID_PORT - 1)
        try:
            assert get_metrics_port() == DEFAULT_METRICS_PORT
        finally:
            os.environ.pop("METRICS_PORT")

    def test_port_too_high(self):
        """Test port above valid range falls back to default."""
        os.environ["METRICS_PORT"] = str(MAX_VALID_PORT + 1)
        try:
            assert get_metrics_port() == DEFAULT_METRICS_PORT
        finally:
            os.environ.pop("METRICS_PORT")

    def test_port_min_valid(self):
        """Test minimum valid port."""
        os.environ["METRICS_PORT"] = str(MIN_VALID_PORT)
        try:
            assert get_metrics_port() == MIN_VALID_PORT
        finally:
            os.environ.pop("METRICS_PORT")

    def test_port_max_valid(self):
        """Test maximum valid port."""
        os.environ["METRICS_PORT"] = str(MAX_VALID_PORT)
        try:
            assert get_metrics_port() == MAX_VALID_PORT
        finally:
            os.environ.pop("METRICS_PORT")


class TestIsMetricsServerEnabled:
    """Tests for is_metrics_server_enabled function."""

    def test_enabled_by_default(self):
        """Test metrics server is enabled by default."""
        os.environ.pop("METRICS_SERVER_ENABLED", None)
        assert is_metrics_server_enabled() is True

    def test_enabled_true(self):
        """Test metrics server enabled with 'true'."""
        os.environ["METRICS_SERVER_ENABLED"] = "true"
        try:
            assert is_metrics_server_enabled() is True
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_enabled_1(self):
        """Test metrics server enabled with '1'."""
        os.environ["METRICS_SERVER_ENABLED"] = "1"
        try:
            assert is_metrics_server_enabled() is True
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_enabled_yes(self):
        """Test metrics server enabled with 'yes'."""
        os.environ["METRICS_SERVER_ENABLED"] = "yes"
        try:
            assert is_metrics_server_enabled() is True
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_enabled_on(self):
        """Test metrics server enabled with 'on'."""
        os.environ["METRICS_SERVER_ENABLED"] = "on"
        try:
            assert is_metrics_server_enabled() is True
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_disabled_false(self):
        """Test metrics server disabled with 'false'."""
        os.environ["METRICS_SERVER_ENABLED"] = "false"
        try:
            assert is_metrics_server_enabled() is False
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_disabled_0(self):
        """Test metrics server disabled with '0'."""
        os.environ["METRICS_SERVER_ENABLED"] = "0"
        try:
            assert is_metrics_server_enabled() is False
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_disabled_no(self):
        """Test metrics server disabled with 'no'."""
        os.environ["METRICS_SERVER_ENABLED"] = "no"
        try:
            assert is_metrics_server_enabled() is False
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

    def test_case_insensitive(self):
        """Test case insensitivity of enabled check."""
        os.environ["METRICS_SERVER_ENABLED"] = "TRUE"
        try:
            assert is_metrics_server_enabled() is True
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")

        os.environ["METRICS_SERVER_ENABLED"] = "False"
        try:
            assert is_metrics_server_enabled() is False
        finally:
            os.environ.pop("METRICS_SERVER_ENABLED")


class TestMetricsServer:
    """Tests for MetricsServer class."""

    def test_initialization_default_port(self):
        """Test MetricsServer initializes with default port."""
        server = MetricsServer()
        assert server.port == DEFAULT_METRICS_PORT
        assert server.is_running is False

    def test_initialization_custom_port(self):
        """Test MetricsServer initializes with custom port."""
        server = MetricsServer(port=9200)
        assert server.port == 9200
        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        """Test start() sets is_running to True."""
        server = MetricsServer(port=9199)

        with patch("app.metrics_server.uvicorn.Server") as mock_server_cls:
            mock_server = AsyncMock()
            mock_server.serve = AsyncMock()
            mock_server_cls.return_value = mock_server

            await server.start()

            assert server.is_running is True
            mock_server_cls.assert_called_once()

            # Cleanup
            server._started = False

    @pytest.mark.asyncio
    async def test_start_twice_warns(self):
        """Test starting server twice logs warning."""
        server = MetricsServer(port=9198)
        server._started = True

        with patch("app.metrics_server.logger") as mock_logger:
            await server.start()
            mock_logger.warning.assert_called_with("Metrics server already started")

        # Cleanup
        server._started = False

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Test stop() does nothing when not started."""
        server = MetricsServer(port=9197)

        # Should not raise
        await server.stop()

        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self):
        """Test stop() sets is_running to False."""
        server = MetricsServer(port=9196)

        with patch("app.metrics_server.uvicorn.Server") as mock_server_cls:
            mock_server = AsyncMock()
            mock_server.serve = AsyncMock(return_value=None)
            mock_server_cls.return_value = mock_server

            await server.start()
            assert server.is_running is True

            await server.stop()
            assert server.is_running is False
