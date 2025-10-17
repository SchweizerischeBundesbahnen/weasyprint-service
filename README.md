# WeasyPrint Service

A dockerized service providing a REST API interface to leverage [WeasyPrint](https://github.com/Kozea/WeasyPrint)'s functionality for generating PDF documents
from HTML and CSS.

## Features

- Simple REST API to access [WeasyPrint](https://github.com/Kozea/WeasyPrint)
- Real-time monitoring dashboard with metrics visualization
- Compatible with amd64 and arm64 architectures
- Easily deployable via Docker

## Getting Started

### Installation

To install the latest version of the WeasyPrint Service, run the following command:

```bash
docker pull ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

### Running the Service

To start the WeasyPrint service container, execute:

```bash
  docker run --detach \
    --init \
    --publish 9080:9080 \
    --name weasyprint-service \
    ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

The service will be accessible on port 9080.

> **Important**: The `--init` flag enables Docker's built-in init process which handles signal forwarding and zombie process reaping. This is required for proper operation of the service.

### Device Scaling

Device Scaling can be configured via the `DEVICE_SCALE_FACTOR` environment variable. This allows you to adjust the scaling factor for the SVG to PNG conversion.

**Valid range:** 1.0 - 10.0 (default: 1.0)

To customize the device scaling when running the container:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env DEVICE_SCALE_FACTOR=2.0 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

**Note:** Invalid values will fall back to default (1.0) with a warning logged.

### Concurrency Control

The service limits concurrent SVG to PNG conversions to prevent memory leaks and resource exhaustion.

**Valid range:** 1 - 100 (default: 10)

To customize the concurrency limit when running the container:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env MAX_CONCURRENT_CONVERSIONS=20 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

**Note:** Invalid values will fall back to default (10) with a warning logged.

### Automatic Chromium Restart

The service can automatically restart the Chromium browser after a specified number of conversions to prevent memory accumulation and ensure long-term stability.

**Valid range:** 0 - 10000 (default: 0 = disabled)

To enable automatic restart after every 1000 conversions:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env CHROMIUM_RESTART_AFTER_N_CONVERSIONS=1000 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

**How it works:**
- When enabled (value > 0), Chromium will automatically restart after reaching the specified conversion count
- The restart happens transparently before the next conversion begins
- Conversion counter resets to 0 after each restart
- Set to 0 (default) to disable automatic restarts
- Useful for long-running services with high conversion volumes

**Note:** Invalid values will fall back to default (0) with a warning logged.

### Chromium Requirements and Recovery

The service requires a persistent Chromium browser instance for SVG to PNG conversion.

**Startup Behavior (Fail-Fast):**
- The service will terminate if Chromium cannot be initialized during startup
- Common causes: Missing dependencies, insufficient memory, or missing Chromium binaries
- Docker requirements: `--shm-size` should be configured if running many concurrent conversions
- Health check: The `/health` endpoint verifies Chromium is running and healthy at runtime

**Automatic Recovery:**
- If a conversion fails due to Chromium crash or error, the service automatically restarts Chromium and retries
- **Valid range:** 1 - 10 (default: 2)
- This provides resilience against transient Chromium failures during operation
- If restart fails or all retry attempts are exhausted, the conversion request will fail with an error
- Recovery attempts are logged for monitoring and troubleshooting

To customize the number of retry attempts:
```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env CHROMIUM_MAX_CONVERSION_RETRIES=3 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

**Note:** Invalid values will fall back to default (2) with a warning logged.

**Monitoring:**
- Use Docker healthcheck or the `/health` endpoint to monitor service availability
- Check service logs for automatic recovery events and conversion failures
- Failed conversions are logged with WARNING level, recovery attempts with INFO level

To diagnose Chromium startup issues, check the service logs for error messages during initialization. The container will exit if Chromium fails to start.

### Monitoring Dashboard

The service includes an interactive web-based monitoring dashboard accessible at `/dashboard`:

**Dashboard Features:**

**Key Performance Indicators:**
- Service health status with real-time indicator
- Total conversions (HTML→PDF and SVG→PNG)
- Error rate percentage
- Current queue size and active conversions
- Average response time
- System uptime and browser restarts

**Interactive Charts:**
1. **Queue & Active Conversions** - Real-time visualization of request queue and concurrent processing
2. **CPU Usage (%)** - CPU consumption tracking with percentage scale
3. **Memory Usage (MB)** - Memory tracking showing Chromium memory, total system memory, and available memory

**Technical Details:**
- **Auto-refresh**: Updates every 5 seconds
- **Data retention**: Last 20 data points on charts
- **Technology**: Chart.js 4.4.0 (bundled locally) for visualizations
- **Design**: Light or dark theme support via environment variable
- **API endpoint**: Fetches data from `/health?detailed=true`
- **Version information**: Service, WeasyPrint, and Chromium versions displayed in the header

**Theme Configuration:**

The dashboard theme can be configured via the `DASHBOARD_THEME` environment variable:

**Valid values:** `light`, `dark` (case-insensitive, default: `light`)

To use dark theme:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env DASHBOARD_THEME=dark \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

**Note:** Invalid values will fall back to light theme with a warning logged.

**Production Considerations:**
- Consider restricting dashboard access via reverse proxy (nginx, Traefik)
- Use authentication middleware for sensitive environments
- Monitor dashboard endpoint metrics separately

### Logging Configuration

The service includes a robust logging system with the following features:

- Log files are stored in `/opt/weasyprint/logs` directory
- Log level can be configured via `LOG_LEVEL` environment variable (default: INFO)
- Log format: `timestamp - logger name - log level - message`
- Each service start creates a new timestamped log file

To customize logging when running the container:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env LOG_LEVEL=DEBUG \
  --volume /path/to/local/logs:/opt/weasyprint/logs \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

Available log levels:

- DEBUG: Detailed information for debugging
- INFO: General operational information (default)
- WARNING: Warning messages for potential issues
- ERROR: Error messages for failed operations
- CRITICAL: Critical issues that require immediate attention

### Using as a Base Image

To extend or customize the service, use it as a base image in the Dockerfile:

```Dockerfile
FROM ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

### Using Docker Compose

To run the service using Docker Compose:

```bash
docker-compose up -d
```

The Docker Compose configuration includes the `init: true` parameter which enables proper process management for the container.

### Multipart form limits (environment variables)

The endpoint /convert/html-with-attachments parses multipart/form-data and supports configuring Starlette's form parsing limits via environment variables:

- FORM_MAX_FIELDS: Maximum number of non-file form fields to accept. Default: 1000.
- FORM_MAX_FILES: Maximum number of file parts to accept. Default: 1000.
- FORM_MAX_PART_SIZE: Maximum allowed size in bytes for any single part (file or field). Default: 10485760 (10 MiB).

Notes:
- Values are parsed as integers. Invalid or negative values fall back to the defaults (negative values are clamped to 0 internally).
- These limits only affect the /convert/html-with-attachments endpoint. The endpoint requires Content-Type: multipart/form-data and will return 400 Bad Request otherwise.

Examples:

Docker run:
```bash
docker run --detach \
  --init \
  --publish 9080:9080 \
  --name weasyprint-service \
  -e FORM_MAX_FIELDS=2000 \
  -e FORM_MAX_FILES=2000 \
  -e FORM_MAX_PART_SIZE=20971520 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

### Mount a custom fonts folder
The following entry may be added to the `run` command:

```bash
  docker run -v /path/to/host/fonts:/usr/share/fonts/custom ...
```

Replace `/path/to/host/fonts` with the folder containing custom fonts

### Insert native sticky notes into final PDF document
You can insert native PDF sticky note annotations at specific positions in the resulting document by using the following HTML structure (nested notes are supported for replies):

```html
  <span class="sticky-note">
    <span class="sticky-note-time">2025-04-30T07:24:55.000+02:00</span>
    <span class="sticky-note-username">Test User 1</span>
    <span class="sticky-note-title">Test Title</span>
    <span class="sticky-note-text">Test sticky note text</span>

    <span class="sticky-note">
      <span class="sticky-note-time">2020-05-12T08:17:02.000+02:00</span>
      <span class="sticky-note-username">Test User 2</span>
      <span class="sticky-note-title">Reply Title</span>
      <span class="sticky-note-text">Reply text</span>
    </span>

  </span>
```

## Development

### Building the Docker Image

To build the Docker image from the source with a custom version, use:

```bash
  docker build \
    --build-arg APP_IMAGE_VERSION=0.0.0 \
    --file Dockerfile \
    --tag weasyprint-service:0.0.0 .
```

Replace 0.0.0 with the desired version number.

### Running the Development Container

To start the Docker container with your custom-built image:

```bash
  docker run --detach \
    --publish 9080:9080 \
    --name weasyprint-service \
    weasyprint-service:0.0.0
```

### Stopping the Container

To stop the running container, execute:

```bash
  docker container stop weasyprint-service
```

### Testing

#### container-structure-test

The container-structure-test tool is used to verify that the Docker image meets expected standards and specifications. It validates the container structure, ensuring proper file paths, permissions, and commands are available, which helps maintain consistency and reliability of the containerized application.

Before running the following command, ensure that the `container-structure-test` tool is installed. You can find installation instructions in the [official documentation](https://github.com/GoogleContainerTools/container-structure-test).

```bash
container-structure-test test --image weasyprint-service:0.0.0 --config ./tests/container/container-structure-test.yaml
```

#### grype

Grype is used for vulnerability scanning of the Docker image. This tool helps identify known security vulnerabilities in the dependencies and packages included in the container, ensuring the deployed application meets security standards and doesn't contain known exploitable components.

To scan the Docker image for vulnerabilities, you can use Grype. First, ensure that Grype is installed by following the [installation instructions](https://github.com/anchore/grype#installation).

Then run the vulnerability scan on your image:

```bash
grype weasyprint-service:0.0.0
```

#### tox

Tox automates testing in different Python environments, ensuring that the application works correctly across various Python versions and configurations. It helps maintain compatibility and provides a standardized way to run test suites, formatting checks, and other quality assurance processes.

```bash
uv run tox
```

#### pytest (for debugging)

Pytest is used for unit and integration testing of the application code. These tests verify that individual components and the entire application function correctly according to specifications. Running pytest during development helps catch bugs early and ensures code quality.

```bash
# all tests
uv run pytest
```

```bash
# a specific test
uv run pytest tests/test_svg_processor.py -v
```

#### pre-commit

Pre-commit hooks run automated checks on code before it's committed to the repository. This ensures consistent code style, formatting, and quality across the project. It helps catch common issues early in the development process, maintaining high code standards and reducing the need for style-related revisions during code reviews.

```bash
uv run pre-commit run --all
```

### REST API

This service provides REST API. OpenAPI Specification can be obtained [here](docs/openapi.json).
