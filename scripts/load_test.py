#!/usr/bin/env python3
"""
Load testing script for WeasyPrint service.

This script performs configurable load testing against the WeasyPrint service,
collecting metrics and displaying real-time statistics.

Features:
- Configurable number of requests and concurrency
- Multiple test scenarios (simple HTML, complex HTML, SVG conversion)
- Real-time progress and statistics display
- Verbose mode with visual per-request tracking (shows "Request sent..." and completion status)
- Results export to console, JSON, or CSV

Usage examples:
    # Simple test with 100 requests, 10 concurrent workers (default: 10 pages, 3 SVGs per page)
    python scripts/load_test.py --requests 100 --concurrency 10

    # Verbose mode - visual tracking of each request (sent → completed)
    python scripts/load_test.py --requests 50 --concurrency 5 --verbose

    # Complex HTML test with custom URL and JSON output
    python scripts/load_test.py --url http://localhost:9080 --scenario complex --requests 500 --concurrency 20 --output results.json

    # SVG conversion stress test with 20 pages and 5 SVGs per page (verbose)
    python scripts/load_test.py --scenario svg --requests 1000 --concurrency 50 --pages 20 --svgs-per-page 5 --verbose

    # Large document test (50 pages, 10 SVGs per page)
    python scripts/load_test.py --scenario complex --pages 50 --svgs-per-page 10 --requests 100 --concurrency 5

    # Minimal test with single page, no SVGs
    python scripts/load_test.py --pages 1 --svgs-per-page 0 --requests 50
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass
class RequestStats:
    """Statistics for a single request."""

    status_code: int
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class LoadTestResults:
    """Aggregated load test results."""

    total_requests: int
    successful_requests: int
    failed_requests: int
    total_duration_sec: float
    min_response_ms: float
    max_response_ms: float
    avg_response_ms: float
    p50_response_ms: float
    p95_response_ms: float
    p99_response_ms: float
    requests_per_second: float
    status_codes: dict[int, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert results to dictionary."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "total_duration_sec": round(self.total_duration_sec, 2),
            "min_response_ms": round(self.min_response_ms, 2),
            "max_response_ms": round(self.max_response_ms, 2),
            "avg_response_ms": round(self.avg_response_ms, 2),
            "p50_response_ms": round(self.p50_response_ms, 2),
            "p95_response_ms": round(self.p95_response_ms, 2),
            "p99_response_ms": round(self.p99_response_ms, 2),
            "requests_per_second": round(self.requests_per_second, 2),
            "status_codes": self.status_codes,
            "errors": self.errors,
        }


class LoadTester:
    """Async load tester for WeasyPrint service."""

    def __init__(self, base_url: str, scenario: str, concurrency: int, timeout: float, pages: int, svgs_per_page: int, verbose: bool = False):
        """
        Initialize load tester.

        Args:
            base_url: Base URL of the WeasyPrint service
            scenario: Test scenario (simple, complex, svg)
            concurrency: Number of concurrent workers
            timeout: Request timeout in seconds
            pages: Number of pages to generate in PDF (default: 10)
            svgs_per_page: Number of SVG elements per page (default: 3)
            verbose: Enable verbose per-request output (default: False)
        """
        self.base_url = base_url.rstrip("/")
        self.scenario = scenario
        self.concurrency = concurrency
        self.timeout = timeout
        self.pages = pages
        self.svgs_per_page = svgs_per_page
        self.verbose = verbose
        self.results: list[RequestStats] = []
        self.lock = asyncio.Lock()
        self.progress_counter = 0

    def _get_test_payload(self) -> tuple[str, str]:
        """
        Get test payload based on scenario.

        Returns:
            Tuple of (endpoint, html_content)
        """
        if self.scenario == "simple":
            return self._generate_simple_html()
        elif self.scenario == "complex":
            return self._generate_complex_html()
        elif self.scenario == "svg":
            return self._generate_svg_html()
        else:
            raise ValueError(f"Unknown scenario: {self.scenario}")

    def _generate_svg_element(self, index: int, color: str) -> str:
        """Generate a single SVG element with varied content."""
        svg_types = [
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" style="margin: 10px;">
                <circle cx="100" cy="100" r="80" fill="{color}"/>
                <text x="100" y="110" text-anchor="middle" fill="white" font-size="16">SVG {index}</text>
            </svg>""",
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" style="margin: 10px;">
                <rect x="20" y="20" width="160" height="160" fill="{color}" rx="15"/>
                <text x="100" y="110" text-anchor="middle" fill="white" font-size="16">Box {index}</text>
            </svg>""",
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" style="margin: 10px;">
                <polygon points="100,20 180,180 20,180" fill="{color}"/>
                <text x="100" y="140" text-anchor="middle" fill="white" font-size="16">△ {index}</text>
            </svg>""",
        ]
        return svg_types[index % len(svg_types)]

    def _generate_simple_html(self) -> tuple[str, str]:
        """Generate simple HTML with multiple pages and SVG elements."""
        colors = ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

        html = """<!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #2c3e50; font-size: 28px; }
                h2 { color: #34495e; font-size: 20px; margin-top: 30px; }
                .page-break { page-break-after: always; }
                .svg-container { display: flex; flex-wrap: wrap; justify-content: space-around; margin: 20px 0; }
                p { line-height: 1.6; color: #555; }
            </style>
        </head>
        <body>
        """

        for page_num in range(self.pages):
            html += f"""
            <div class="{"page-break" if page_num < self.pages - 1 else ""}">
                <h1>Load Test Document - Page {page_num + 1}</h1>
                <p>This is a multi-page document generated for load testing purposes.
                Page {page_num + 1} of {self.pages}. Each page contains SVG graphics and text content
                to simulate realistic PDF generation scenarios.</p>

                <h2>SVG Graphics Section</h2>
                <div class="svg-container">
            """

            for svg_num in range(self.svgs_per_page):
                color = colors[(page_num * self.svgs_per_page + svg_num) % len(colors)]
                html += self._generate_svg_element(page_num * self.svgs_per_page + svg_num + 1, color)

            html += """
                </div>
                <p>Additional content to fill the page. Lorem ipsum dolor sit amet, consectetur adipiscing elit.
                Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam,
                quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>
            </div>
            """

        html += """
        </body>
        </html>
        """
        return "/convert/html", html

    def _generate_complex_html(self) -> tuple[str, str]:
        """Generate complex HTML with tables, styling, and SVG elements."""
        colors = ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

        html = """<!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
                h2 { color: #34495e; margin-top: 30px; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; }
                td, th { border: 1px solid #bdc3c7; padding: 10px; text-align: left; }
                th { background-color: #3498db; color: white; font-weight: bold; }
                tr:nth-child(even) { background-color: #ecf0f1; }
                .page-break { page-break-after: always; }
                .svg-container { display: flex; flex-wrap: wrap; justify-content: space-around; margin: 20px 0; }
                .stats { background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin: 15px 0; }
            </style>
        </head>
        <body>
        """

        for page_num in range(self.pages):
            html += f"""
            <div class="{"page-break" if page_num < self.pages - 1 else ""}">
                <h1>Complex Performance Test Report - Page {page_num + 1}</h1>

                <div class="stats">
                    <strong>Document Statistics:</strong> Page {page_num + 1} of {self.pages} |
                    SVG Elements: {self.svgs_per_page} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </div>

                <h2>Data Table Section</h2>
                <table>
                    <tr>
                        <th>ID</th><th>Metric</th><th>Value</th><th>Status</th><th>Timestamp</th>
                    </tr>
            """

            # Add 20 rows per page
            for i in range(20):
                row_id = page_num * 20 + i + 1
                status = "Success" if (row_id % 3) != 0 else "Pending"
                html += f"""
                    <tr>
                        <td>{row_id:04d}</td>
                        <td>Metric-{row_id % 5}</td>
                        <td>{(row_id * 123.45) % 1000:.2f}</td>
                        <td>{status}</td>
                        <td>2025-10-13 14:{row_id % 60:02d}:00</td>
                    </tr>
                """

            html += """
                </table>

                <h2>Visual Elements</h2>
                <div class="svg-container">
            """

            for svg_num in range(self.svgs_per_page):
                color = colors[(page_num * self.svgs_per_page + svg_num) % len(colors)]
                html += self._generate_svg_element(page_num * self.svgs_per_page + svg_num + 1, color)

            html += """
                </div>
            </div>
            """

        html += """
        </body>
        </html>
        """
        return "/convert/html", html

    def _generate_svg_html(self) -> tuple[str, str]:
        """Generate SVG-focused HTML with maximum SVG content."""
        colors = ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#16a085"]

        html = """<!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #2c3e50; text-align: center; }
                h2 { color: #34495e; margin-top: 20px; border-left: 4px solid #3498db; padding-left: 10px; }
                .page-break { page-break-after: always; }
                .svg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
                .description { background-color: #f8f9fa; padding: 12px; border-radius: 5px; margin: 15px 0; }
            </style>
        </head>
        <body>
        """

        for page_num in range(self.pages):
            html += f"""
            <div class="{"page-break" if page_num < self.pages - 1 else ""}">
                <h1>SVG Graphics Showcase - Page {page_num + 1}</h1>

                <div class="description">
                    <strong>SVG Conversion Test:</strong> This page contains {self.svgs_per_page} SVG elements
                    that are converted to PNG via Chromium CDP for PDF rendering. Page {page_num + 1} of {self.pages}.
                </div>

                <h2>SVG Graphics Grid</h2>
                <div class="svg-grid">
            """

            for svg_num in range(self.svgs_per_page):
                color = colors[(page_num * self.svgs_per_page + svg_num) % len(colors)]
                html += f"<div>{self._generate_svg_element(page_num * self.svgs_per_page + svg_num + 1, color)}</div>"

            html += """
                </div>

                <p style="margin-top: 20px; color: #7f8c8d; font-size: 14px;">
                    Each SVG element above is processed through the Chromium browser via CDP (Chrome DevTools Protocol),
                    converted to PNG format, and then embedded into the final PDF document. This ensures consistent
                    rendering across all platforms and PDF viewers.
                </p>
            </div>
            """

        html += """
        </body>
        </html>
        """
        return "/convert/html", html

    async def _send_request(self, client: httpx.AsyncClient, request_id: int, total_requests: int) -> RequestStats:
        """
        Send a single request and collect statistics.

        Args:
            client: HTTP client
            request_id: Request identifier
            total_requests: Total number of requests (for display)

        Returns:
            Request statistics
        """
        endpoint, html_content = self._get_test_payload()
        url = f"{self.base_url}{endpoint}"

        # Print "request sent" message in verbose mode
        if self.verbose:
            print(f"[{request_id + 1:4d}/{total_requests}] → Request sent...")

        start_time = time.time()
        try:
            response = await client.post(
                url,
                content=html_content,
                headers={"Content-Type": "text/html", "Accept": "*/*"},
                timeout=self.timeout,
            )
            duration_ms = (time.time() - start_time) * 1000
            success = 200 <= response.status_code < 300

            return RequestStats(status_code=response.status_code, duration_ms=duration_ms, success=success, error=None if success else f"HTTP {response.status_code}")
        except httpx.TimeoutException:
            duration_ms = (time.time() - start_time) * 1000
            return RequestStats(status_code=0, duration_ms=duration_ms, success=False, error="Timeout")
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return RequestStats(status_code=0, duration_ms=duration_ms, success=False, error=str(e))

    async def _worker(self, client: httpx.AsyncClient, queue: asyncio.Queue, total_requests: int) -> None:
        """
        Worker coroutine that processes requests from queue.

        Args:
            client: HTTP client
            queue: Request queue
            total_requests: Total number of requests (for progress display)
        """
        while True:
            try:
                request_id = await queue.get()
                if request_id is None:  # Poison pill
                    queue.task_done()
                    break

                stats = await self._send_request(client, request_id, total_requests)

                async with self.lock:
                    self.results.append(stats)
                    self.progress_counter += 1

                    if self.verbose:
                        # Simple visual output: request completed
                        status_icon = "✓" if stats.success else "✗"
                        error_str = f" ({stats.error})" if stats.error else ""

                        print(f"[{self.progress_counter:4d}/{total_requests}] {status_icon} Completed in {stats.duration_ms:7.2f}ms{error_str}")
                    # Compact progress bar (every 10 requests or on completion)
                    elif self.progress_counter % 10 == 0 or self.progress_counter == total_requests:
                        progress_pct = (self.progress_counter / total_requests) * 100
                        print(
                            f"\rProgress: {self.progress_counter}/{total_requests} ({progress_pct:.1f}%) - Success: {sum(1 for r in self.results if r.success)}, Failed: {sum(1 for r in self.results if not r.success)}",
                            end="",
                            flush=True,
                        )

                queue.task_done()
            except Exception as e:
                print(f"\nWorker error: {e}", file=sys.stderr)
                queue.task_done()

    async def run(self, num_requests: int) -> LoadTestResults:
        """
        Run load test.

        Args:
            num_requests: Number of requests to send

        Returns:
            Aggregated load test results
        """
        print(f"Starting load test: {num_requests} requests with {self.concurrency} concurrent workers")
        print(f"Target: {self.base_url}")
        print(f"Scenario: {self.scenario}")
        print(f"Verbose mode: {'enabled' if self.verbose else 'disabled'}")
        print("-" * 80)
        if self.verbose:
            print("Sending requests and tracking completion...")
            print()

        # Create queue and fill with request IDs
        queue: asyncio.Queue = asyncio.Queue()
        for i in range(num_requests):
            await queue.put(i)

        # Add poison pills for workers
        for _ in range(self.concurrency):
            await queue.put(None)

        start_time = time.time()

        # Create HTTP client and workers
        async with httpx.AsyncClient() as client:
            workers = [asyncio.create_task(self._worker(client, queue, num_requests)) for _ in range(self.concurrency)]

            # Wait for all requests to complete
            await queue.join()

            # Wait for workers to finish
            await asyncio.gather(*workers)

        total_duration = time.time() - start_time
        if not self.verbose:
            print()  # New line after progress
        print("-" * 80)

        return self._calculate_results(total_duration)

    def _calculate_results(self, total_duration: float) -> LoadTestResults:
        """
        Calculate aggregated results from collected statistics.

        Args:
            total_duration: Total test duration in seconds

        Returns:
            Aggregated results
        """
        if not self.results:
            raise ValueError("No results to calculate")

        successful = [r for r in self.results if r.success]
        failed = [r for r in self.results if not r.success]

        durations = sorted([r.duration_ms for r in self.results])

        # Calculate percentiles
        def percentile(data: list[float], p: float) -> float:
            k = (len(data) - 1) * p
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] + c * (data[f + 1] - data[f])
            return data[f]

        # Count status codes
        status_codes: dict[int, int] = defaultdict(int)
        for r in self.results:
            status_codes[r.status_code] += 1

        # Count errors
        errors: dict[str, int] = defaultdict(int)
        for r in failed:
            if r.error:
                errors[r.error] += 1

        return LoadTestResults(
            total_requests=len(self.results),
            successful_requests=len(successful),
            failed_requests=len(failed),
            total_duration_sec=total_duration,
            min_response_ms=min(durations),
            max_response_ms=max(durations),
            avg_response_ms=sum(durations) / len(durations),
            p50_response_ms=percentile(durations, 0.50),
            p95_response_ms=percentile(durations, 0.95),
            p99_response_ms=percentile(durations, 0.99),
            requests_per_second=len(self.results) / total_duration,
            status_codes=dict(status_codes),
            errors=dict(errors),
        )


