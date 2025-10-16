# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Before Committing - Run Full Test Suite
```bash
# Run complete test suite (optimized sequence, no redundancy)
# 1. Run tox - handles linting, formatting, type checking, and tests with coverage
uv run tox

# 2. Run pre-commit hooks - final validation including security checks and commit format
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
uv sync --extra dev --extra test
```

### Testing and Quality Assurance
```bash
# Quick test during development
uv run pytest tests/test_specific_file.py -v

# Run specific test within a file
uv run pytest tests/test_svg_processor.py::test_process_valid_svg -v

# Manual linting/formatting (if needed outside of tox/pre-commit)
uv run ruff format
uv run ruff check --fix
uv run mypy .

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
```

**Load Test Features:**
- Real-time progress display with success/failure counts
- Comprehensive metrics: min/max/avg/p50/p95/p99 response times
- Requests per second calculation
- Status code and error distribution
- Configurable scenarios (simple, complex, SVG)
- Export to JSON or CSV format
- Async/concurrent request execution using httpx

**Use Cases:**
- Validate service behavior under load
- Identify performance bottlenecks
- Test Chromium browser pool behavior with SVG conversions
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

# Run development container
docker run --detach --init --publish 9080:9080 --name weasyprint-service weasyprint-service:0.0.0

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
- **SvgProcessor** (`app/svg_processor.py`): Converts SVG to PNG via CDP (Chrome DevTools Protocol) with configurable device scaling (`DEVICE_SCALE_FACTOR` env var)
- **ChromiumManager** (`app/chromium_manager.py`): Manages persistent Chromium browser instance for SVG to PNG conversion via CDP with proactive health monitoring
  - Background health monitoring: Periodic checks (configurable interval) to detect browser issues
  - Auto-restart on degraded health: Automatically restarts browser after 3 consecutive health check failures
  - Metrics collection: Tracks conversions, errors, response times, restarts, and uptime
  - Configurable retry logic: Automatic retry with browser restart on conversion failures
- **Schemas** (`app/schemas.py`): Pydantic models for API request/response validation

### API Endpoints Architecture
- `/dashboard` - Interactive web-based monitoring dashboard with real-time metrics visualization
  - Real-time charts for queue size, active conversions, response times, and resource usage
  - Auto-refresh every 5 seconds
  - Dark theme optimized for monitoring displays
- `/health` - Health check endpoint with optional detailed metrics
  - Simple mode (default): Returns 200 "OK" or 503 "Service Unavailable"
  - Detailed mode (`?detailed=true`): Returns JSON with metrics, browser status, health monitoring info, and queue metrics
- `/version` - Service version information (Python, WeasyPrint, Chromium, service versions)
- `/convert/html` - Basic HTML to PDF conversion (accepts HTML string, returns PDF binary)
- `/convert/html-with-attachments` - HTML to PDF with file attachments support (multipart/form-data, for embedded resources)

### Configuration and Environment Variables

**General Configuration:**
- `LOG_LEVEL`: Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL) - defaults to INFO
- `LOG_DIR`: Directory for log files (defaults to `/opt/weasyprint/logs`)
- `WEASYPRINT_SERVICE_VERSION`: Service version (set during build)
- `WEASYPRINT_SERVICE_BUILD_TIMESTAMP`: Build timestamp (set during build)

**Form Processing:**
- `FORM_MAX_FIELDS`: Maximum number of form fields (default: 1000)
- `FORM_MAX_FILES`: Maximum number of file uploads (default: 1000)
- `FORM_MAX_PART_SIZE`: Maximum size per form part in bytes (default: 10485760/10MB)

