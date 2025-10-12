# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Before Committing - Run Full Test Suite
```bash
# Run complete test suite (optimized sequence, no redundancy)
# 1. Run tox - handles linting, formatting, type checking, and tests with coverage
poetry run tox

# 2. Run pre-commit hooks - final validation including security checks and commit format
poetry run pre-commit run --all
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
# Install dependencies using Poetry
poetry install --with=dev,test
```

### Testing and Quality Assurance
```bash
# Quick test during development
poetry run pytest tests/test_specific_file.py -v

# Run specific test within a file
poetry run pytest tests/test_svg_processor.py::test_process_valid_svg -v

# Manual linting/formatting (if needed outside of tox/pre-commit)
poetry run ruff format
poetry run ruff check --fix
poetry run mypy .

# Generate/update OpenAPI schema (auto-runs in pre-commit)
scripts/precommit_generate_openapi.sh
```

### Local Development Server
```bash
# Start FastAPI development server
poetry run python -m app.weasyprint_service_application --port 9080

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
- **ChromiumManager** (`app/chromium_manager.py`): Manages persistent Chromium browser instance for SVG to PNG conversion via CDP
- **Schemas** (`app/schemas.py`): Pydantic models for API request/response validation

### API Endpoints Architecture
- `/health` - Health check endpoint (returns service status)
- `/version` - Service version information (Python, WeasyPrint, service versions)
- `/convert/html` - Basic HTML to PDF conversion (accepts HTML string, returns PDF binary)
- `/convert/html-with-attachments` - HTML to PDF with file attachments support (multipart/form-data, for embedded resources)

### Configuration and Environment Variables
- `LOG_LEVEL`: Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL) - defaults to INFO
- `LOG_DIR`: Directory for log files (defaults to `/opt/weasyprint/logs`)
- `DEVICE_SCALE_FACTOR`: SVG to PNG conversion scaling factor via CDP (float, e.g., 2.0, default: 1.0)
- `FORM_MAX_FIELDS`: Maximum number of form fields (default: 1000)
- `FORM_MAX_FILES`: Maximum number of file uploads (default: 1000)
- `FORM_MAX_PART_SIZE`: Maximum size per form part in bytes (default: 10485760/10MB)
- `WEASYPRINT_SERVICE_VERSION`: Service version (set during build)
- `WEASYPRINT_SERVICE_BUILD_TIMESTAMP`: Build timestamp (set during build)

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
- Using Poetry for package management
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
- Poetry dependency management validation (lock file updates)
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
- Uses Poetry for Python dependency management
- Dependencies defined in both `pyproject.toml` and `[tool.poetry.dependencies]` due to Renovate compatibility requirements
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
4. **Application Lifecycle**: FastAPI startup → ChromiumManager starts persistent Chromium browser → Handles all SVG conversions → FastAPI shutdown → ChromiumManager stops Chromium gracefully
