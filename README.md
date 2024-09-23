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
    --build-arg APP_IMAGE_VERSION=0.0.0-dev \
    --file Dockerfile \
    --tag weasyprint-service:0.0.0-dev .
```

Replace 0.0.0 with the desired version number.

### Running the Development Container

To start the Docker container with your custom-built image:

```bash
  docker run --detach \
    --publish 9080:9080 \
    --name weasyprint-service \
    weasyprint-service:0.0.0-dev
```

### Stopping the Container

To stop the running container, execute:

```bash
  docker container stop weasyprint-service
```

### Access service

Weasyprint Service provides the following endpoints:

------------------------------------------------------------------------------------------

#### Getting version info

<details>
  <summary>
    <code>GET</code> <code>/version</code>
  </summary>

##### Responses

> | HTTP code | Content-Type       | Response                                                                                                                                           |
> |-----------|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
> | `200`     | `application/json` | `{ "chromium": "129.0.6668.58", "python": "3.12.5", "timestamp": "2024-09-23T12:23:09Z", "weasyprint": "62.3", "weasyprintService": "0.0.0-dev" }` |

##### Example cURL

> ```bash
>  curl -X GET -H "Content-Type: application/json" http://localhost:9080/version
> ```

</details>


------------------------------------------------------------------------------------------

#### Convert HTML to PDF

<details>
  <summary>
    <code>POST</code> <code>/convert/html</code>
  </summary>

##### Parameters

> | Parameter name       | Type     | Data type | Description                                                          |
> |----------------------|----------|-----------|----------------------------------------------------------------------|
> | encoding             | optional | string    | Encoding of provided HTML (default: utf-8)                           |
> | media_type           | optional | string    | WeasyPrint media type (default: print)                               |
> | file_name            | optional | string    | Output filename (default: converted-document.pdf)                    |
> | presentational_hints | optional | string    | WeasyPrint option: Follow HTML presentational hints (default: False) |
> | base_url             | optional | string    | Base URL to resolve relative resources (default: None)               |

##### Responses

> | HTTP code | Content-Type      | Response                      |
> |-----------|-------------------|-------------------------------|
> | `200`     | `application/pdf` | PDF document (binary data)    |
> | `400`     | `plain/text`      | Error message with exception  |
> | `500`     | `plain/text`      | Error message with exception  |

##### Example cURL

> ```bash
> curl -X POST -H "Content-Type: application/html" --data @input_html http://localhost:9080/convert/html --output output.pdf
> ```

</details>
