# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Before Committing - Run Full Test Suite
```bash
# Run complete test suite (optimized sequence, no redundancy)
# 1. Install dependencies first (required before running tox)
uv sync --group dev --group test

# 2. Run tox - handles linting, formatting, type checking, and tests with coverage
uv run tox

# 3. Run pre-commit hooks - final validation including security checks and commit format
uv run pre-commit run --all
```

### Commit Convention
Use Conventional Commits format:
```bash
# Format: <type>(<scope>): <description>
# Examples:
git commit -m "feat(api): add PDF compression endpoint"
git commit -m "fix(svg): handle malformed SVG input gracefully"
git commit -m "docs: update API documentation"
git commit -m "chore(deps): update weasyprint to 66.0"
git commit -m "test(controller): add edge case tests for HTML parsing"
git commit -m "refactor(parser): simplify attachment handling logic"
git commit -m "perf(svg): optimize SVG to PNG conversion"
```

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert

### Development Environment Setup
```bash
# Install dependencies using uv
uv sync --group dev --group test
```

### Testing and Quality Assurance
```bash
# Quick test during development
uv run pytest tests/test_specific_file.py -v

# Run specific test within a file
uv run pytest tests/test_svg_renderer.py::test_svg_is_drawn_as_vector -v

# Manual linting/formatting (if needed outside of tox/pre-commit)
uv run ruff format
uv run ruff check --fix
uv run ty check

# Generate/update OpenAPI schema (auto-runs in pre-commit)
scripts/precommit_generate_openapi.sh
```

### Load Testing
The repository includes a comprehensive load testing script for performance evaluation and stress testing.

```bash
# Basic load test (100 requests, 10 concurrent workers)
uv run python scripts/load_test.py

# Custom configuration
uv run python scripts/load_test.py --requests 1000 --concurrency 50

# Test specific scenario
uv run python scripts/load_test.py --scenario simple    # Basic HTML conversion
uv run python scripts/load_test.py --scenario complex  # Complex HTML with tables
uv run python scripts/load_test.py --scenario svg      # SVG to PNG conversion

# Export results to JSON
uv run python scripts/load_test.py --requests 500 --concurrency 20 --output results.json

# Export results to CSV
uv run python scripts/load_test.py --requests 500 --concurrency 20 --output results.csv --format csv

# Test against custom URL
uv run python scripts/load_test.py --url http://localhost:9080 --requests 200 --concurrency 10

# Stress test with high concurrency
uv run python scripts/load_test.py --scenario svg --requests 2000 --concurrency 100 --timeout 60

# Verbose mode - show detailed per-request information
uv run python scripts/load_test.py --requests 50 --concurrency 5 --verbose
```

**Load Test Features:**
- Real-time progress display with success/failure counts
- Verbose mode (`--verbose` or `-v`): visual per-request tracking with "Request sent..." and completion status
  - Shows: `[N/total] → Request sent...` when request is initiated
  - Shows: `[N/total] ✓ Completed in XXXms` on success
  - Shows: `[N/total] ✗ Completed in XXXms (error)` on failure
- Comprehensive metrics: min/max/avg/p50/p95/p99 response times
- Requests per second calculation
- Status code and error distribution
- Configurable scenarios (simple, complex, SVG)
- Export to JSON or CSV format
- Async/concurrent request execution using httpx

**Use Cases:**
- Validate service behavior under load
- Identify performance bottlenecks
- Measure the cost of SVG drawn by weasysvg
- Generate performance baselines for CI/CD

### Local Development Server
```bash
# Start FastAPI development server
uv run python -m app.weasyprint_service_application --port 9080

# Access API documentation
# http://localhost:9080/api/docs
```

### Docker Development
```bash
# Build development image
docker build --build-arg APP_IMAGE_VERSION=0.0.0 --file Dockerfile --tag weasyprint-service:0.0.0 .

# Run development container (expose both application and metrics ports)
docker run --detach --init --publish 9080:9080 --publish 9180:9180 --name weasyprint-service weasyprint-service:0.0.0

# Test container structure
container-structure-test test --image weasyprint-service:0.0.0 --config ./tests/container/container-structure-test.yaml

# Vulnerability scanning
grype weasyprint-service:0.0.0
```