**Chromium/SVG Processing:**
- `DEVICE_SCALE_FACTOR`: SVG to PNG conversion scaling factor via CDP (float, 1.0-10.0, default: 1.0)
- `MAX_CONCURRENT_CONVERSIONS`: Max concurrent SVG conversions (1-100, default: 10)
- `CHROMIUM_RESTART_AFTER_N_CONVERSIONS`: Restart Chromium after N conversions (0-10000, default: 0 = disabled)
- `CHROMIUM_MAX_CONVERSION_RETRIES`: Max retry attempts on conversion failure (1-10, default: 2)
- `CHROMIUM_CONVERSION_TIMEOUT`: Timeout in seconds for each conversion (5-300, default: 30)

**Health Monitoring (New):**
- `CHROMIUM_HEALTH_CHECK_ENABLED`: Enable background health monitoring (true/false, default: true)
- `CHROMIUM_HEALTH_CHECK_INTERVAL`: Interval in seconds for background health checks (10-300, default: 30)

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

**Type Checking** (handled by MyPy):
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
- Playwright Chromium for SVG conversion

### Project-Specific Review Focus

**DO focus on:**
1. **Security**:
   - Input validation and sanitization
   - Path traversal prevention
   - File upload size limits enforcement
   - Secrets exposure in logs
   - SVG/HTML injection attacks

2. **WeasyPrint/Chromium Integration**:
   - Proper error handling for PDF generation failures
   - ChromiumManager lifecycle management
   - CDP connection handling
   - Resource cleanup (browser tabs, temporary files)

3. **Resource Management**:
   - Temporary file cleanup
   - Proper async/await patterns
   - Memory leaks in PDF/SVG processing
   - Browser instance cleanup

4. **Breaking Changes**:
   - API endpoint changes
   - Response format changes
   - Docker image compatibility
   - Environment variable changes

## Development Workflow

### Code Quality Standards
- **Python Standards**: Follows PEP 8, enforced via Ruff (replaces Black/Flake8)
- **Type Checking**: MyPy with strict typing (`disallow_untyped_defs = true`)
- **Line Length**: 240 characters (configured in pyproject.toml)
- **Coverage Requirement**: 90% minimum test coverage
- **Pre-commit Hooks**: Automatic formatting, linting, security checks, and OpenAPI generation

### Pre-commit Hook Integration
The repository uses extensive pre-commit hooks including:
- Ruff formatting and linting (automatically fixes issues)
- MyPy type checking (strict mode)
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
- Stored at `app/static/openapi.json`
- Served at `/static/openapi.json` and docs at `/api/docs`
- Script starts local FastAPI instance, downloads schema, and formats with jq

## Important Notes

### Dependency Management
- Uses uv for Python dependency management
- Dependencies defined in standard `[project.dependencies]` format in `pyproject.toml`
- Fully compatible with Renovate for automated dependency updates
- Lock file: `uv.lock`
- Renovate handles automated dependency updates
- Python 3.13+ required

### Docker Considerations
- Multi-architecture support (amd64/arm64)
- Uses `--init` flag for proper signal handling and zombie process reaping
- Includes fonts and Playwright Chromium for complete PDF rendering capabilities
- Logging directory `/opt/weasyprint/logs` with timestamped log files
- Custom fonts can be mounted via `/usr/share/fonts/custom`
- Playwright Chromium browser installed via `playwright install chromium --with-deps`

### Security and Compliance
- Follows security practices with comprehensive pre-commit hooks
- Git commit signing required (`--gpg-sign`)
- Sensitive data leak prevention (URLs, ticket numbers, UE numbers)
- No secrets or credentials should be committed
- Vulnerability scanning via Grype
- Static analysis via MyPy with strict typing

### Request/Response Flow
1. **HTML to PDF Conversion**: Client sends HTML → HtmlParser processes → SvgProcessor converts SVG to PNG via CDP → WeasyPrint renders → PDF returned
2. **With Attachments**: Multipart form → FormParser validates limits → AttachmentManager extracts files → HtmlParser resolves references → SvgProcessor converts SVG → WeasyPrint renders → PDF returned
3. **SVG Processing via CDP**: SVG detected → SvgProcessor uses ChromiumManager (persistent Chromium instance) → CDP creates browser tab → Renders SVG → Screenshots as PNG → Tab closed → PNG embedded in PDF
4. **Application Lifecycle**:
   - FastAPI startup → ChromiumManager starts persistent Chromium browser
   - Background health monitor starts (if enabled) → Periodic health checks every 30s (configurable)
   - Handles all SVG conversions with automatic retry and metrics collection
   - Auto-restart on health degradation (3 consecutive failures)
   - FastAPI shutdown → Health monitor stops → Chromium stops gracefully

