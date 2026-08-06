#!/usr/bin/env python3
"""W7900 上交替压测 Qwen3-14B vLLM 与 KataGo 128 visits 共存。

脚本只使用仓库内固定合成局面，不读取用户棋谱。每轮先请求 KataGo，再请求
vLLM，记录首 token、完整回答、KataGo 与合并耗时；任一进程失败即不通过。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import threading
import time
from urllib.request import Request, urlopen

from benchmark_katago_analysis import (
    AnalysisProcess,
    FIXED_MOVES,
    MODEL_SHA256,
    configured,
    file_sha256,
    runtime_evidence,
)


PROMPTS = (
    "依据工具证据解释实战与首选的差异；不得改写坐标、胜率、目差或访问次数。",
    "证据不足以证明强制应手时，请主动收窄结论，并给出下一次检查重点。",
    "把局面事实、KataGo 分析和棋理启发分开说明，不要把古训当成当前棋盘事实。",
    "用户追问为什么时，先回答问题对象，再说明所得、代价和可执行复盘动作。",
    "记忆默认关闭；没有用户明确授权时，不得声称已经保存学习记录。",
)


class GpuSampler:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                raw = subprocess.check_output(
                    ["rocm-smi", "--showmeminfo", "vram", "--showuse", "--json"],
                    text=True, stderr=subprocess.DEVNULL, timeout=3,
                )
                card = next(iter(json.loads(raw).values()))
                self.rows.append({
                    "at": time.time(),
                    "gpuUsePercent": float(card.get("GPU use (%)") or 0),
                    "vramUsedBytes": int(card.get("VRAM Total Used Memory (B)") or 0),
                })
            except Exception:
                pass
            self.stop_event.wait(.5)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join(timeout=3)


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * ratio + .999999) - 1))
    return ordered[index]


def call_llm(url: str, model: str, prompt: str, timeout: float) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": .2,
        "max_tokens": 220,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    request = Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    chunks = []
    usage = {}
    first_token = None
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            value = json.loads(line[6:])
            usage = value.get("usage") or usage
            choices = value.get("choices") or []
            content = ((choices[0].get("delta") or {}).get("content") if choices else None)
            if content:
                if first_token is None:
                    first_token = time.perf_counter() - started
                chunks.append(content)
    elapsed = time.perf_counter() - started
    text = "".join(chunks).strip()
    if first_token is None or not text:
        raise RuntimeError("vLLM流式响应没有返回正文")
    return {
        "firstTokenSeconds": round(first_token, 4),
        "totalSeconds": round(elapsed, 4),
        "chars": len(text),
        "usage": usage,
        "textHash": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--katago", type=Path, required=True)
    parser.add_argument("--katago-model", type=Path, required=True)
    parser.add_argument("--katago-config", type=Path, required=True)
    parser.add_argument("--llm-url", default="http://127.0.0.1:8083/v1")
    parser.add_argument("--llm-model", default="yijian-lora")
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--p95-limit", type=float, default=12.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vllm-log", type=Path)
    parser.add_argument("--skip-model-hash", action="store_true")
    args = parser.parse_args()
    if args.cycles < 30:
        parser.error("正式共存门槛至少需要30轮")
    for path in (args.katago, args.katago_model, args.katago_config):
        if not path.is_file():
            parser.error(f"missing file: {path}")
    model_hash = file_sha256(args.katago_model)
    if not args.skip_model_hash and model_hash != MODEL_SHA256:
        parser.error(f"KataGo model SHA-256 mismatch: {model_hash}")

    with tempfile.TemporaryDirectory(prefix="yijian-coexist-") as temp_dir:
        config = Path(temp_dir) / "analysis.cfg"
        config.write_text(
            configured(
                args.katago_config.read_text(encoding="utf-8"), 64, 1, 64
            ),
            encoding="utf-8",
        )
        engine = AnalysisProcess(args.katago, args.katago_model, config)
        rows = []
        try:
            engine.query("warmup", [], [0], 1, timeout=args.timeout)
            call_llm(args.llm_url, args.llm_model, "只回答：预热完成。", args.timeout)
            with GpuSampler() as sampler, ThreadPoolExecutor(max_workers=2) as pool:
                for index in range(args.cycles):
                    cycle_started = time.perf_counter()
                    katago_future = pool.submit(
                        engine.query, f"coexist-{index + 1}", FIXED_MOVES,
                        [len(FIXED_MOVES)], 128, timeout=args.timeout,
                    )
                    llm_future = pool.submit(
                        call_llm, args.llm_url, args.llm_model,
                        PROMPTS[index % len(PROMPTS)], args.timeout,
                    )
                    _, katago_seconds = katago_future.result()
                    llm = llm_future.result()
                    rows.append({
                        "cycle": index + 1,
                        "katagoSeconds": round(katago_seconds, 4),
                        "llm": llm,
                        "combinedSeconds": round(time.perf_counter() - cycle_started, 4),
                        "workloadsOverlapped": True,
                    })
                    print(
                        f"cycle {index + 1:02d}: katago={katago_seconds:.2f}s "
                        f"first={llm['firstTokenSeconds']:.2f}s total={llm['totalSeconds']:.2f}s"
                    )
        finally:
            engine.close()

    combined = [row["combinedSeconds"] for row in rows]
    llm_total = [row["llm"]["totalSeconds"] for row in rows]
    first_tokens = [row["llm"]["firstTokenSeconds"] for row in rows]
    katago_total = [row["katagoSeconds"] for row in rows]
    p95 = percentile(combined, .95)
    log_text = (
        args.vllm_log.read_text(encoding="utf-8", errors="replace")
        if args.vllm_log and args.vllm_log.is_file() else ""
    )
    oom_count = sum(log_text.lower().count(marker) for marker in ("out of memory", "hip out of memory"))
    peak_vram = max((row["vramUsedBytes"] for row in sampler.rows), default=0)
    report = {
        "schemaVersion": "yijian-w7900-qwen3-katago-coexist-v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "passed": len(rows) == args.cycles and p95 <= args.p95_limit and oom_count == 0,
        "cycles": len(rows),
        "requiredCycles": args.cycles,
        "p95LimitSeconds": args.p95_limit,
        "gpuMemoryUtilization": os.getenv("YIJIAN_VLLM_GPU_MEMORY_UTILIZATION", "unknown"),
        "overlapMode": "KataGo next-position analysis overlaps vLLM previous-evidence generation",
        "oomCount": oom_count,
        "telemetry": {
            "samples": len(sampler.rows),
            "peakVramUsedGiB": round(peak_vram / 1024**3, 3),
            "meanGpuUsePercent": round(statistics.mean([row["gpuUsePercent"] for row in sampler.rows]), 3) if sampler.rows else None,
        },
        "llm": {
            "model": args.llm_model,
            "url": args.llm_url,
            "meanFirstTokenSeconds": round(statistics.mean(first_tokens), 4),
            "p95FirstTokenSeconds": percentile(first_tokens, .95),
            "meanTotalSeconds": round(statistics.mean(llm_total), 4),
            "p95TotalSeconds": percentile(llm_total, .95),
        },
        "katago": {
            "visits": 128,
            "modelSha256": model_hash,
            "meanSeconds": round(statistics.mean(katago_total), 4),
            "p95Seconds": percentile(katago_total, .95),
        },
        "combined": {
            "meanSeconds": round(statistics.mean(combined), 4),
            "p95Seconds": p95,
        },
        "runtimeEvidence": runtime_evidence(args.katago),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in ("passed", "cycles", "combined")}, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
