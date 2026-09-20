"""Run three auditable domestic-market cases against vLLM and the CN report API."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from src.cn_pipeline import CN_MARKET_DSL_PROMPT, process_cn_model_output


CASES = [
    ("ema_trend", "请为沪深300ETF（510300.SH）设计日线EMA20/EMA50趋势策略，最大仓位30%，止损5%"),
    ("rsi_reversion", "请为中证500ETF（510500.SH）设计30分钟RSI超卖均值回归策略，止损4%，禁止做空"),
    ("breakout_risk", "请为创业板ETF（159915.SZ）设计日线布林带突破策略，必须遵守T+1、100股整手和禁止做空"),
]


def main() -> None:
    base = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    model = os.environ.get("MODEL_NAME", "models/qwen-trader-merged")
    api = os.environ.get("BACKTEST_API_URL", "http://127.0.0.1:8080")
    output = Path(os.environ.get("CN_CASE_OUTPUT", "/persistent/track2/eval/cn_dify_cases.json"))
    records = []
    with httpx.Client(timeout=120) as client:
        for case_id, user_prompt in CASES:
            response = client.post(
                f"{base}/chat/completions",
                json={"model": model, "messages": [
                    {"role": "system", "content": CN_MARKET_DSL_PROMPT},
                    {"role": "user", "content": user_prompt},
                ], "temperature": 0.2, "max_tokens": 2048},
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            normalized = process_cn_model_output(raw)
            dsl = normalized["canonicalized"]
            report = None
            if dsl:
                # The CN report endpoint expects the DSL root directly.
                # Wrapping it again as {"strategy": dsl} creates strategy.strategy
                # and causes a false validation rejection.
                report_resp = client.post(f"{api}/api/cn/backtest/report", json=dsl)
                report_resp.raise_for_status()
                report = report_resp.text
            records.append({
                "case_id": case_id,
                "user_prompt": user_prompt,
                "raw_output": raw,
                "parsed": normalized["parsed"],
                "canonicalized": dsl,
                "repairs": normalized["extract_repairs"] + normalized["canon_repairs"],
                "errors": normalized["errors"],
                "canonicalization_pass": normalized["canon_success"],
                "report": report,
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"model": model, "cases": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(records), "passed": sum(r["canonicalization_pass"] for r in records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