## Architecture Overview

### Core Application Structure
- **FastAPI Application**: `app/weasyprint_controller.py` - Main REST API with endpoints for PDF generation
- **Service Entry Point**: `app/weasyprint_service_application.py` - Application startup, logging configuration, and argument parsing
- **HTML Processing Pipeline**: HTML → PDF conversion using WeasyPrint with attachment and SVG processing support

### Key Components
- **AttachmentManager** (`app/attachment_manager.py`): Handles multipart form data and file attachments for HTML conversion
- **FormParser** (`app/form_parser.py`): Parses multipart/form-data with configurable limits via environment variables
- **HtmlParser** (`app/html_parser.py`): Processes HTML content and handles embedded resources
- **Visio drawings** (`app/vsdx_renderer.py`): weasyvsdx draws VSDX and VSD natively in WeasyPrint, as vector; `/version` adds `weasyvsdx` and `libvisio`
- **SVG** (`app/svg_renderer.py`): weasysvg draws SVG natively in WeasyPrint, as vector. It is the only renderer, the service has no Chromium
- **ConversionMetrics** (`app/conversion_metrics.py`): Counts HTML to PDF conversions, failures and durations since the service started. `get_conversion_metrics()` is the singleton, taken as a FastAPI dependency by the `/convert/*` endpoints, `/health` and `/metrics`
- **Schemas** (`app/schemas.py`): Pydantic models for API request/response validation

### API Endpoints Architecture
- `/dashboard` - Interactive web-based monitoring dashboard with real-time metrics visualization
  - PDF conversion counts, error rate, average time, uptime and a chart of the system memory
  - Auto-refresh every 5 seconds
  - Configurable light/dark theme via DASHBOARD_THEME environment variable (default: light)
- `/health` - Health check endpoint with optional detailed metrics
  - Simple mode (default): Returns 200 "OK"
  - Detailed mode (`?detailed=true`): Returns JSON with status, versions, `svg_renderer` and the PDF conversion metrics (`ConversionMetricsSchema`)
- `/version` - Service version information (apiVersion, Python, WeasyPrint, service, `svgRenderer`, weasysvg, weasyvsdx, libvisio versions)
  - `apiVersion`: Integer for compatibility checking with pdf-exporter. Increment only on breaking API changes.
- `/metrics` - Prometheus metrics endpoint (served on dedicated port, default: 9180)
  - **Security**: Exposed on separate port from main API for network-level isolation
  - Returns metrics in Prometheus text format
  - Automatic FastAPI metrics (request duration, in-progress requests, total requests)
  - Custom conversion metrics (conversions, failures, durations, error rate, uptime)
  - System memory, and the process metrics of prometheus_client (CPU, resident memory)
  - Compatible with Prometheus scraping and Grafana visualization
- `/convert/html` - Basic HTML to PDF conversion (accepts HTML string, returns PDF binary)
- `/convert/html-with-attachments` - HTML to PDF with file attachments support (multipart/form-data, for embedded resources)

**Authentication:** Both `/convert/*` endpoints require an API key when `API_KEY` is configured (see `app/auth.py`). All other endpoints stay open, which keeps the Docker healthcheck and the dashboard working.

**Query Parameters for PDF conversion:**
- `pdf_variant` - PDF profile/variant (see supported variants below)
- `presentational_hints` - Use HTML presentational hints (default: true)
- `custom_metadata` - Include custom metadata in PDF (default: false)
- `full_fonts` - Embed full fonts instead of subsetting (default: false). Escape hatch for fonts that fail during subsetting. Note: fonttools 4.63.0 accepts reserved OS/2 ulUnicodeRange bits 123-127, so the former `ValueError: expected 0 <= int <= 122` no longer occurs (truly out-of-range bits now raise `expected 0 <= int <= 127`)