def print_results_console(results: LoadTestResults) -> None:
    """Print results to console in human-readable format."""
    print("\n" + "=" * 80)
    print("LOAD TEST RESULTS")
    print("=" * 80)
    print(f"Total Requests:       {results.total_requests}")
    print(f"Successful:           {results.successful_requests} ({results.successful_requests / results.total_requests * 100:.1f}%)")
    print(f"Failed:               {results.failed_requests} ({results.failed_requests / results.total_requests * 100:.1f}%)")
    print(f"Total Duration:       {results.total_duration_sec:.2f}s")
    print(f"Requests/sec:         {results.requests_per_second:.2f}")
    print()
    print("Response Times (ms):")
    print(f"  Min:                {results.min_response_ms:.2f}")
    print(f"  Max:                {results.max_response_ms:.2f}")
    print(f"  Average:            {results.avg_response_ms:.2f}")
    print(f"  Median (p50):       {results.p50_response_ms:.2f}")
    print(f"  95th percentile:    {results.p95_response_ms:.2f}")
    print(f"  99th percentile:    {results.p99_response_ms:.2f}")

    if results.status_codes:
        print()
        print("Status Codes:")
        for code, count in sorted(results.status_codes.items()):
            print(f"  {code}: {count}")

    if results.errors:
        print()
        print("Errors:")
        for error, count in sorted(results.errors.items(), key=lambda x: x[1], reverse=True):
            print(f"  {error}: {count}")

    print("=" * 80)


