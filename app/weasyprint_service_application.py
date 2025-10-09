import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

import uvicorn

from app import weasyprint_controller  # type: ignore


def setup_logging() -> Path:
    """
    Configure logging for the WeasyPrint service with both file and console output.

    The function:
    - Sets log level from LOG_LEVEL environment variable (defaults to INFO)
    - Creates timestamped log files in /opt/weasyprint/logs directory
    - Configures both file and console logging handlers
    - Uses format: timestamp - logger name - log level - message

    The log files are not rotated and a new file is created on each service start.

    Returns:
        Path: The path to the created log file
    """
    # Clean up any existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    # Use LOG_DIR environment variable if set, otherwise use default
    log_dir = Path(os.getenv("LOG_DIR", "/opt/weasyprint/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create log filename with timestamp
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"weasyprint-service_{current_time}.log"

    # Configure logging format
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Configure file handler (no rotation)
    file_handler = logging.FileHandler(
        log_file,
        encoding="utf-8",
        delay=False,  # Create file immediately
    )
    file_handler.setFormatter(formatter)

    # Configure console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Setup root logger
    configured_level = getattr(logging, log_level, logging.INFO)  # Default to INFO if invalid
    root_logger.setLevel(configured_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Explicitly set logging level for third-party libraries that have their own loggers
    # This ensures they respect the LOG_LEVEL environment variable
    # Note: Setting level on parent logger affects all child loggers
    for logger_name in ["fontTools", "fontTools.subset", "fontTools.ttLib", "weasyprint", "PIL", "playwright"]:
        logging.getLogger(logger_name).setLevel(configured_level)

    # Force immediate file creation
    root_logger.info(f"Logging initialized with level: {log_level}")
    root_logger.info(f"Log file: {log_file}")

    # Ensure everything is written
    for handler in root_logger.handlers:
        handler.flush()

    return log_file  # Return log file path for testing


def start_server(port: int) -> None:
    uvicorn.run(app=weasyprint_controller.app, host="", port=port)


def main() -> None:
    """
    Main entry point for the WeasyPrint service.

    Parses command line arguments, initializes logging, and starts the server.
    The service port can be specified via command line argument (defaults to 9080).
    """
    parser = argparse.ArgumentParser(description="Weasyprint service")
    parser.add_argument("--port", default=9080, type=int, required=False, help="Service port")
    args = parser.parse_args()

    setup_logging()
    logging.info("Weasyprint service listening port: " + str(args.port))

    start_server(args.port)


if __name__ == "__main__":
    main()