**Supported PDF variants (WeasyPrint 70.0):**
- PDF/A basic: `pdf/a-1b`, `pdf/a-2b`, `pdf/a-3b`
- PDF/A unicode: `pdf/a-2u`, `pdf/a-3u`, `pdf/a-4u`
- PDF/A accessible: `pdf/a-1a`, `pdf/a-2a`, `pdf/a-3a`
- PDF/A-4: `pdf/a-4e`, `pdf/a-4f`
- PDF/UA: `pdf/ua-1`, `pdf/ua-2`

> **Note:** `pdf/a-4b` is not supported. Use `pdf/a-4f` or `pdf/a-4e` instead.

### Configuration and Environment Variables

**Logging:** `setup_logging()` (`app/weasyprint_service_application.py`) owns the logging configuration of the whole process. Every uvicorn server is started with `log_config=None`, which is what keeps uvicorn from applying its own configuration, and `configure_uvicorn_logging()` routes the uvicorn loggers into the root handlers. Never give a `uvicorn.Config` a `log_level`, and never give it a logging configuration of its own: both are applied to the uvicorn loggers of the whole process, and the metrics server used to silence the main server that way. Access logs (`uvicorn.access`) propagate at DEBUG only.

**General Configuration:**
- `LOG_LEVEL`: Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL) - defaults to INFO
- `LOG_DIR`: Directory for log files (defaults to `/opt/weasyprint/logs`)
- `WEASYPRINT_SERVICE_VERSION`: Service version (set during build)
- `WEASYPRINT_SERVICE_BUILD_TIMESTAMP`: Build timestamp (set during build)
- `GRACEFUL_SHUTDOWN_TIMEOUT`: Seconds uvicorn waits for running requests on SIGTERM (1-300, default: 30)
- `MAX_CONCURRENT_PDF_CONVERSIONS`: PDF renderings allowed at the same time (1-100, default: 2). `write_pdf` runs in a dedicated `ThreadPoolExecutor` built by the lifespan, so it no longer holds the event loop and the pool size is the real bound on parallel renderings

**External resources (see `app/external_resources.py`):**
- `EXTERNAL_RESOURCES_POLICY` (BLOCK_INTERNAL default / ALLOWLIST_ONLY / ALLOW_ALL), `EXTERNAL_RESOURCES_ALLOWED_ORIGINS` (`[scheme://]host[:port]`, comma separated), `EXTERNAL_RESOURCES_MAX_SIZE_MB` (16), `EXTERNAL_RESOURCES_TIMEOUT_SECONDS` (10).
- `PolicyUrlFetcher` is passed to every `weasyprint.HTML(...)` call: addresses are vetted and pinned, redirects re-vetted, bodies capped and restricted to images, fonts, stylesheets and Visio drawings (an untyped one by its Visio suffix and its ZIP or OLE signature). `file:` is refused outside the request temporary directory, which is what makes `/convert/html-with-attachments` keep working.

**TLS (see `app/tls.py`):**
- `TLS_CERT_FILE`, `TLS_KEY_FILE`, `TLS_KEY_PASSWORD`, `TLS_CLIENT_CA_FILE`, `TLS_CLIENT_AUTH` (none/optional/required): serve the API over HTTPS. Unset means plain HTTP (default).
- `METRICS_TLS_*`: the same five for the metrics server, configured independently. Neither set inherits from the other.
- Incomplete configuration fails at startup, it never falls back to plain HTTP. The material is loaded before either server listens (`load_tls_options`), so a mismatched key or a wrong password also stops the start. The container healthcheck (`healthcheck.sh`) follows the configured scheme and probes with `app/healthcheck_probe.py` (standard library only, no proxy). Over TLS it verifies the server like a client: it trusts `TLS_CERT_FILE` itself, checks the first name of its subjectAltName (read by a small DER parser, as the standard library has no public reader) and connects to loopback. Python's `VERIFY_X509_STRICT` is cleared, as curl and browsers make no such checks. An expired certificate, or one the server does not present, makes the container unhealthy. The image has no curl: it carried 16 of the 17 critical findings of the image scans, for this probe alone.

