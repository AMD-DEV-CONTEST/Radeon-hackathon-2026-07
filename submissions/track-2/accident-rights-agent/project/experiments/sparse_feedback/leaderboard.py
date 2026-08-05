"""EXP-06: combine measured RAG and Prompt A/B components into a leaderboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


WEIGHTS = {
    "correctness": 0.25,
    "evidence_grounding": 0.20,
    "legal_citation": 0.15,
    "verifier_pass_rate": 0.20,
    "latency": 0.10,
    "token_efficiency": 0.10,
}


def generate_leaderboard(
    output_dir: Path,
    *,
    rag_result: dict[str, Any],
    prompt_result: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rag in rag_result["configurations"]:
        for prompt in prompt_result["prompts"]:
            latency = float(rag["latency_seconds"]) + float(
                prompt["latency_seconds"]
            )
            tokens = float(rag["token_usage"]) + float(prompt["input_tokens"]) + float(
                prompt["output_tokens"]
            )
            rows.append(
                {
                    "configuration": f"{rag['configuration']}-prompt{prompt['prompt_id']}",
                    "retrieval_top_k": rag["retrieval_top_k"],
                    "rerank_keep": rag["rerank_keep"],
                    "prompt_id": prompt["prompt_id"],
                    "correctness": float(prompt["correctness"]),
                    "evidence_grounding": float(prompt["evidence_grounding"]),
                    "legal_citation": (
                        float(prompt["legal_citation"])
                        + float(rag["citation_accuracy"])
                    )
                    / 2,
                    "verifier_pass_rate": (
                        float(prompt["verifier_pass_rate"])
                        + float(rag["final_verifier_score"]) / 100
                    )
                    / 2,
                    "latency_seconds": latency,
                    "token_usage": tokens,
                }
            )
    max_latency = max(row["latency_seconds"] for row in rows)
    min_latency = min(row["latency_seconds"] for row in rows)
    max_tokens = max(row["token_usage"] for row in rows)
    min_tokens = min(row["token_usage"] for row in rows)
    for row in rows:
        row["latency_score"] = _inverse_normalize(
            row["latency_seconds"], min_latency, max_latency
        )
        row["token_efficiency"] = _inverse_normalize(
            row["token_usage"], min_tokens, max_tokens
        )
        row["composite_score"] = round(
            100
            * (
                WEIGHTS["correctness"] * row["correctness"]
                + WEIGHTS["evidence_grounding"] * row["evidence_grounding"]
                + WEIGHTS["legal_citation"] * row["legal_citation"]
                + WEIGHTS["verifier_pass_rate"] * row["verifier_pass_rate"]
                + WEIGHTS["latency"] * row["latency_score"]
                + WEIGHTS["token_efficiency"] * row["token_efficiency"]
            ),
            3,
        )
    ranked = sorted(rows, key=lambda row: row["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        for key in (
            "correctness",
            "evidence_grounding",
            "legal_citation",
            "verifier_pass_rate",
            "latency_seconds",
            "token_usage",
            "latency_score",
            "token_efficiency",
        ):
            row[key] = round(float(row[key]), 6)
    _write_csv(output_dir / "leaderboard.csv", ranked)
    (output_dir / "leaderboard.json").write_text(
        json.dumps(
            {"schema_version": 1, "weights": WEIGHTS, "rows": ranked},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ranked


def _inverse_normalize(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 1.0
    return 1 - (value - minimum) / (maximum - minimum)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rank",
        "configuration",
        "retrieval_top_k",
        "rerank_keep",
        "prompt_id",
        "correctness",
        "evidence_grounding",
        "legal_citation",
        "verifier_pass_rate",
        "latency_seconds",
        "token_usage",
        "latency_score",
        "token_efficiency",
        "composite_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def render_report(
    *,
    memory_result: dict[str, Any],
    rag_result: dict[str, Any],
    prompt_result: dict[str, Any],
    leaderboard: list[dict[str, Any]],
) -> str:
    comparison = memory_result["comparison"]
    baseline = memory_result["baseline"]
    optimized = memory_result["optimized"]
    preferences: dict[str, int] = {}
    for item in prompt_result["feedback"]:
        preferred = str(item["preferred"])
        preferences[preferred] = preferences.get(preferred, 0) + 1
    lines = [
        "# 动态记忆压缩与稀疏反馈实验报告",
        "",
        "所有性能数字均来自本次运行日志；稀疏反馈为明确标记的模拟评审流程，"
        "不是法律或保险专家的真实签署意见，也未用于训练或 LoRA。",
        "",
        "## MEM-03 完整上下文 Baseline",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Input tokens | {baseline['input_tokens']} |",
        f"| Output tokens | {baseline['output_tokens']} |",
        f"| TTFT | {_ms(baseline['ttft_seconds'])} ms |",
        f"| TPOT | {_ms(baseline['tpot_seconds'])} ms/token |",
        f"| Total latency | {baseline['total_latency_seconds']:.3f} s |",
        f"| GPU utilization mean/peak | {_gpu(baseline, 'gpu_utilization_pct')} |",
        f"| VRAM used peak | {_gpu_peak(baseline, 'vram_used_mb')} MB |",
        f"| Quality / verifier | {baseline['quality']['quality_score']} / {baseline['quality']['verifier_pass']} |",
        "",
        (
            "Baseline 被 Verifier 拦截：模型把 Law ID 写入 Evidence ID；"
            "该失败按真实日志保留，没有修饰为通过。"
            if not baseline["quality"]["verifier_pass"]
            else "Baseline 通过结构、引用与风险语言校验。"
        ),
        "",
        "## MEM-04 Case Capsule",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Input tokens | {optimized['input_tokens']} |",
        f"| Token reduction | {100 * comparison['token_reduction_ratio']:.2f}% |",
        f"| TTFT | {_ms(optimized['ttft_seconds'])} ms |",
        f"| TPOT | {_ms(optimized['tpot_seconds'])} ms/token |",
        f"| Total latency | {optimized['total_latency_seconds']:.3f} s |",
        f"| Latency change | {100 * comparison['latency_change_ratio']:.2f}% |",
        f"| VRAM peak change | {comparison['vram_peak_change_mb']:.0f} MB |",
        f"| Conclusion consistency | {100 * comparison['conclusion_consistency']:.2f}% |",
        "",
        "结论一致性采用严格的 Fact/Evidence/Law ID 与审批/不确定性签名比较；"
        "它不等同于宽松的语义相似度。",
        "",
        "## MEM-05 忠实性",
        "",
        f"- Protected fields: {comparison['protected_field_count']} 个；保留率 "
        f"{100 * comparison['protected_field_retention']:.2f}%。",
        f"- 结果：{'通过' if comparison['fidelity_passed'] else '失败'}。",
        "- 检查范围：日期、法定期限、金额、责任比例、Evidence ID、Fact ID、"
        "Law ID、审批状态，以及既有车辆/当事人保护字段。",
        "",
        "## EXP-01/02 案件与评测问题",
        "",
        "- 3 个合成测试案件；12 个问题（车辆、责任、权益、证据各 3 个）。",
        "- Demo B 缺车辆属性鉴定与路口监控；Demo C 包含视频/认定书冲突。",
        "",
        "## EXP-03 RAG 网格",
        "",
        "| 配置 | Recall | Citation accuracy | Latency (s) | Verifier |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rag_result["configurations"]:
        lines.append(
            f"| {row['configuration']} | {row['retrieval_recall']:.3f} | "
            f"{row['citation_accuracy']:.3f} | {row['latency_seconds']:.4f} | "
            f"{row['final_verifier_score']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## EXP-04 Prompt A/B",
            "",
            "| Prompt | Correctness | Evidence | Legal | Verifier pass | Latency (s) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in prompt_result["prompts"]:
        lines.append(
            f"| {row['prompt_id']} | {row['correctness']:.3f} | "
            f"{row['evidence_grounding']:.3f} | {row['legal_citation']:.3f} | "
            f"{row['verifier_pass_rate']:.3f} | {row['latency_seconds']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## EXP-05 稀疏反馈",
            "",
            f"生成 {len(prompt_result['feedback'])} 条 A/B 比较记录；字段符合"
            " `sparse_feedback.schema.json`。这些记录仅演示人工偏好采集，"
            "未触发训练、微调或参数更新。",
            f"- 模拟偏好分布：{json.dumps(preferences, ensure_ascii=False, sort_keys=True)}。",
            "",
            "## EXP-06 Leaderboard",
            "",
            "| Rank | 配置 | 综合分 | Verifier | Latency (s) | Tokens |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in leaderboard[:12]:
        lines.append(
            f"| {row['rank']} | {row['configuration']} | {row['composite_score']:.3f} | "
            f"{row['verifier_pass_rate']:.3f} | {row['latency_seconds']:.3f} | "
            f"{row['token_usage']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## AMD 下一阶段输入",
            "",
            "本次 JSON/CSV 已保存 full vs capsule 的 input/output tokens、TTFT、"
            "TPOT、总延迟、GPU 利用率、VRAM peak 和 concurrency=1。后续 AMD"
            " 优化应在相同模型、温度、请求与硬件下扩展 concurrency 2/4。",
        ]
    )
    return "\n".join(lines)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{1000 * value:.2f}"


def _gpu(result: dict[str, Any], metric: str) -> str:
    values = result["gpu"]["metrics"][metric]
    if values["mean"] is None:
        return "n/a"
    return f"{values['mean']:.1f}% / {values['peak']}%"


def _gpu_peak(result: dict[str, Any], metric: str) -> str:
    value = result["gpu"]["metrics"][metric]["peak"]
    return "n/a" if value is None else str(value)