### Chromium Health Monitoring

The ChromiumManager includes proactive health monitoring to ensure reliability:

**Features:**
- **Background Health Checks**: Runs every 30 seconds (configurable via `CHROMIUM_HEALTH_CHECK_INTERVAL`)
- **Automatic Recovery**: Restarts browser after 3 consecutive health check failures
- **Metrics Collection**: Tracks all conversions, failures, response times, and system uptime
- **Retry Logic**: Automatic retry with browser restart on conversion errors (configurable via `CHROMIUM_MAX_CONVERSION_RETRIES`)
- **Queue Monitoring**: Real-time tracking of request queue and active conversions
- **Detailed Health Endpoint**: Access `/health?detailed=true` for JSON metrics including:
  - Total conversions and failures (HTML→PDF and SVG→PNG)
  - Error rate percentage
  - Average conversion time
  - Browser restarts count
  - Uptime and last health check status
  - Queue metrics: queue size, active conversions, max queue size, average queue wait time

**Configuration:**
```bash
# Enable/disable health monitoring (default: true)
CHROMIUM_HEALTH_CHECK_ENABLED=true

# Health check interval in seconds (10-300, default: 30)
CHROMIUM_HEALTH_CHECK_INTERVAL=30

# Auto-restart after N conversions (0=disabled, default: 0)
CHROMIUM_RESTART_AFTER_N_CONVERSIONS=1000

# Max retry attempts on failure (1-10, default: 2)
CHROMIUM_MAX_CONVERSION_RETRIES=3

# Conversion timeout in seconds (5-300, default: 30)
CHROMIUM_CONVERSION_TIMEOUT=30
```

**Monitoring Dashboard:**
```bash
# Access interactive web dashboard
open http://localhost:9080/dashboard

# Dashboard features:
# - Real-time charts with 5-second auto-refresh
# - Queue size and active conversions visualization
# - Response time metrics (HTML→PDF and SVG→PNG)
# - Resource usage (CPU and Memory)
# - Conversion rate graphs
# - System information and health status
# - Dark theme optimized for monitoring displays
```

**Monitoring API:**
```bash
# Simple health check
curl http://localhost:9080/health
# Response: OK (200) or Service Unavailable (503)

# Detailed health with metrics (used by dashboard)
curl http://localhost:9080/health?detailed=true
# Response (JSON):
{
  "status": "healthy",
  "chromium_running": true,
  "chromium_version": "131.0.6778.69",
  "health_monitoring_enabled": true,
  "metrics": {
    "total_conversions": 1523,
    "failed_conversions": 2,
    "total_svg_conversions": 458,
    "failed_svg_conversions": 1,
    "error_rate_percent": 0.13,
    "total_restarts": 0,
    "avg_conversion_time_ms": 145.23,
    "avg_svg_conversion_time_ms": 82.45,
    "last_health_check": "14:30:45 16.10.2025",
    "last_health_status": true,
    "consecutive_failures": 0,
    "uptime_seconds": 3600.45,
    "current_cpu_percent": 12.5,
    "avg_cpu_percent": 8.3,
    "total_memory_mb": 16384.0,
    "available_memory_mb": 8192.0,
    "current_chromium_memory_mb": 256.8,
    "avg_chromium_memory_mb": 234.5,
    "queue_size": 3,
    "max_queue_size": 15,
    "active_conversions": 7,
    "avg_queue_time_ms": 12.34,
    "max_concurrent_conversions": 10
  }
}
```