**Authentication:**
- `API_KEY`: API key(s) protecting the `/convert/*` endpoints. Unset or empty disables authentication (default). Comma-separated list allows key rotation. Clients send `X-API-Key: <key>` or `Authorization: Bearer <key>`. Invalid or missing keys return 401.

**Form Processing:**
- `FORM_MAX_FIELDS`: Maximum number of form fields (default: 1000)
- `FORM_MAX_FILES`: Maximum number of file uploads (default: 1000)
- `FORM_MAX_PART_SIZE`: Maximum size per form part in bytes (default: 10485760/10MB)

**SVG Renderer (see `app/svg_renderer.py`):**
- weasysvg draws SVG, always. The controller installs it once at import (`configure_svg_renderer()`), before weasyvsdx, which draws the text of Visio drawings with its foreignObject. `weasysvg.install()` patches WeasyPrint for the whole process, so the whole test suite runs with it.
- `SVG_RENDERER` is read only to warn: a value other than `weasysvg` logs `SVG_RENDERER=<value> is no longer supported; weasysvg draws SVG`. The service never fails on it.
- The Chromium mode is gone. `DEVICE_SCALE_FACTOR`, `MAX_CONCURRENT_CONVERSIONS`, all `CHROMIUM_*` variables and the `scale_factor` query parameter have no effect; FastAPI ignores the unknown parameter, so old clients keep working.

**Dashboard Configuration:**
- `DASHBOARD_THEME`: Dashboard theme (light/dark, case-insensitive, default: light)

**Metrics Server Configuration:**
- `METRICS_PORT`: Port for the dedicated Prometheus metrics server (default: 9180, range: 1024-65535)
- `METRICS_SERVER_ENABLED`: Enable/disable the dedicated metrics server (true/false, default: true)

## Development Practices

- Check IDE diagnostics for errors before running tools manually
- **Context Window Optimization Strategy:**
  - We optimize for CLEAN main context, not token cost (Claude Code Plan 5x)
  - Use agents liberally to keep main context focused on implementation
  - Time for agent spawning is acceptable trade-off for context clarity
- **Use agents for these tasks:**
  - **context7-docs agent** - All documentation lookups (libraries, frameworks, APIs)
  - **ansible-expert agent** - Ansible-specific tasks (if applicable)
  - **docker-optimizer agent** - Docker optimization questions
  - Never use WebFetch for technical documentation - always use appropriate agent
- **Keep in main context:**
  - Direct code edits and bug fixes
  - Quick tool calls (Read, Write, Edit)
  - Implementation work
  - Simple clarifications
- ALWAYS run `pre-commit run -a` after implementation
- NEVER suppress or comment lint or test errors or problems

### Before Committing Changes (MANDATORY)

**ALWAYS perform these steps BEFORE creating any git commit:**

1. **Update TODO.md**:
   - Move completed tasks from "Current Work" to "Completed Tasks"
   - Condense descriptions (keep key points only)
   - Ensure "Current Work" reflects actual current state

2. **Update CLAUDE.md** (if applicable):
   - Add new commands or patterns discovered during implementation
   - Update technical details if architecture changed
   - Document new development practices or gotchas
   - Update dependency versions in examples if changed

3. **Review changes**:
   - Run `git status` and `git diff` to verify what will be committed
   - Ensure TODO.md is NOT staged (it should never be committed)
   - Ensure CLAUDE.md changes (if any) ARE staged

**This check is MANDATORY before every commit. Do not skip these steps.**

### GitHub PR Code Reviews (Automated Workflow)

**Philosophy**: Reviews should be **terse, actionable, and problem-focused**. No praise, no analysis of unchanged code.

**When reviewing PRs via the automated workflow:**
- ONLY review lines changed in the PR diff
- ONLY report actual problems (bugs, security issues, breaking changes, missing tests)
- Use terse format: `[file:line] Problem - Fix: Solution`
- If no issues found, say "No issues found." and stop
- Do NOT: praise code quality, review unchanged code, suggest optional improvements, analyze performance if not changed

