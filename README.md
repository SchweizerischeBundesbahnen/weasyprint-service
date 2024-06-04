# WeasyPrint Service
Service providing REST API to use WeasyPrint functionality

## Build Docker image

```bash
  docker build \
    --file Dockerfile \
    --tag weasyprint-service:61.2.0 .
```

## Start Docker container

```bash
  docker run --detach \
    --publish 9080:9080 \
    --name weasyprint-service \
    weasyprint-service:61.2.0
```

## Stop Docker container

```bash
  docker container stop weasyprint-service
```

## Access service
Weasyprint Service provides the following endpoints:

------------------------------------------------------------------------------------------
#### Getting version info
<details>
  <summary>
    <code>GET</code> <code>/version</code>
  </summary>

##### Responses

> | HTTP code | Content-Type       | Response                                  |
> |-----------|--------------------|-------------------------------------------|
> | `200`     | `application/json` | `{"python":"3.12.3","weasyprint":"61.2"}` |

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
