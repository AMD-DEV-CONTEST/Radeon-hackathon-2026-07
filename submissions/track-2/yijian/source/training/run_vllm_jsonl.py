# -*- coding: utf-8 -*-
"""Run a deterministic JSONL evaluation through an OpenAI-compatible vLLM API."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA = "yijian-vllm-evaluation-output-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} must be an object")
        rows.append(value)
    return rows


def case_id(row: dict[str, Any], index: int) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return str(row.get("caseId") or row.get("id") or metadata.get("id") or metadata.get("sourceCaseId") or f"case-{index:04d}")


def messages_for(row: dict[str, Any]) -> list[dict[str, str]]:
    messages = row.get("messages")
    if not isinstance(messages, list):
        payload = row.get("input") if isinstance(row.get("input"), dict) else {}
        messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        normalized = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in messages
            if isinstance(item, dict) and item.get("role") in {"system", "user", "assistant"} and item.get("content") is not None
        ]
        if normalized and normalized[-1]["role"] == "assistant":
            normalized.pop()
        if normalized:
            return normalized
    payload = row.get("input") if isinstance(row.get("input"), dict) else {}
    target = str(row.get("target") or payload.get("target") or "position")
    question = str(row.get("question") or payload.get("question") or "Explain the position using only supplied evidence.")
    if row.get("suite") == "structure_safety":
        example_tool = "compare_moves" if target == "comparison" else "inspect_position"
        example_focus = (
            ["move_order", "evidence_boundary"]
            if target == "comparison"
            else ["group_safety", "evidence_boundary"]
        )
        example = canonical({
            "schemaVersion": "agent-plan-v1",
            "questionTarget": target,
            "steps": [{"tool": example_tool, "target": target}],
            "focus": example_focus,
            "confidence": "medium",
        })
        prompt = (
            "/no_think\n你只负责规划围棋教学工具，不负责回答问题。"
            "不得输出棋盘坐标、胜率、目差、访问次数或任何数字。"
            "只能选择inspect_position、compare_moves、analyze_variations、"
            "retrieve_principles、recall_lessons、remember_lesson。"
            "target只能是actual、best、comparison、position；最多三个步骤。"
            f"本题所有steps的target都必须与questionTarget相同，即只能写{target}。"
            "focus只能从move_order、group_safety、liberties、connection、cutting、"
            "sente、territory_influence、thickness、ko_resources、joseki_direction、"
            "opening_priority、endgame_value、evidence_boundary中选择。"
            "只返回JSON对象，字段必须恰好是schemaVersion、questionTarget、steps、"
            "focus、confidence；schemaVersion固定agent-plan-v1。"
            "steps中的每一项只能有tool和target两个字段；focus必须是枚举字符串数组，"
            "只能选一至四项，绝不能照抄全部focus枚举；"
            "confidence只能是low、medium或high，不得使用数字。"
            f"本题格式示例：{example}。"
            f"\n服务端已确定问题目标：{target}"
            f"\n用户问题：{question}"
        )
        return [
            {
                "role": "system",
                "content": "你是弈鉴工具规划器，只输出严格JSON。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
    evidence = payload.get("evidence") or row.get("evidence") or {}
    return [
        {"role": "system", "content": "You are YIJIAN's bounded Go teaching agent. Use only supplied evidence. Return concise JSON with answer and followUps. Do not invent coordinates, numeric values, life-and-death status, or sources."},
        {"role": "user", "content": f"Target: {target}\nEvidence: {canonical(evidence)}\nQuestion: {question}"},
    ]


def request_one(*, endpoint: str, model: str, row: dict[str, Any], index: int,
                timeout: float, max_tokens: int) -> dict[str, Any]:
    cid = case_id(row, index)
    payload = {
        "model": model,
        "messages": messages_for(row),
        "temperature": 0,
        "max_tokens": max_tokens,
        # The response contract is exactly one JSON object.  Both llama.cpp
        # and vLLM honour this stop sequence, which prevents a correct object
        # from being repeated until the token limit and then becoming invalid.
        "stop": ["\n{"],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=canonical(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = str(body["choices"][0]["message"]["content"]).strip()
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return {
            "caseId": cid,
            "answer": text,
            "succeeded": True,
            "seconds": round(time.perf_counter() - started, 6),
            "usage": usage,
        }
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
        return {
            "caseId": cid,
            "answer": "",
            "succeeded": False,
            "seconds": round(time.perf_counter() - started, 6),
            "error": f"{type(exc).__name__}: {exc}",
        }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8083")
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        parser.error("input has no cases")
    if args.concurrency < 1 or args.concurrency > 8:
        parser.error("concurrency must be between 1 and 8")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                request_one, endpoint=args.endpoint, model=args.model, row=row,
                index=index, timeout=args.timeout, max_tokens=args.max_tokens,
            )
            for index, row in enumerate(rows, 1)
        ]
        results = [future.result() for future in futures]
    succeeded = sum(bool(row["succeeded"]) for row in results)
    report = {
        "schemaVersion": SCHEMA,
        "model": args.model,
        "endpoint": args.endpoint,
        "inputSha256": sha256_file(args.input),
        "cases": len(results),
        "succeeded": succeeded,
        "successRate": succeeded / len(results),
        "latencyP50Seconds": percentile([float(row["seconds"]) for row in results if row["succeeded"]], .50),
        "latencyP95Seconds": percentile([float(row["seconds"]) for row in results if row["succeeded"]], .95),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({key: report[key] for key in ("model", "cases", "succeeded", "successRate", "latencyP95Seconds")}, ensure_ascii=False))
    return 0 if succeeded == len(results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
