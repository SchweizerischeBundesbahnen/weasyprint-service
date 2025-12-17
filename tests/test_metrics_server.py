"""Tests for the dedicated metrics server module."""

import asyncio
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
            mock_server.started = True  # Simulate server ready state
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
    async def test_start_timeout(self):
        """Test start() raises TimeoutError if server doesn't start in time."""
        server = MetricsServer(port=9191)

        with patch("app.metrics_server.uvicorn.Server") as mock_server_cls:
            mock_server = AsyncMock()
            # Server never becomes ready
            mock_server.started = False
            mock_server.serve = AsyncMock(return_value=None)
            mock_server_cls.return_value = mock_server

            # Patch the timeout to be very short for testing
            with (
                patch.object(server, "stop", new_callable=AsyncMock) as mock_stop,
                pytest.raises(TimeoutError, match="Metrics server failed to start"),
            ):
                # Patch the time function to simulate timeout
                original_time = asyncio.get_event_loop().time
                call_count = [0]

                def mock_time() -> float:
                    call_count[0] += 1
                    if call_count[0] > 2:
                        return original_time() + 20  # Simulate 20 seconds passed
                    return original_time()

                with patch.object(asyncio.get_event_loop(), "time", mock_time):
                    await server.start()

                mock_stop.assert_called_once()

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
            mock_server.started = True  # Simulate server ready state
            mock_server.serve = AsyncMock(return_value=None)
            mock_server_cls.return_value = mock_server

            await server.start()
            assert server.is_running is True

            await server.stop()
            assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_with_timeout(self):
        """Test stop() handles timeout and cancels task."""
        server = MetricsServer(port=9195)

        with patch("app.metrics_server.uvicorn.Server") as mock_server_cls:
            mock_server = AsyncMock()
            mock_server.started = True

            # Create a task that will hang and cause timeout
            async def hang_forever() -> None:
                await asyncio.sleep(100)

            mock_server.serve = hang_forever
            mock_server_cls.return_value = mock_server

            await server.start()
            assert server.is_running is True

            # Patch wait_for to raise TimeoutError
            with patch("app.metrics_server.asyncio.wait_for", side_effect=TimeoutError):
                await server.stop()

            assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task_on_timeout(self):
        """Test stop() cancels task when timeout occurs."""
        server = MetricsServer(port=9194)
        server._started = True

        # Create an actual asyncio task that we can cancel
        async def long_running() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        server._task = task
        server._server = AsyncMock()

        # Patch wait_for to raise TimeoutError to trigger the cancel path
        with patch("app.metrics_server.asyncio.wait_for", side_effect=TimeoutError):
            await server.stop()

        # Allow event loop to process cancellation
        await asyncio.sleep(0)

        assert server.is_running is False
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_without_server(self):
        """Test stop() handles case when server is None."""
        server = MetricsServer(port=9193)
        server._started = True
        server._server = None
        server._task = None

        # Should not raise
        await server.stop()

        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_without_task(self):
        """Test stop() handles case when task is None."""
        server = MetricsServer(port=9192)
        server._started = True
        server._server = AsyncMock()
        server._task = None

        # Should not raise
        await server.stop()

        assert server.is_running is False
        assert server._server.should_exit is True
