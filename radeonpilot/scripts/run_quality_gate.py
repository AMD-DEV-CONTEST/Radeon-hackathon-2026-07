#!/usr/bin/env python3
"""Frozen quality gate for the optional quantized profile.

Runs a fixed evaluation prompt set against the configured endpoint and requires
every answer to meet minimal factual/completeness checks. Writes
runtime/quality_gate.json with passed=true only when all checks succeed.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EVALUATIONS = [
    {
        "prompt": "In one sentence, what does prefix caching reuse in an LLM serving engine?",
        "must_contain": ["prefix", "cache"],
        "min_chars": 20,
    },
    {
        "prompt": "Name one AMD tool that can list GPU processes by PID.",
        "must_contain": ["amd-smi", "rocm-smi"],
        "min_chars": 5,
    },
    {
        "prompt": "What architecture family does a Radeon RX 7900 series GPU belong to, and what gfx target does it report to ROCm?",
        "must_contain": ["rdna", "gfx"],
        "min_chars": 10,
    },
]


def ask(base_url: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 96,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120.0) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def main() -> int:
    base_url = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    model = os.environ.get("RADEONPILOT_MODEL", "qwen3-8b")
    results = []
    all_ok = True
    for item in EVALUATIONS:
        try:
            answer = ask(base_url, model, item["prompt"])
            lowered = answer.lower()
            hit_terms = [term for term in item["must_contain"] if term.lower() in lowered]
            ok = len(hit_terms) >= 1 and len(answer) >= item["min_chars"]
        except Exception as exc:  # noqa: BLE001
            answer = ""
            hit_terms = []
            ok = False
            results.append({"prompt": item["prompt"], "ok": False, "error": str(exc)})
            all_ok = False
            continue
        results.append({"prompt": item["prompt"], "ok": ok, "answer": answer[:300], "matched": hit_terms})
        all_ok = all_ok and ok

    out_path = Path("runtime/quality_gate.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "passed": all_ok,
                "endpoint": base_url,
                "model": model,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"quality gate passed={all_ok} -> {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
