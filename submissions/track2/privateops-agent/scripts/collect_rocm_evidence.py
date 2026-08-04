from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path


PROMPT = "In two concise sentences, explain how an auditable private Agent protects project data."


def command_output(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    return (completed.stdout + completed.stderr).strip()


def rocm_version() -> str:
    version_file = Path("/opt/rocm/.info/version")
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    output = command_output(["hipcc", "--version"])
    return next((line.strip() for line in output.splitlines() if "HIP version" in line), output.splitlines()[0])


def parse_gpu_proof(output: str) -> tuple[str, str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in output.splitlines():
        if line.strip().startswith("Agent ") and current:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)

    gpu_block = next(
        (block for block in blocks if any("Device Type:" in line and "GPU" in line for line in block)),
        output.splitlines(),
    )
    lines = [line.strip() for line in gpu_block if line.strip()]
    gfx = next((line for line in lines if "gfx" in line.lower()), "")
    marketing = next((line for line in lines if "Marketing Name" in line), "")
    if not gfx:
        raise RuntimeError("rocminfo did not expose a gfx device line.")
    gpu_name = marketing.split(":", 1)[-1].strip() if marketing else "AMD Radeon GPU"
    if "AMD Radeon" not in gpu_name:
        gpu_name = f"AMD Radeon {gpu_name}".strip()
    excerpt = "\n".join(item for item in [marketing, gfx] if item)
    return gpu_name, excerpt


def gpu_proof() -> tuple[str, str]:
    return parse_gpu_proof(command_output(["rocminfo"]))


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture real Radeon/ROCm benchmark evidence.")
    parser.add_argument("--app-url", default="http://127.0.0.1:8765")
    parser.add_argument("--model-endpoint", required=True)
    parser.add_argument("--model-name", required=True)
    args = parser.parse_args()

    gpu_name, rocminfo_excerpt = gpu_proof()
    payload = {
        "model": args.model_name,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "max_tokens": 160,
    }
    started = time.perf_counter()
    result = post_json(args.model_endpoint, payload)
    elapsed = time.perf_counter() - started
    usage = result.get("usage") or {}
    completion_tokens = int(usage.get("completion_tokens", 0))
    if completion_tokens <= 0:
        raise RuntimeError("The model response did not report completion_tokens; no throughput claim was recorded.")
    evidence = {
        "label": "Radeon Cloud verified run",
        "provider_mode": "rocm-local",
        "verified": True,
        "gpu_name": gpu_name,
        "rocm_version": rocm_version(),
        "model_name": args.model_name,
        "rocminfo_excerpt": rocminfo_excerpt,
        "latency_ms": elapsed * 1000,
        "tokens_per_second": completion_tokens / elapsed,
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": completion_tokens,
        "notes": "Measured end-to-end through the loopback OpenAI-compatible endpoint.",
    }
    recorded = post_json(args.app_url.rstrip("/") + "/api/benchmarks", evidence)
    print(json.dumps(recorded, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
