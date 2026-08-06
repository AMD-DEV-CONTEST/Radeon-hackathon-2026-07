#!/usr/bin/env python3
"""
CodeRisk Agent — Performance Benchmark Script

Reproduces all performance data reported in README and project documentation.
Run this script on a Radeon Cloud instance with llama-server running.

Usage:
    # GPU mode (default)
    python scripts/benchmark.py

    # Custom server URL
    python scripts/benchmark.py --server-url http://localhost:8080

    # Save results to file
    python scripts/benchmark.py --output benchmark_results.json

Requirements:
    - llama-server running (GPU or CPU mode)
    - Python 3.12+
    - requests library
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library required. Install with: pip install requests")
    sys.exit(1)


def benchmark_token_generation(server_url: str, prompt: str, num_tokens: int = 256) -> float:
    """Measure token generation speed (tokens/second)."""
    response = requests.post(
        f"{server_url}/completion",
        json={
            "prompt": prompt,
            "n_predict": num_tokens,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()
    tokens_generated = data.get("tokens_predicted", num_tokens)
    timings = data.get("timings", {})
    # Use llama-server's own timing if available (more accurate)
    if timings and timings.get("predicted_per_second", 0) > 0:
        return timings["predicted_per_second"]
    # Fallback: manual timing
    return tokens_generated / timings.get("total", 1)


def benchmark_prompt_processing(server_url: str, context_prompt: str) -> float:
    """Measure prompt processing speed (tokens/second)."""
    response = requests.post(
        f"{server_url}/completion",
        json={
            "prompt": context_prompt,
            "n_predict": 1,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()
    timings = data.get("timings", {})
    if timings and timings.get("prompt_per_second", 0) > 0:
        return timings["prompt_per_second"]
    tokens_processed = data.get("tokens_evaluated", 0)
    total_time = timings.get("total", 1)
    return tokens_processed / total_time if total_time > 0 else 0


def benchmark_e2e(test_dir: str) -> tuple[float, dict]:
    """Run full E2E pipeline and measure time."""
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "main.py", "analyze", test_dir, "--output", "json"],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - start

    report = {}
    if result.returncode == 0:
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass

    return elapsed, report


def check_vram() -> dict | None:
    """Check VRAM usage via rocm-smi."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def check_gpu_info() -> dict | None:
    """Get GPU product name and basic info."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeRisk Agent — Performance Benchmark")
    parser.add_argument(
        "--server-url",
        default="http://localhost:8080",
        help="llama-server URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--test-dir",
        default="tests/test_cases/",
        help="Test directory for E2E benchmark (default: tests/test_cases/)",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.json",
        help="Output file for results (default: benchmark_results.json)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  CodeRisk Agent — Performance Benchmark")
    print("=" * 60)
    print(f"  Server: {args.server_url}")
    print(f"  Test dir: {args.test_dir}")
    print()

    results = {}
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    results["timestamp"] = timestamp
    results["server_url"] = args.server_url

    # --- 1. Token Generation Speed ---
    print("[1/5] Token Generation Speed...")
    code_prompt = (
        "Analyze this C code for security vulnerabilities:\n\n"
        "```c\n"
        '#include <stdio.h>\n'
        '#include <string.h>\n'
        "void process(char *user_input) {\n"
        "    char buf[64];\n"
        "    strcpy(buf, user_input);\n"
        '    printf("Data: %s\\n", buf);\n'
        "}\n"
        "```\n\n"
        "List all CWEs found with severity and fix suggestions:"
    )
    try:
        tps = benchmark_token_generation(args.server_url, code_prompt)
        results["token_generation_tps"] = round(tps, 1)
        print(f"  Result: {tps:.1f} t/s")
    except Exception as e:
        results["token_generation_tps"] = None
        print(f"  ERROR: {e}")

    # --- 2. Prompt Processing Speed ---
    print("\n[2/5] Prompt Processing Speed...")
    long_context = (
        "Analyze the following codebase for security issues. "
        "Check for buffer overflows, format string vulnerabilities, "
        "command injection, SQL injection, XSS, and other OWASP Top 10 issues. "
        "Provide detailed findings with CWE classifications.\n\n"
    ) * 100  # ~10K tokens
    try:
        pp_tps = benchmark_prompt_processing(args.server_url, long_context)
        results["prompt_processing_tps"] = round(pp_tps, 1)
        print(f"  Result: {pp_tps:.1f} t/s")
    except Exception as e:
        results["prompt_processing_tps"] = None
        print(f"  ERROR: {e}")

    # --- 3. VRAM Usage ---
    print("\n[3/5] VRAM Usage...")
    vram = check_vram()
    gpu_info = check_gpu_info()
    if vram:
        results["vram_info"] = vram
        print(f"  Result: VRAM data collected")
    else:
        results["vram_info"] = None
        print("  Skipped (rocm-smi not available)")
    if gpu_info:
        results["gpu_info"] = gpu_info

    # --- 4. E2E Pipeline ---
    print("\n[4/5] End-to-End Pipeline...")
    try:
        e2e_time, report = benchmark_e2e(args.test_dir)
        results["e2e_time_seconds"] = round(e2e_time, 1)
        results["e2e_time_minutes"] = round(e2e_time / 60, 1)
        if report:
            results["e2e_report_summary"] = {
                "total_risks": report.get("summary", {}).get("total_risks"),
                "files_scanned": report.get("summary", {}).get("files_scanned"),
            }
        print(f"  Result: {e2e_time:.1f}s ({e2e_time/60:.1f} min)")
    except Exception as e:
        results["e2e_time_seconds"] = None
        print(f"  ERROR: {e}")

    # --- 5. Network Verification ---
    print("\n[5/5] Network Isolation Check...")
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        # Try to connect to an external address (should fail if truly isolated)
        result_code = sock.connect_ex(("1.1.1.1", 443))
        sock.close()
        if result_code == 0:
            results["network_isolation"] = False
            print("  WARNING: External network accessible (not isolated)")
        else:
            results["network_isolation"] = True
            print("  Result: Network isolated (no external connections)")
    except Exception:
        results["network_isolation"] = True
        print("  Result: Network isolated (connection failed)")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("  Benchmark Summary")
    print("=" * 60)
    print(f"  Token Generation:  {results.get('token_generation_tps', 'N/A')} t/s")
    print(f"  Prompt Processing: {results.get('prompt_processing_tps', 'N/A')} t/s")
    print(f"  E2E Time:          {results.get('e2e_time_minutes', 'N/A')} min")
    print(f"  Network Isolated:  {results.get('network_isolation', 'N/A')}")
    print(f"  VRAM:              See {args.output} for details")
    print()

    # --- Save Results ---
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to: {args.output}")

    # --- Comparison with Reported Values ---
    print("\n" + "=" * 60)
    print("  Comparison with Reported Values")
    print("=" * 60)
    reported = {
        "token_generation_tps": 29.4,
        "prompt_processing_tps": 264.8,
        "e2e_time_minutes": 18,
    }
    for key, expected in reported.items():
        actual = results.get(key)
        if actual is not None:
            diff = ((actual - expected) / expected) * 100
            status = "✅" if abs(diff) < 20 else "⚠️"
            print(f"  {status} {key}: {actual} (reported: {expected}, diff: {diff:+.1f}%)")
        else:
            print(f"  ❌ {key}: N/A (reported: {expected})")

    print()


if __name__ == "__main__":
    main()
