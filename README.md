# WeasyPrint Service

A dockerized service providing a REST API interface to leverage [WeasyPrint](https://github.com/Kozea/WeasyPrint)'s functionality for generating PDF documents
from HTML and CSS.

## Features

- Simple REST API to access [WeasyPrint](https://github.com/Kozea/WeasyPrint)
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

To customize the device scaling when running the container, use:

```bash
docker run --detach \
  --publish 9080:9080 \
  --name weasyprint-service \
  --env DEVICE_SCALE_FACTOR=2.0 \
  ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

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
poetry run tox
```

#### pytest (for debugging)

Pytest is used for unit and integration testing of the application code. These tests verify that individual components and the entire application function correctly according to specifications. Running pytest during development helps catch bugs early and ensures code quality.

```bash
# all tests
poetry run pytest
```

```bash
# a specific test
poetry run pytest tests/test_svg_utils.py -v
```

#### pre-commit

Pre-commit hooks run automated checks on code before it's committed to the repository. This ensures consistent code style, formatting, and quality across the project. It helps catch common issues early in the development process, maintaining high code standards and reducing the need for style-related revisions during code reviews.

```bash
poetry run pre-commit run --all
```

### REST API

This service provides REST API. OpenAPI Specification can be obtained [here](app/static/openapi.json).