**Review categories:**
- 🔴 **Critical**: Bugs, security vulnerabilities, breaking changes
- 🟡 **Important**: Missing tests for new functionality, significant issues

### Skip Reviews For (Automated Tools Handle These)

**The following are already checked by automated tools - DO NOT comment on them:**

**Formatting & Style** (handled by Ruff):
- Line length (configured to 240 characters)
- Import ordering and organization
- Indentation and whitespace
- Quotation mark consistency
- Trailing commas
- Line breaks and blank lines

**Type Checking** (handled by ty):
- Type annotations and hints
- Type compatibility
- Return type correctness
- Optional/None handling

**Code Quality** (handled by Ruff linter):
- Unused imports and variables
- Undefined names
- F-string usage
- List/dict comprehension simplification
- Mutable default arguments
- Shadowed variables

**Testing** (handled by Pytest + Coverage):
- Test coverage (minimum 90% required)
- Async test configuration
- Test discovery and execution

**Pre-commit Hooks**:
- YAML formatting (yamlfix)
- General formatting issues
- Trailing whitespace
- OpenAPI schema generation
- Security checks (gitleaks)

**Don't suggest these common patterns (already established in codebase):**
- Using Ruff instead of Black/isort/flake8
- Using uv for package management
- Python 3.13+ syntax and features
- FastAPI patterns already in use
- Temporary file handling patterns
- weasysvg for SVG, weasyvsdx for Visio drawings

### Project-Specific Review Focus

**DO focus on:**
1. **Security**:
   - Input validation and sanitization
   - Path traversal prevention
   - File upload size limits enforcement
   - Secrets exposure in logs
   - SVG/HTML injection attacks

2. **WeasyPrint Integration**:
   - Proper error handling for PDF generation failures
   - Process-wide patches of WeasyPrint (weasysvg, weasyvsdx, the `app/weasyprint_*_patch.py` modules)
   - Resource cleanup (temporary files)

3. **Resource Management**:
   - Temporary file cleanup
   - Proper async/await patterns
   - Memory leaks in PDF/SVG processing

4. **Breaking Changes**:
   - API endpoint changes
   - Response format changes
   - Docker image compatibility
   - Environment variable changes

## Development Workflow

### Code Quality Standards
- **Python Standards**: Follows PEP 8, enforced via Ruff (replaces Black/Flake8)
- **Type Checking**: ty (Astral); missing annotations are enforced by ruff `ANN` rules
- **Line Length**: 240 characters (configured in pyproject.toml)
- **Coverage Requirement**: 90% minimum test coverage
- **Pre-commit Hooks**: Automatic formatting, linting, security checks, and OpenAPI generation

### Pre-commit Hook Integration
The repository uses extensive pre-commit hooks including:
- Ruff formatting and linting (automatically fixes issues)
- ty type checking
- OpenAPI schema auto-generation (`scripts/precommit_generate_openapi.sh`)
- Security checks (gitleaks, sensitive data detection)
- Docker security (hadolint for Dockerfile linting)
- uv dependency management validation (lock file updates)
- Commitizen (validates conventional commit format)
- YAML/JSON/TOML validation and formatting

**Note**: Pre-commit runs all these checks automatically, no need to run them individually before committing.

### Testing Strategy
- **Unit Tests**: All components have corresponding test files in `tests/`
- **Container Testing**: `container-structure-test` validates Docker image structure
- **Security Scanning**: Grype for vulnerability assessment
- **Coverage**: Enforced 90% minimum with detailed reporting

### OpenAPI Schema Management
- Auto-generated during pre-commit via `scripts/precommit_generate_openapi.sh`
- Stored at `docs/openapi.json`
- Served at `/static/openapi.json` and docs at `/api/docs`
- Script starts local FastAPI instance, downloads schema, and formats with jq

## Important Notes

### Dependency Management
- Uses uv for Python dependency management
- Dependencies defined in standard `[project.dependencies]` format in `pyproject.toml`
- Fully compatible with Renovate for automated dependency updates
- Lock file: `uv.lock`
- Renovate handles automated dependency updates
- Renovate updates the Python version in `.tool-versions` through its `asdf` manager, which the shared preset enables.
- Python 3.15 required

