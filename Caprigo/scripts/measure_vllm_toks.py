#!/usr/bin/env python3
"""Time vLLM /v1/chat/completions decode tok/s (DevMaster Track 2 harness)."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--model", required=True)
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--out", default="")
    args = p.parse_args()

    url = args.base.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": args.model,
        "messages": [
            {"role": "user", "content": "Write a short paragraph about AMD ROCm GPUs."}
        ],
        "max_tokens": args.max_tokens,
        "temperature": 0,
    }
    t0 = time.time()
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.load(r)
    dt = time.time() - t0
    out_tok = (data.get("usage") or {}).get("completion_tokens") or 0
    tps = (out_tok / dt) if dt > 0 else 0.0
    text = (
        f"model={args.model}\n"
        f"completion_tokens={out_tok}\n"
        f"wall_s={dt:.3f}\n"
        f"tok_per_s={tps:.2f}\n"
    )
    print(text, end="")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
