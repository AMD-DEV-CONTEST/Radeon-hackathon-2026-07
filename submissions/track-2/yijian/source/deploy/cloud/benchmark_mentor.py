#!/usr/bin/env python3
"""固定围棋导师提示的首字/总耗时基准；结果写入持久盘 JSON。"""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


URL = os.getenv("YIJIAN_CLOUD_LLM_URL", "http://127.0.0.1:8082/v1").rstrip("/")
MODEL = os.getenv("YIJIAN_CLOUD_LLM_MODEL", "Yijian-Qwen3.6-27B-GoCoach")
OUT = Path(os.getenv("YIJIAN_BENCH_DIR", "/persistent/yijian/benchmarks"))
CASES = [
    "依据证据解释：第28手白D10，黑胜率52.9%，目差+0.6；不要改写数字。",
    "依据证据解释：实战手导致胜率损失3.2个百分点，首选Q10；说明复盘动作。",
    "依据证据解释：布局阶段己方两块弱棋，对方外势较厚；给出下一步观察顺序。",
    "依据证据解释：官子阶段目差接近，候选点价值相近；说明如何比较先后手。",
    "依据证据解释：推荐变化只有六手，不得把它描述成强制变化。",
]


def call(prompt: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": .2,
        "max_tokens": 160,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    request = Request(
        f"{URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    chunks: list[str] = []
    usage: dict = {}
    first_token = None
    with urlopen(request, timeout=120) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            data = json.loads(line[6:])
            usage = data.get("usage") or usage
            choices = data.get("choices") or []
            content = ((choices[0].get("delta") or {}).get("content") if choices else None)
            if content:
                if first_token is None:
                    first_token = time.perf_counter() - started
                chunks.append(content)
    elapsed = time.perf_counter() - started
    text = "".join(chunks)
    if first_token is None or not text:
        raise RuntimeError("The model stream returned no text.")
    return {
        "firstTokenSeconds": first_token,
        "totalSeconds": elapsed,
        "chars": len(text),
        "usage": usage,
        "text": text,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    call("只回答：预热完成。")
    for index, prompt in enumerate(CASES, 1):
        result = call(prompt)
        result.update({"case": index, "prompt": prompt})
        results.append(result)
        print(
            f"case {index}: first={result['firstTokenSeconds']:.2f}s "
            f"total={result['totalSeconds']:.2f}s"
        )
    report = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "endpoint": URL,
        "meanFirstTokenSeconds": statistics.mean(item["firstTokenSeconds"] for item in results),
        "meanTotalSeconds": statistics.mean(item["totalSeconds"] for item in results),
        "p95TotalSeconds": sorted(item["totalSeconds"] for item in results)[-1],
        "results": results,
    }
    model_slug = "".join(char if char.isalnum() else "-" for char in MODEL).strip("-")
    target = OUT / f"mentor-{model_slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
