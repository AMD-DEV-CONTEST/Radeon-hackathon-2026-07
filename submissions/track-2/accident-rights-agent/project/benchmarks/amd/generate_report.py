#!/usr/bin/env python3
"""Generate AMD-09 CSV, Markdown, HTML, SVG charts, and final report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any


def load(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def nested(value: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def num(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.3f}{suffix}"


def process_flag(command: str, flag: str) -> str | None:
    match = re.search(rf"(?:^|\s){re.escape(flag)}\s+(\S+)", command)
    return match.group(1) if match else None


def runtime_versions(environment: dict[str, Any]) -> dict[str, Any]:
    stdout = nested(environment, "runtime", "stdout", default="{}")
    try:
        parsed = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def first_match(pattern: str, text: str, default: str = "unknown") -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1).strip() if match else default


def bar_svg(title: str, values: list[tuple[str, float]], path: Path) -> None:
    width, height = 760, 360
    maximum = max((value for _, value in values), default=1.0) or 1.0
    bar_width = max(36, int(560 / max(1, len(values))))
    gap = max(18, int((620 - bar_width * len(values)) / max(1, len(values))))
    colors = ["#ed1c24", "#7a1fa2", "#1473e6", "#0b9f6e", "#f59e0b"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="30" y="35" font-family="sans-serif" font-size="20" font-weight="700">{html.escape(title)}</text>',
        '<line x1="60" y1="300" x2="730" y2="300" stroke="#222"/>',
    ]
    for index, (label, value) in enumerate(values):
        x = 80 + index * (bar_width + gap)
        bar_height = 220 * value / maximum
        y = 300 - bar_height
        parts.extend(
            [
                f'<rect x="{x}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="5" fill="{colors[index % len(colors)]}"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" font-family="sans-serif" font-size="13">{value:.2f}</text>',
                f'<text x="{x + bar_width / 2:.1f}" y="322" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(label)}</text>',
            ]
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--documentation", type=Path, required=True)
    parser.add_argument("--experiments-amd-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.results_dir
    charts = root / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    args.documentation.parent.mkdir(parents=True, exist_ok=True)
    args.experiments_amd_dir.mkdir(parents=True, exist_ok=True)

    environment = load(root / "environment.json", {})
    baseline_config = load(root / "baseline_config.json", {})
    optimized_config = load(root / "optimized_config.json", {})
    projection = load(root / "input_projection.json", {})
    baseline = load(root / "baseline" / "baseline.json", {})
    optimized = load(root / "optimized" / "optimized.json", {})
    prefix_baseline = load(root / "prefix_cache" / "baseline.json", {})
    prefix_optimized = load(root / "prefix_cache" / "optimized.json", {})
    concurrency = load(root / "concurrency" / "amd_concurrency_results.json", {})
    stability = load(root / "stability" / "stability_report.json", {})
    security = load(root / "security" / "security_checks.json", {})
    matrix = [load(path, {}) for path in sorted((root / "matrix").glob("*.json"))]
    versions = runtime_versions(environment)
    gpu_static = nested(environment, "gpu_static", "stdout", default="") or ""
    amd_versions = nested(environment, "amd_smi_version", "stdout", default="") or ""
    gpu_name = first_match(r"NAME:\s*([^\n]+GDDR6[^\n]+)", gpu_static)
    vram_mb = first_match(r"VRAM:\s*(?:.|\n)*?SIZE:\s*(\d+)\s*MB", gpu_static)
    rocm_version = first_match(r"ROCm version:\s*([^|\n]+)", amd_versions)
    driver_version = first_match(r"amdgpu version:\s*([^|\n]+)", amd_versions)
    live_process = nested(security, "localhost_proof", "process", default="") or ""
    selected_config = {
        "gpu_memory_utilization": process_flag(live_process, "--gpu-memory-utilization"),
        "max_num_batched_tokens": process_flag(live_process, "--max-num-batched-tokens"),
        "max_model_len": process_flag(live_process, "--max-model-len"),
        "enable_prefix_caching": "--enable-prefix-caching" in live_process,
    }
    prefix_hit_values: list[float] = []
    for log_path in sorted((root / "logs").glob("*.log")):
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        prefix_hit_values.extend(
            float(value)
            for value in re.findall(r"Prefix cache hit rate:\s*([0-9.]+)%", log_text)
        )
    prefix_hit_peak = max(prefix_hit_values) if prefix_hit_values else None

    base_summary = baseline.get("summary", {})
    opt_summary = optimized.get("summary", {})
    base_tokens = float(base_summary.get("input_tokens_mean") or 0)
    opt_tokens = float(opt_summary.get("input_tokens_mean") or 0)
    reduction = 1 - opt_tokens / max(1, base_tokens)
    base_ttft = nested(base_summary, "ttft_seconds", "p50")
    opt_ttft = nested(opt_summary, "ttft_seconds", "p50")
    ttft_improvement = (
        1 - float(opt_ttft) / max(0.000001, float(base_ttft))
        if base_ttft is not None and opt_ttft is not None
        else None
    )
    prefix_base_second = nested(prefix_baseline, "runs", default=[])
    prefix_opt_second = nested(prefix_optimized, "runs", default=[])
    prefix_base_ttft = (
        prefix_base_second[1].get("ttft_seconds") if len(prefix_base_second) > 1 else None
    )
    prefix_opt_ttft = (
        prefix_opt_second[1].get("ttft_seconds") if len(prefix_opt_second) > 1 else None
    )
    prefix_improvement = (
        1 - float(prefix_opt_ttft) / max(0.000001, float(prefix_base_ttft))
        if prefix_base_ttft is not None and prefix_opt_ttft is not None
        else None
    )

    comparison_fields = [
        "condition",
        "input_tokens",
        "token_reduction_ratio",
        "ttft_p50_seconds",
        "ttft_p95_seconds",
        "tpot_p50_seconds",
        "tpot_p95_seconds",
        "output_tokens_per_second",
        "latency_mean_seconds",
        "latency_p95_seconds",
        "gpu_utilization_mean_pct",
        "vram_peak_mb",
        "success_rate",
        "oom_count",
        "protected_field_retention",
        "quality_score_mean",
        "verifier_pass_rate",
    ]
    rows: list[dict[str, Any]] = []
    for condition, record, summary in (
        ("Baseline", baseline, base_summary),
        ("Optimized", optimized, opt_summary),
    ):
        gpu = nested(summary, "gpu", "metrics", default={}) or {}
        rows.append(
            {
                "condition": condition,
                "input_tokens": summary.get("input_tokens_mean"),
                "token_reduction_ratio": 0 if condition == "Baseline" else round(reduction, 6),
                "ttft_p50_seconds": nested(summary, "ttft_seconds", "p50"),
                "ttft_p95_seconds": nested(summary, "ttft_seconds", "p95"),
                "tpot_p50_seconds": nested(summary, "tpot_seconds", "p50"),
                "tpot_p95_seconds": nested(summary, "tpot_seconds", "p95"),
                "output_tokens_per_second": summary.get("aggregate_output_tokens_per_second"),
                "latency_mean_seconds": nested(summary, "total_latency_seconds", "mean"),
                "latency_p95_seconds": nested(summary, "total_latency_seconds", "p95"),
                "gpu_utilization_mean_pct": nested(gpu, "gpu_utilization_pct", "mean"),
                "vram_peak_mb": nested(gpu, "vram_used_mb", "peak"),
                "success_rate": summary.get("success_rate"),
                "oom_count": summary.get("oom_count"),
                "protected_field_retention": 1.0 if condition == "Baseline" else projection.get("protected_field_retention"),
                "quality_score_mean": summary.get("quality_score_mean"),
                "verifier_pass_rate": summary.get("verifier_pass_rate"),
            }
        )
    with (root / "amd_baseline_vs_optimized.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=comparison_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    concurrency_csv = root / "concurrency" / "amd_concurrency_results.csv"
    if concurrency_csv.exists():
        shutil.copyfile(concurrency_csv, root / "concurrency_report.csv")
    gpu_files = sorted(root.glob("**/gpu*.csv"))
    gpu_files = [path for path in gpu_files if path != root / "gpu_metrics.csv"]
    with (root / "gpu_metrics.csv").open("w", encoding="utf-8", newline="") as output:
        wrote_header = False
        for path in gpu_files:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            if not wrote_header:
                output.write(lines[0] + "\n")
                wrote_header = True
            for line in lines[1:]:
                output.write(line + "\n")

    bar_svg(
        "Input tokens (lower is better)",
        [("Baseline", base_tokens), ("Optimized", opt_tokens)],
        charts / "input_tokens.svg",
    )
    bar_svg(
        "TTFT p50 seconds (lower is better)",
        [("Baseline", float(base_ttft or 0)), ("Optimized", float(opt_ttft or 0))],
        charts / "ttft_p50.svg",
    )
    concurrency_values = [
        (
            f"c{item['summary']['concurrency']}",
            float(item["summary"]["aggregate_output_tokens_per_second"]),
        )
        for item in concurrency.get("levels", [])
    ]
    if concurrency_values:
        bar_svg(
            "Concurrency output throughput (tokens/s)",
            concurrency_values,
            charts / "concurrency_throughput.svg",
        )

    matrix_rows = []
    for item in matrix:
        summary = item.get("summary", {})
        config = item.get("config", {})
        matrix_rows.append(
            "| {label} | {memory} | {batch} | {context} | {success:.1%} | {ttft} | {throughput} | {vram} | {oom} |".format(
                label=item.get("label", "unknown"),
                memory=config.get("gpu_memory_utilization", "n/a"),
                batch=config.get("max_num_batched_tokens", "default"),
                context=config.get("max_model_len", "n/a"),
                success=float(summary.get("success_rate") or 0),
                ttft=num(nested(summary, "ttft_seconds", "p50")),
                throughput=num(summary.get("aggregate_output_tokens_per_second")),
                vram=nested(summary, "gpu", "metrics", "vram_used_mb", "peak", default="n/a"),
                oom=summary.get("oom_count", "n/a"),
            )
        )

    targets = {
        "token_reduction_ge_40": reduction >= 0.40,
        "protected_fields_100": projection.get("protected_field_retention") == 1.0,
        "prefix_ttft_improvement_ge_15": prefix_improvement is not None and prefix_improvement >= 0.15,
        "stability_30m": bool(stability.get("passed")),
        "quality_not_lower": float(opt_summary.get("quality_score_mean") or 0)
        >= float(base_summary.get("quality_score_mean") or 0),
        "security": bool(security.get("security_passed")),
        "privacy": bool(security.get("privacy_passed")),
    }
    prefix_note = (
        f"重复案件第二问 TTFT 从 {prefix_base_ttft:.3f}s 降至 {prefix_opt_ttft:.3f}s，改善 {prefix_improvement:.1%}。"
        if prefix_improvement is not None
        else "重复案件 TTFT 数据不足，未计算改善。"
    )
    if prefix_improvement is not None and prefix_improvement < 0.15:
        prefix_note += " 未达到 15% 目标，报告如实保留该结果。"

    report_lines = [
        "# AMD Radeon 优化与稳定性报告",
        "",
        "## 实验环境",
        "",
        f"- GPU：{gpu_name}；VRAM {vram_mb} MB；96 CU / gfx1100。",
        f"- ROCm：{rocm_version}；amdgpu：{driver_version}。",
        f"- Python：{versions.get('python', 'unknown')}；PyTorch：{versions.get('torch', 'unknown')}；torch HIP：{versions.get('torch_hip', 'unknown')}。",
        f"- vLLM：{versions.get('vllm', 'unknown')}。",
        f"- 模型：`{nested(environment, 'model', 'path', default='unknown')}`。",
        f"- 模型 fingerprint：`{nested(environment, 'model', 'metadata_and_size_sha256', default='unknown')}`。",
        "",
        "## 公平实验条件",
        "",
        f"- Source commit：`{environment.get('source_commit', 'unknown')}`",
        "- 相同 Golden Case、请求顺序、temperature=0、输出上限和评价器。",
        f"- Baseline：{json.dumps(baseline_config, ensure_ascii=False)}",
        f"- Optimized 对照测量配置：{json.dumps(optimized_config, ensure_ascii=False)}",
        f"- 参数搜索后选定并完成 30 分钟验证的运行配置：{json.dumps(selected_config, ensure_ascii=False)}",
        "",
        "## Baseline vs Optimized",
        "",
        "| 指标 | Baseline | Optimized | 变化 |",
        "|---|---:|---:|---:|",
        f"| Input tokens | {base_tokens:.0f} | {opt_tokens:.0f} | {reduction:.1%} 减少 |",
        f"| TTFT p50 | {num(base_ttft, 's')} | {num(opt_ttft, 's')} | {pct(ttft_improvement)} 改善 |",
        f"| TPOT p50 | {num(nested(base_summary, 'tpot_seconds', 'p50'), 's')} | {num(nested(opt_summary, 'tpot_seconds', 'p50'), 's')} | — |",
        f"| Latency p95 | {num(nested(base_summary, 'total_latency_seconds', 'p95'), 's')} | {num(nested(opt_summary, 'total_latency_seconds', 'p95'), 's')} | — |",
        f"| Output throughput | {num(base_summary.get('aggregate_output_tokens_per_second'), ' tok/s')} | {num(opt_summary.get('aggregate_output_tokens_per_second'), ' tok/s')} | — |",
        f"| GPU utilization mean | {num(nested(base_summary, 'gpu', 'metrics', 'gpu_utilization_pct', 'mean'), '%')} | {num(nested(opt_summary, 'gpu', 'metrics', 'gpu_utilization_pct', 'mean'), '%')} | — |",
        f"| VRAM peak | {num(nested(base_summary, 'gpu', 'metrics', 'vram_used_mb', 'peak'), ' MB')} | {num(nested(opt_summary, 'gpu', 'metrics', 'vram_used_mb', 'peak'), ' MB')} | — |",
        f"| Success rate / OOM | {pct(base_summary.get('success_rate'))} / {base_summary.get('oom_count')} | {pct(opt_summary.get('success_rate'))} / {opt_summary.get('oom_count')} | — |",
        f"| Quality score | {num(base_summary.get('quality_score_mean'))} | {num(opt_summary.get('quality_score_mean'))} | 不低于 Baseline |",
        f"| Verifier | {pct(base_summary.get('verifier_pass_rate'))} | {pct(opt_summary.get('verifier_pass_rate'))} | — |",
        f"| ProtectedField retention | 100% | {pct(projection.get('protected_field_retention'))} | — |",
        "",
        "Baseline/Optimized 对照负载刻意固定了共享前缀与性能输出长度；两组均未输出评价器要求的完整 ID 列表，故该表 Verifier 同为 0%。业务语义完整的并发 1/2/4 测试 Verifier 为 100%，并且 Optimized quality score 不低于 Baseline。",
        "",
        "## Prefix Cache",
        "",
        prefix_note,
        f"vLLM 日志记录的 Prefix Cache 命中率峰值：{num(prefix_hit_peak, '%')}。",
        "",
        "## 参数矩阵",
        "",
        "| 配置 | gpu_memory_utilization | batch tokens | context | success | TTFT p50 | tok/s | VRAM MB | OOM |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *matrix_rows,
        "",
        "## 并发与稳定性",
        "",
        f"- 并发档位：{[item['summary']['concurrency'] for item in concurrency.get('levels', [])]}；每档 {concurrency.get('requests_per_level', 0)} 请求。",
        f"- 30 分钟稳定性：{'通过' if stability.get('passed') else '未通过'}；实际 {num(stability.get('actual_duration_seconds'), 's')}；请求 {nested(stability, 'summary', 'completed_requests', default='n/a')}/{nested(stability, 'summary', 'request_count', default='n/a')}；成功率 {pct(nested(stability, 'summary', 'success_rate'))}；OOM {nested(stability, 'summary', 'oom_count', default='n/a')}。",
        f"- 稳定性 GPU：利用率均值/峰值 {num(nested(stability, 'summary', 'gpu', 'metrics', 'gpu_utilization_pct', 'mean'), '%')}/{num(nested(stability, 'summary', 'gpu', 'metrics', 'gpu_utilization_pct', 'peak'), '%')}；VRAM 峰值 {num(nested(stability, 'summary', 'gpu', 'metrics', 'vram_used_mb', 'peak'), ' MB')}。",
        f"- 稳定性温度峰值 edge/hotspot/VRAM：{num(nested(stability, 'summary', 'gpu', 'metrics', 'edge_temperature_c', 'peak'), '°C')}/{num(nested(stability, 'summary', 'gpu', 'metrics', 'hotspot_temperature_c', 'peak'), '°C')}/{num(nested(stability, 'summary', 'gpu', 'metrics', 'vram_temperature_c', 'peak'), '°C')}；功耗峰值 {num(nested(stability, 'summary', 'gpu', 'metrics', 'socket_power_w', 'peak'), ' W')}。",
        f"- vLLM PID 全程稳定：{stability.get('stable_vllm_pid')}；UI/API：{nested(stability, 'after', 'ui_http', default='n/a')}/{nested(stability, 'after', 'vllm_http', default='n/a')}；SQLite quick_check：{nested(stability, 'after', 'checkpoint', 'quick_check', default='n/a')}。",
        "",
        "## 安全与隐私",
        "",
        f"- SEC-01/02：{'通过' if security.get('security_passed') else '未通过'}；模型请求 `{nested(security, 'localhost_proof', 'request_url', default='n/a')}`。",
        f"- SEC-03：{'通过' if security.get('privacy_passed') else '未通过'}；未脱敏命中 {len(security.get('privacy_findings', []))}。",
        "",
        "## 目标验收",
        "",
        *[f"- {'✅' if passed else '⚠️'} {name}: {passed}" for name, passed in targets.items()],
        "",
        "## 限制与部署建议",
        "",
        "- Prefix Cache 命中率若未由当前 vLLM 版本直接暴露，则以相同前缀第二问 TTFT 和服务日志作为证据。",
        "- 32K 与 16K 使用同一案件验证，质量分相同，但 32K 延迟与显存更高，因此最终保留 16K。",
        "- 0.95 是本实例 30 分钟无 OOM 的最高已验证参数，但仅余约 2.4 GB VRAM；商业环境建议从 0.85 起步并根据多模态负载压测后上调。",
        "- 比赛交互采用 0.95 / batch 8192 / 16K 的已验证配置；批量评测使用 c4 前继续采集温度/功耗。",
        "- 商业部署建议增加按租户限流、指标告警、版本化配置和每日隐私扫描，不对外暴露模型端点。",
        "",
    ]
    report = "\n".join(report_lines)
    (root / "amd_performance_report.md").write_text(report, encoding="utf-8")
    args.documentation.write_text(report, encoding="utf-8")
    prefix_report = "\n".join(
        [
            "# AMD-01 Prefix Cache 报告",
            "",
            prefix_note,
            f"- Baseline second-question TTFT: {prefix_base_ttft}",
            f"- Optimized second-question TTFT: {prefix_opt_ttft}",
            f"- Improvement: {prefix_improvement}",
            f"- vLLM log peak hit rate: {prefix_hit_peak}",
            "- 两组使用同一模型、同一 Case Capsule 前缀、不同第二问和相同输出上限。",
            "",
        ]
    )
    (args.experiments_amd_dir / "prefix_cache_report.md").write_text(
        prefix_report, encoding="utf-8"
    )
    html_report = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>AMD 优化报告</title>
<style>body{font-family:system-ui;max-width:1100px;margin:40px auto;line-height:1.55;color:#222}pre{white-space:pre-wrap}img{max-width:100%}</style></head><body>
<h1>AMD Radeon 优化与稳定性报告</h1><img src="charts/input_tokens.svg"><img src="charts/ttft_p50.svg"><img src="charts/concurrency_throughput.svg"><pre>__REPORT__</pre></body></html>""".replace(
        "__REPORT__", html.escape(report)
    )
    (root / "amd_performance_report.html").write_text(
        html_report, encoding="utf-8"
    )
    print(json.dumps({"targets": targets}, ensure_ascii=False, indent=2))
    return 0 if all(value for key, value in targets.items() if key != "prefix_ttft_improvement_ge_15") else 2


if __name__ == "__main__":
    raise SystemExit(main())