def save_results_json(results: LoadTestResults, output_file: Path) -> None:
    """Save results to JSON file."""
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "results": results.to_dict(),
    }

    with output_file.open("w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nResults saved to: {output_file}")


def save_results_csv(results: LoadTestResults, output_file: Path) -> None:
    """Save results to CSV file."""
    import csv

    with output_file.open("w", newline="") as f:
        writer = csv.writer(f)

        # Write summary
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Timestamp", datetime.now().isoformat()])
        writer.writerow(["Total Requests", results.total_requests])
        writer.writerow(["Successful Requests", results.successful_requests])
        writer.writerow(["Failed Requests", results.failed_requests])
        writer.writerow(["Total Duration (sec)", f"{results.total_duration_sec:.2f}"])
        writer.writerow(["Requests/sec", f"{results.requests_per_second:.2f}"])
        writer.writerow(["Min Response (ms)", f"{results.min_response_ms:.2f}"])
        writer.writerow(["Max Response (ms)", f"{results.max_response_ms:.2f}"])
        writer.writerow(["Avg Response (ms)", f"{results.avg_response_ms:.2f}"])
        writer.writerow(["P50 Response (ms)", f"{results.p50_response_ms:.2f}"])
        writer.writerow(["P95 Response (ms)", f"{results.p95_response_ms:.2f}"])
        writer.writerow(["P99 Response (ms)", f"{results.p99_response_ms:.2f}"])

        # Write status codes
        if results.status_codes:
            writer.writerow([])
            writer.writerow(["Status Code", "Count"])
            for code, count in sorted(results.status_codes.items()):
                writer.writerow([code, count])

        # Write errors
        if results.errors:
            writer.writerow([])
            writer.writerow(["Error", "Count"])
            for error, count in sorted(results.errors.items(), key=lambda x: x[1], reverse=True):
                writer.writerow([error, count])

    print(f"\nResults saved to: {output_file}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load testing tool for WeasyPrint service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--url", default="http://localhost:9080", help="Base URL of WeasyPrint service (default: http://localhost:9080)")

    parser.add_argument("--requests", "-n", type=int, default=100, help="Number of requests to send (default: 100)")

    parser.add_argument("--concurrency", "-c", type=int, default=10, help="Number of concurrent workers (default: 10)")

    parser.add_argument(
        "--scenario",
        "-s",
        choices=["simple", "complex", "svg"],
        default="simple",
        help="Test scenario: simple (basic HTML), complex (tables/styling), svg (SVG conversion) (default: simple)",
    )

    parser.add_argument("--timeout", "-t", type=float, default=120.0, help="Request timeout in seconds (default: 120.0)")

    parser.add_argument("--pages", "-p", type=int, default=10, help="Number of pages to generate in PDF (default: 10)")

    parser.add_argument("--svgs-per-page", type=int, default=3, help="Number of SVG elements per page (default: 3)")

    parser.add_argument("--output", "-o", type=Path, help="Output file path (optional, if not specified results are only printed to console)")

    parser.add_argument("--format", "-f", choices=["json", "csv"], default="json", help="Output format: json or csv (default: json)")

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output (print details for each request)")

    args = parser.parse_args()

    # Validate arguments
    if args.requests <= 0:
        parser.error("--requests must be positive")
    if args.concurrency <= 0:
        parser.error("--concurrency must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.pages <= 0:
        parser.error("--pages must be positive")
    if args.svgs_per_page < 0:
        parser.error("--svgs-per-page must be non-negative")

    # Run load test
    try:
        tester = LoadTester(
            base_url=args.url,
            scenario=args.scenario,
            concurrency=args.concurrency,
            timeout=args.timeout,
            pages=args.pages,
            svgs_per_page=args.svgs_per_page,
            verbose=args.verbose,
        )

        results = asyncio.run(tester.run(args.requests))

        # Print results to console
        print_results_console(results)

        # Save to file if requested
        if args.output:
            if args.format == "json":
                save_results_json(results, args.output)
            elif args.format == "csv":
                save_results_csv(results, args.output)

    except KeyboardInterrupt:
        print("\n\nLoad test interrupted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
