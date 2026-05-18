import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_HOST_BASE_URL = "http://localhost:8000"
DEFAULT_DOCKER_BASE_URL = "http://load_balancer"
EXPECTED_SERVERS = {"web-1", "web-2", "web-3"}


class LoadDistributionTestError(Exception):
    pass


def running_inside_docker():
    return Path("/.dockerenv").exists() or os.getenv("RUNNING_IN_DOCKER") == "1"


def default_base_url():
    if os.getenv("LOAD_BALANCER_TEST_BASE_URL"):
        return os.getenv("LOAD_BALANCER_TEST_BASE_URL")
    if running_inside_docker():
        return DEFAULT_DOCKER_BASE_URL
    return DEFAULT_HOST_BASE_URL


def parse_args():
    parser = argparse.ArgumentParser(description="Task 5 load distribution proof for HAProxy.")
    parser.add_argument(
        "--base-url",
        default=default_base_url(),
        help=(
            "Load balancer base URL. Defaults to LOAD_BALANCER_TEST_BASE_URL, "
            "http://load_balancer inside Docker, or http://localhost:8000 on the host."
        ),
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=int(os.getenv("LOAD_BALANCER_TEST_REQUESTS", "60")),
        help="Number of /api/server-info/ requests to send.",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait for health.")
    return parser.parse_args()


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def parse_json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_body": body}


def get_json(url, timeout=10):
    headers = {
        "Accept": "application/json",
        "Connection": "close",
    }
    parsed_url = urlparse(url)
    if parsed_url.hostname and "_" in parsed_url.hostname:
        # Docker service names may contain underscores, but Django correctly
        # rejects underscores in HTTP Host headers. Keep the Docker DNS target
        # while sending a syntactically valid Host header through HAProxy.
        headers["Host"] = "localhost"

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "status_code": response.status,
                "response": parse_json_body(body),
                "headers": dict(response.headers.items()),
                "duration_ms": duration_ms,
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status_code": exc.code,
            "response": parse_json_body(body),
            "headers": dict(exc.headers.items()),
            "duration_ms": duration_ms,
            "error": "",
        }
    except urllib.error.URLError as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status_code": None,
            "response": {},
            "headers": {},
            "duration_ms": duration_ms,
            "error": str(exc),
        }


def wait_for_health(base_url, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_result = None
    while time.monotonic() < deadline:
        last_result = get_json(f"{base_url}/api/health/", timeout=5)
        if last_result["status_code"] == 200 and last_result["response"].get("status") == "ok":
            return last_result
        time.sleep(1)

    raise LoadDistributionTestError(
        f"Load balancer did not become healthy at {base_url}/api/health/. "
        f"Last response: {last_result}"
    )


def collect_server_info(base_url, total_requests):
    if total_requests < 1:
        raise LoadDistributionTestError("--requests must be at least 1.")

    results = []
    for index in range(1, total_requests + 1):
        result = get_json(f"{base_url}/api/server-info/", timeout=10)
        result["request_number"] = index
        result["server_name"] = result["response"].get("server_name")
        result["hostname"] = result["response"].get("hostname")
        result["backend_header"] = get_header_case_insensitive(result["headers"], "X-Backend-Server")
        results.append(result)
    return results


def get_header_case_insensitive(headers, name):
    for header_name, value in headers.items():
        if header_name.lower() == name.lower():
            return value
    return None


def build_summary(base_url, total_requests, health_result, request_results):
    successful = [result for result in request_results if result["status_code"] == 200]
    failed = [result for result in request_results if result["status_code"] != 200]
    server_counts = Counter(result["server_name"] for result in successful if result["server_name"])
    unique_servers = set(server_counts)
    all_expected_reached = EXPECTED_SERVERS.issubset(unique_servers)
    response_has_server_name = all(bool(result["server_name"]) for result in successful)

    if server_counts:
        min_count = min(server_counts.values())
        max_count = max(server_counts.values())
    else:
        min_count = 0
        max_count = 0

    balanced_threshold = total_requests * 0.25
    distribution_reasonably_balanced = bool(server_counts) and (max_count - min_count) <= balanced_threshold
    only_one_server_reached = len(unique_servers) == 1
    passed = (
        len(successful) == total_requests
        and len(failed) == 0
        and len(unique_servers) >= 3
        and all_expected_reached
        and all(count > 0 for count in server_counts.values())
        and distribution_reasonably_balanced
        and response_has_server_name
    )

    return {
        "load_balancer_url": base_url,
        "strategy": "Round Robin",
        "total_requests": total_requests,
        "successful_responses": len(successful),
        "failed_responses": len(failed),
        "backend_distribution": dict(sorted(server_counts.items())),
        "unique_backend_servers_reached": len(unique_servers),
        "expected_servers": sorted(EXPECTED_SERVERS),
        "all_expected_servers_reached": all_expected_reached,
        "distribution_reasonably_balanced": distribution_reasonably_balanced,
        "balance_threshold": balanced_threshold,
        "min_backend_request_count": min_count,
        "max_backend_request_count": max_count,
        "health_endpoint_available": health_result["status_code"] == 200,
        "response_has_server_name": response_has_server_name,
        "only_one_server_reached": only_one_server_reached,
        "single_server_hint": (
            "The script may be calling a single Django container directly instead of HAProxy. "
            "Make sure the base URL points to the load balancer: http://load_balancer inside Docker "
            "or http://localhost:8000 from the host."
            if only_one_server_reached
            else ""
        ),
        "passed": passed,
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "load_distribution"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"load_distribution_task5_{timestamp}.json"
    latest_path = results_dir / "load_distribution_task5_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary):
    print("\nTask 5 - Load Distribution Proof\n")
    print(f"Load balancer URL: {summary['load_balancer_url']}")
    print(f"Strategy: {summary['strategy']}")
    print(f"Total requests: {summary['total_requests']}")
    print(f"Successful responses: {summary['successful_responses']}")
    print(f"Failed responses: {summary['failed_responses']}\n")
    print("Backend distribution:")
    for server_name, count in summary["backend_distribution"].items():
        print(f"- {server_name}: {count} requests")
    print(f"\nUnique backend servers reached: {summary['unique_backend_servers_reached']}")
    print(f"All expected servers reached: {'Yes' if summary['all_expected_servers_reached'] else 'No'}")
    print(
        "Distribution reasonably balanced: "
        f"{'Yes' if summary['distribution_reasonably_balanced'] else 'No'}"
    )
    print(f"Health endpoint available: {'Yes' if summary['health_endpoint_available'] else 'No'}")
    if summary["single_server_hint"]:
        print(f"\n{summary['single_server_hint']}")
    print(f"Result: {'PASSED' if summary['passed'] else 'FAILED'}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)

    try:
        health_result = wait_for_health(base_url, args.timeout)
        request_results = collect_server_info(base_url, args.requests)
        summary = build_summary(base_url, args.requests, health_result, request_results)
        result = {
            "summary": summary,
            "health_response": health_result,
            "requests": request_results,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(summary)
        print(f"\nSaved latest result: {latest_path}")
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except LoadDistributionTestError as exc:
        print(f"\nTask 5 load distribution proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
