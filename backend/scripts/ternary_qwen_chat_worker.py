#!/usr/bin/env python3
"""Subprocess worker for ternary Qwen chat inference.

This worker is meant to be launched from the main backend in the `e2e` conda
environment, but it actually runs inside an environment that has a compatible
`transformers` version (e.g. `radialog-qwen35`). It communicates via JSON lines
on stdin/stdout so the main process does not need the heavy ternary Qwen
dependencies.

Protocol:
- Each line on stdin is a JSON request:
    {"report": "...", "findings": [{"label": "...", "confidence": 0.9}], "question": "...", "max_new_tokens": 128}
- Each line on stdout is a JSON response:
    {"text": "...", "tokens_generated": 42, "latency_seconds": 1.2, "model_name": "..."}
- The worker loads the model once and keeps it in memory.
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure end2end_xray backend and RaDialog_LLaVA are importable.
end2end_backend = Path(__file__).resolve().parent.parent
radialog_llava = end2end_backend.parent.parent / "RaDialog_LLaVA"
for p in (str(end2end_backend), str(radialog_llava)):
    if p not in sys.path:
        sys.path.insert(0, p)

from models.ternary_qwen_loader import generate_text, load_ternary_qwen


def _build_prompt(report: str, findings: list, question: str, system_prompt: Optional[str] = None) -> str:
    finding_lines = "\n".join(
        f"- {f['label']}: {f['confidence']:.0%}" for f in findings if f.get("confidence", 0) > 0.05
    )
    system = system_prompt or (
        "You are a helpful radiology assistant. Use the following chest X-ray report and findings to answer the user."
    )
    return (
        f"{system}\n\n"
        f"Report:\n{report}\n\n"
        f"Findings:\n{finding_lines}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def main():
    model_dir = os.environ.get("CHAT_MODEL")
    if not model_dir:
        print(json.dumps({"error": "CHAT_MODEL environment variable is not set."}), flush=True)
        return 1

    sys.stderr.write(f"[worker] Loading ternary Qwen chat model from {model_dir}\n")
    sys.stderr.flush()
    try:
        model, processor = load_ternary_qwen(model_dir)
    except Exception as exc:
        sys.stderr.write(f"[worker] FAILED to load model: {exc}\n")
        sys.stderr.flush()
        print(json.dumps({"error": f"Failed to load ternary Qwen model: {exc}"}), flush=True)
        return 1

    sys.stderr.write("[worker] Model loaded. Waiting for requests.\n")
    sys.stderr.flush()
    # Signal readiness to the parent process via stdout.
    print(json.dumps({"status": "ready"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"Invalid JSON: {exc}"}), flush=True)
            continue

        report = req.get("report", "")
        findings = req.get("findings", [])
        question = req.get("question", "")
        max_new_tokens = req.get("max_new_tokens", 128)
        do_sample = req.get("do_sample", False)
        temperature = req.get("temperature", 0.7)
        image_b64 = req.get("image_b64")
        system_prompt = req.get("system_prompt")

        images = []
        if image_b64:
            try:
                import base64
                from io import BytesIO
                from PIL import Image

                image_bytes = base64.b64decode(image_b64)
                images = [Image.open(BytesIO(image_bytes)).convert("RGB")]
            except Exception as exc:
                sys.stderr.write(f"[worker] Failed to decode image: {exc}\n")
                sys.stderr.flush()

        prompt = _build_prompt(report, findings, question, system_prompt=system_prompt)
        start = time.time()
        try:
            text = generate_text(
                model,
                processor,
                prompt,
                images=images,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=temperature,
            )
            latency = time.time() - start
            # Rough token count: words if we don't have exact tokenizer count.
            tokens_generated = len(text.split()) if text else 0
            print(
                json.dumps(
                    {
                        "text": text,
                        "tokens_generated": tokens_generated,
                        "latency_seconds": latency,
                        "model_name": str(model_dir),
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            print(json.dumps({"error": f"Generation failed: {exc}"}), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
