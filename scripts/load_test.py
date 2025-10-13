#!/usr/bin/env python3
"""
Load testing script for WeasyPrint service.

This script performs configurable load testing against the WeasyPrint service,
collecting metrics and displaying real-time statistics.

Features:
- Configurable number of requests and concurrency
- Multiple test scenarios (simple HTML, complex HTML, SVG conversion)
- Real-time progress and statistics display
- Results export to console, JSON, or CSV

Usage examples:
    # Simple test with 100 requests, 10 concurrent workers
    python scripts/load_test.py --requests 100 --concurrency 10

    # Complex HTML test with custom URL and JSON output
    python scripts/load_test.py --url http://localhost:9080 --scenario complex --requests 500 --concurrency 20 --output results.json

    # SVG conversion stress test with CSV export
    python scripts/load_test.py --scenario svg --requests 1000 --concurrency 50 --output results.csv --format csv
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

try:
    import httpx
except ImportError:
    print("Error: httpx is required. Install dependencies: poetry install --with=test", file=sys.stderr)
    sys.exit(1)


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

    def __init__(self, base_url: str, scenario: str, concurrency: int, timeout: float):
        """
        Initialize load tester.

        Args:
            base_url: Base URL of the WeasyPrint service
            scenario: Test scenario (simple, complex, svg)
            concurrency: Number of concurrent workers
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.scenario = scenario
        self.concurrency = concurrency
        self.timeout = timeout
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
            return "/convert/html", "<html><body><h1>Load Test</h1><p>Simple HTML content for performance testing.</p></body></html>"
        elif self.scenario == "complex":
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    h1 { color: #333; }
                    table { border-collapse: collapse; width: 100%; margin: 20px 0; }
                    td, th { border: 1px solid #ddd; padding: 8px; text-align: left; }
                    th { background-color: #4CAF50; color: white; }
                </style>
            </head>
            <body>
                <h1>Complex Document</h1>
                <p>This is a more complex HTML document with tables and styling.</p>
                <table>
                    <tr><th>Column 1</th><th>Column 2</th><th>Column 3</th></tr>
            """
            # Add 50 rows to make it more complex
            for i in range(50):
                html += f"<tr><td>Row {i} Col 1</td><td>Row {i} Col 2</td><td>Row {i} Col 3</td></tr>\n"
            html += """
                </table>
            </body>
            </html>
            """
            return "/convert/html", html
        elif self.scenario == "svg":
            html = """
            <!DOCTYPE html>
            <html>
            <body>
                <h1>SVG Conversion Test</h1>
                <svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
                    <circle cx="100" cy="100" r="80" fill="blue"/>
                    <text x="100" y="110" text-anchor="middle" fill="white" font-size="20">SVG Test</text>
                </svg>
            </body>
            </html>
            """
            return "/convert/html", html
        else:
            raise ValueError(f"Unknown scenario: {self.scenario}")

    async def _send_request(self, client: httpx.AsyncClient, request_id: int) -> RequestStats:
        """
        Send a single request and collect statistics.

        Args:
            client: HTTP client
            request_id: Request identifier

        Returns:
            Request statistics
        """
        endpoint, html_content = self._get_test_payload()
        url = f"{self.base_url}{endpoint}"

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

                stats = await self._send_request(client, request_id)

                async with self.lock:
                    self.results.append(stats)
                    self.progress_counter += 1
                    # Print progress every 10 requests or on completion
                    if self.progress_counter % 10 == 0 or self.progress_counter == total_requests:
                        progress_pct = (self.progress_counter / total_requests) * 100
                        print(f"\rProgress: {self.progress_counter}/{total_requests} ({progress_pct:.1f}%) - Success: {sum(1 for r in self.results if r.success)}, Failed: {sum(1 for r in self.results if not r.success)}", end="", flush=True)

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
        print("-" * 80)

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

    parser.add_argument("--timeout", "-t", type=float, default=30.0, help="Request timeout in seconds (default: 30.0)")

    parser.add_argument("--output", "-o", type=Path, help="Output file path (optional, if not specified results are only printed to console)")

    parser.add_argument("--format", "-f", choices=["json", "csv"], default="json", help="Output format: json or csv (default: json)")

    args = parser.parse_args()

    # Validate arguments
    if args.requests <= 0:
        parser.error("--requests must be positive")
    if args.concurrency <= 0:
        parser.error("--concurrency must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    # Run load test
    try:
        tester = LoadTester(base_url=args.url, scenario=args.scenario, concurrency=args.concurrency, timeout=args.timeout)

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
