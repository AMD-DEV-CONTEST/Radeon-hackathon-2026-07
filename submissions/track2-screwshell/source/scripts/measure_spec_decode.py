#!/usr/bin/env python3
"""Measure decode throughput with/without speculative decoding (T-spec).

Usage (on the W7900 box, against the relay):

    python3 scripts/measure_spec_decode.py --reps 5 --tokens 200

Prints the median decode tok/s for the CURRENT server configuration. Run it
once BEFORE enabling `--spec-type ngram-*` on llama-server and once AFTER;
the two medians are the A/B that proves (or disproves) the speedup on
structured agentic payloads (JSON tool-call style prompts).

Pure stdlib. Sends realistic agent-shaped prompts (tool-call JSON) because
ngram speculation wins exactly on repetitive structured text.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request

RELAY = "http://127.0.0.1:18090/v1/chat/completions"
TOKEN = "screwshell-relay-devtoken"

# Structured-JSON prompts: ngram speculation wins on repetitive output
# (JSON tool-call blocks, repeated keys), NOT on free text. These force the
# model to emit long, structurally repetitive JSON so the A/B is meaningful.
PROMPTS = [
    '输出一个 JSON 数组，包含 25 个工具调用记录，每个含 action/tool/args 字段，args 里要有 path 和 pattern。',
    '生成一个 JSON 对象，列出 20 个文件调查步骤，每步含 step/action/tool/args/expect 字段。',
    'Output a JSON array of 25 tool-call records, each with action/tool/args where args has path and pattern.',
]


def one_call(prompt: str, max_tokens: int) -> tuple[float, int]:
    body = json.dumps({
        "model": "m",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(RELAY, data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Relay-Token": TOKEN},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    t = (d.get("timings") or {})
    tps = t.get("predicted_per_second")
    return float(tps) if tps else 0.0, int((d.get("usage") or {}).get("completion_tokens", 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--tokens", type=int, default=200)
    args = ap.parse_args()

    tps_all: list[float] = []
    for i in range(args.reps):
        for p in PROMPTS:
            tps, comp = one_call(p, args.tokens)
            if tps:
                tps_all.append(tps)
            print(f"  rep {i + 1}: {tps:.1f} tok/s ({comp} tokens)")
            time.sleep(0.2)
    if not tps_all:
        print("no measurements (server unreachable?)")
        return 1
    med = statistics.median(tps_all)
    print(f"=== median decode: {med:.1f} tok/s over {len(tps_all)} calls ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