### Docker Considerations
- Multi-architecture support (amd64/arm64). The release builds each platform on a runner of its own architecture (`ubuntu-24.04` and `ubuntu-24.04-arm`, the same Ubuntu on both) and joins them with `docker buildx imagetools create`: under QEMU the Visio stage would compile for far longer
- Uses `--init` flag for proper signal handling and zombie process reaping
- **Non-root user**: Container runs as `appuser` (uid 1000) for enhanced security
- **Python via uv**: Python version installed from `.tool-versions` file (single source of truth)
- **Base image**: `alpine`, pinned by tag and digest, with uv for Python management. Its stable branch gets fixes in point releases, so grype and trivy find next to nothing in a current one, where Debian kept unfixed findings in the libraries the service loads. A stale digest brings them back: 3.23.7 had 1 critical and 6 high in glib
- **musl**: Alpine's libc. uv installs the musl build of Python, and every dependency installs from a musllinux wheel. musl is the source of the three items below
- **mimalloc**: `LD_PRELOAD=/usr/lib/libmimalloc.so.2`, from `mimalloc2`. The malloc of musl makes conversions about 30% slower than on glibc; mimalloc about 20%. `-e LD_PRELOAD=` at `docker run` turns it off
- **Thread stack**: musl gives a thread 128 KiB of stack, and WeasyPrint overflowed it at about 160 nested elements with SIGSEGV, which killed the service. The lifespan sets `threading.stack_size()` to 8 MiB, the glibc default, before it creates the rendering pool. `test_deeply_nested_html_does_not_crash_the_service` asserts it
- **No `malloc_trim`**: musl loads as `libc.so.6` but lacks `malloc_trim`. `memory_manager` then calls `mi_collect` of mimalloc for `RECLAIM_MEMORY_AFTER_CONVERSION`
- **Fonts from Debian**: a `debian:trixie-slim` stage installs the font packages. The runtime takes their files, copyright files and fontconfig rules (`/opt/weasyprint/fontconfig`, selected by `FONTCONFIG_FILE`), so the PDFs stay as on Debian. Other fonts would change them. The apk database does not know these fonts: syft writes their CycloneDX SBOM to `/usr/share/doc/debian-fonts.cdx.json`
- Includes the fonts the documents use. No browser: weasysvg draws SVG, the image has no Chromium and no Playwright
- libharfbuzz-subset (Alpine's `harfbuzz-subset` package) lets WeasyPrint subset fonts with HarfBuzz. Without it WeasyPrint falls back to fontTools, warns once per font, and renders small documents about 40% slower. `test_fonts_are_subset_with_harfbuzz` asserts it
- Visio drawings: weasyvsdx draws VSDX and VSD as vector through `vsd2xhtml` of libvisio (`app/vsdx_renderer.py`, installed at import of the controller). Alpine's libvisio is not 0.1.7, and its emf2svg is only in `edge/testing`: the `visio` stage builds librevenge 0.0.5, libvisio 0.1.7 (the release weasyvsdx is tested with) and libemf2svg 1.1.0 from their upstream releases, by checksum, into `/opt/visio`. Debian builds the same releases without patches. musl has no `argp_parse`, so `emf2svg-conv` links the static libargp of `argp-standalone`. `vsd2xhtml`, `vsd2raw` (weasyvsdx places text by its output and looks for it next to `vsd2xhtml`) and `emf2svg-conv` are linked into `/usr/local/bin`. The libraries they link come from Alpine, installed by soname from `/opt/visio/needed`. The scanners do not see these three projects. The Dockerfile and the structure test check `vsd2xhtml --version`. `emf2svg`, Carlito, Caladea and Selawik (from its GitHub release, by checksum) serve the drawings. weasyvsdx draws text with the `foreign_object` feature of weasysvg, which is installed first. Without `vsd2xhtml` nothing is patched and Visio images are left out. LibreOffice is gone
- Logging directory `/opt/weasyprint/logs` with timestamped log files
- Custom fonts can be mounted via `/usr/share/fonts/custom`
- The apk list holds what WeasyPrint and the scripts need: Pango, HarfBuzz subsetting, fontconfig, bash and mimalloc, plus the libraries of the Visio tools. container-structure-test expands `$name` in its arguments itself: a check that needs a shell variable is written in Python
- The image has no compiler: `uv sync` runs with `--no-build`, so a dependency without a wheel for the Python of `.tool-versions` fails the build instead of compiling.
- pip is removed from the uv-installed Python in `/opt/python`, in the layer that installs it. Nothing in the image uses pip, and image scanners report the packages it vendors. The container structure test asserts it is absent.
- Every `uv run` in the Dockerfile needs `--no-sync`: without it uv syncs the default groups again and puts the `dev` group (ruff, ty, pre-commit) into the image. The container structure test asserts they are absent.
- **OCI labels**: Security metadata labels for container scanning tools

### Security and Compliance
- Follows security practices with comprehensive pre-commit hooks
- Git commit signing required (`--gpg-sign`)
- Sensitive data leak prevention (URLs, ticket numbers, UE numbers)
- No secrets or credentials should be committed
- Vulnerability scanning via Grype
- Static analysis via ty

### Request/Response Flow
1. **HTML to PDF Conversion**: Client sends HTML → HtmlParser processes → WeasyPrint renders, drawing SVG through weasysvg → PDF returned
2. **With Attachments**: Multipart form → FormParser validates limits → AttachmentManager extracts files → HtmlParser resolves references → WeasyPrint renders, drawing SVG through weasysvg → PDF returned
3. **Application Lifecycle**: FastAPI startup → the PDF rendering pool and the metrics server start → FastAPI shutdown → the metrics server stops, queued renderings are dropped
4. **Metrics**: each `/convert/*` request records its success or failure in `ConversionMetrics` and in the Prometheus counters
5. **Shutdown on SIGTERM**: `docker stop` sends SIGTERM → `entrypoint.sh` runs the server via `exec`, so the signal reaches it → uvicorn stops accepting requests, waits up to `GRACEFUL_SHUTDOWN_TIMEOUT` → lifespan shutdown closes the metrics server → last log line is `Service shutdown complete` → exit code 143 (uvicorn re-raises the signal), which is a normal stop

### Monitoring

The service keeps conversion metrics in `ConversionMetrics` (`app/conversion_metrics.py`):
- Total and failed HTML→PDF conversions, error rate percentage, average conversion time
- Uptime since the service started, total and available system memory
- `/health?detailed=true` returns them as JSON, `/metrics` exports them to Prometheus

**Monitoring Dashboard:**
```bash
# Access interactive web dashboard
open http://localhost:9080/dashboard

# Dashboard features:
# - 5-second auto-refresh
# - PDF conversions, failures, error rate and average time
# - Uptime and a chart of the system memory
# - Service and WeasyPrint versions and the SVG renderer
# - Configurable light/dark theme (DASHBOARD_THEME env var, default: light)

# Configure dashboard theme
DASHBOARD_THEME=dark uv run python -m app.weasyprint_service_application --port 9080
```

**Monitoring API:**
```bash
# Simple health check
curl http://localhost:9080/health
# Response: OK (200)

# Detailed health with metrics (used by dashboard)
curl http://localhost:9080/health?detailed=true
# Response (JSON):
{
  "status": "healthy",
  "version": "70.0.7",
  "weasyprint_version": "70.0",
  "svg_renderer": "weasysvg",
  "metrics": {
    "pdf_generations": 1523,
    "failed_pdf_generations": 2,
    "avg_pdf_generation_time_ms": 145.23,
    "error_pdf_generation_rate_percent": 0.13,
    "uptime_seconds": 3600.45,
    "total_memory_mb": 16384.0,
    "available_memory_mb": 8192.0
  }
}
```

### Prometheus Integration

The service exposes metrics in Prometheus format via the `/metrics` endpoint on a **dedicated port** (default: 9180) for security. This allows network-level isolation between the main API and metrics endpoint (e.g., restricting metrics access to Prometheus server only via security groups).

**Key Metrics Exposed:**

**Automatic FastAPI Metrics** (provided by `prometheus-fastapi-instrumentator`):
- `http_request_duration_seconds` - HTTP request duration histogram
- `http_requests_total` - Total HTTP requests counter
- `http_requests_inprogress` - Current in-flight HTTP requests

**Custom Conversion Metrics:**
- `pdf_generations_total` - Total successful HTML→PDF conversions
- `pdf_generation_failures_total` - Failed HTML→PDF conversions
- `pdf_generation_duration_seconds` - PDF generation duration histogram (buckets: 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
- `pdf_generation_error_rate_percent` - PDF generation error rate percentage
- `avg_pdf_generation_time_seconds` - Average PDF generation time
- `uptime_seconds` - Service uptime

**System & Resource Metrics:**
- `system_memory_total_bytes` - Total system memory in bytes
- `system_memory_available_bytes` - Available system memory in bytes
- `process_resident_memory_bytes`, `process_cpu_seconds_total` - Memory and CPU of the service process, from the default collectors of prometheus_client

**Usage Example:**

```bash
# Fetch Prometheus metrics (served on dedicated port 9180)
curl http://localhost:9180/metrics

# Example output (excerpt):
# HELP pdf_generations_total Total number of successful HTML to PDF conversions
# TYPE pdf_generations_total counter
pdf_generations_total 1523.0
# HELP pdf_generation_failures_total Total number of failed HTML to PDF conversions
# TYPE pdf_generation_failures_total counter
pdf_generation_failures_total 2.0
# HELP uptime_seconds Service uptime in seconds
# TYPE uptime_seconds gauge
uptime_seconds 3600.45
```

**Prometheus Scrape Configuration:**

```yaml
scrape_configs:
  - job_name: 'weasyprint-service'
    static_configs:
      - targets: ['weasyprint-service:9180']  # Metrics served on dedicated port
    metrics_path: '/metrics'
    scrape_interval: 10s
    scrape_timeout: 5s
```

**Security Group Configuration (EC2/AWS example):**

```bash
# Application port - accessible by clients
Inbound: TCP 9080 from <client CIDR or ALB SG>

# Metrics port - Prometheus only
Inbound: TCP 9180 from <Prometheus server IP/SG only>
```

**Grafana Dashboard Queries:**

```promql
# PDF generation rate (requests per second)
rate(pdf_generations_total[5m])

# Error rate percentage
rate(pdf_generation_failures_total[5m]) / (
  rate(pdf_generations_total[5m]) +
  rate(pdf_generation_failures_total[5m])
) * 100

# 95th percentile PDF generation duration
histogram_quantile(0.95, rate(pdf_generation_duration_seconds_bucket[5m]))

# Memory usage trend
process_resident_memory_bytes / 1024 / 1024
```

**Alerting Rules Example:**

```yaml
groups:
  - name: weasyprint_service
    interval: 30s
    rules:
      - alert: HighPDFGenerationErrorRate
        expr: pdf_generation_error_rate_percent > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High PDF generation error rate"
          description: "PDF generation error rate is {{ $value }}% (threshold: 5%)"

      - alert: WeasyPrintServiceDown
        expr: up{job="weasyprint-service"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "WeasyPrint service is down"
          description: "The WeasyPrint service has been unreachable for 2 minutes"

      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes > 2147483648  # 2GB
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High service memory usage"
          description: "Service memory usage is {{ $value | humanize }}B"
```

**Complete Monitoring Stack:**

For a full monitoring setup with Prometheus and Grafana, see `monitoring/README.md`. Quick start:

```bash
# From project root
cd monitoring

# Start monitoring stack (WeasyPrint service + Prometheus + Grafana)
./start-monitoring.sh

# Access Grafana dashboard
open http://localhost:3000/d/weasyprint-service

# Generate test load
./generate-load.sh

# Stop monitoring stack
./stop-monitoring.sh
```

All monitoring configuration files are located in the `monitoring/` directory.
