# WeasyPrint Service

A Dockerized service providing a REST API interface to leverage WeasyPrint's functionality for generating PDF documents
from HTML and CSS.

## Features

- Simple REST API to access WeasyPrint
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
    --publish 9080:9080 \
    --name weasyprint-service \
    ghcr.io/schweizerischebundesbahnen/weasyprint-service:latest
```

The service will be accessible on port 9080.

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
```bash
docker build -t weasyprint-service:local .
```
```bash
container-structure-test test --image weasyprint-service:local --config ./tests/container/container-structure-test.yaml
```
#### tox
```bash
poetry run tox
```
#### pytest (for debugging)
```bash
# all tests
poetry run pytest
```
```bash
# a specific test
poetry run pytest tests/test_svg_utils.py -v
```
#### pre-commit
```bash
poetry run pre-commit run --all
```

### REST API

This service provides REST API. OpenAPI Specification can be obtained [here](app/static/openapi.json).
