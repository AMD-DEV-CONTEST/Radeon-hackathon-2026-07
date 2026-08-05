#!/usr/bin/env python3
"""
生成管理层摘要报告（GPU 推理环节）。

用法:
    python3 scripts/generate_report.py [选项]

选项:
    --demo          使用演示模式（生成更丰富的报告，无需 LLM 服务）
    --mock          启动内置 Mock LLM 服务（无需外部 LLM，模拟真实响应）
    --input PATH    指定分析结果路径（默认 data/output/analysis_result.json）

环境变量:
    LLM_BASE_URL: LLM 服务地址（默认 http://localhost:8000/v1）
    LLM_MODEL: 模型名称（默认 meta-llama/Llama-3.1-8B-Instruct）
"""

import sys
import os
import time
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.report_generator import ReportGenerator
from src.agent import load_config
from rich.console import Console
from rich.markdown import Markdown

console = Console()


def _start_mock_server(port: int = 0):
    """启动内置 Mock LLM 服务，返回 (base_url, model_name)。
    Mock 响应不包含任何固定 SKU、金额、品类等业务事实。"""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class MockHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/v1/models":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "object": "list",
                    "data": [{"id": "mock-llm", "object": "model", "created": 1234567890, "owned_by": "mock"}]
                }).encode())

        def do_POST(self):
            if self.path == "/v1/chat/completions":
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len)) if content_len else {}
                prompt = body.get("messages", [{}])[-1].get("content", "")
                model_name = body.get("model", "mock-llm")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                mock_response = (
                    "这是 Mock LLM 响应。请以调用方提供的结构化事实区块为准；"
                    "本 Mock 不生成任何固定 SKU、金额或品类事实。"
                )

                resp = {
                    "id": "mock-cmpl",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": mock_response},
                        "finish_reason": "stop"
                    }],
                    "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(mock_response), "total_tokens": len(prompt) + len(mock_response)}
                }
                self.wfile.write(json.dumps(resp).encode())

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), MockHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    console.print(f"[dim]  内置 Mock LLM → http://127.0.0.1:{port}/v1[/dim]")
    return f"http://127.0.0.1:{port}/v1"


def _check_llm(base_url: str) -> bool:
    """探测 LLM 服务是否可达。"""
    import urllib.request
    try:
        r = urllib.request.urlopen(f"{base_url}/models", timeout=3)
        return r.status == 200
    except Exception:
        return False


def _generate_restricted_report(analysis_result: dict, quality_gate: dict) -> str:
    """质量门禁失败时生成限制性报告。"""
    checks = analysis_result.get("quality_checks", [])
    failed_items = [c for c in checks if not c.get("passed", True)]
    meta = analysis_result.get("_metadata", {})
    dp = meta.get("deliverable_package", {})

    lines = []
    lines.append("# 管理层报告不建议使用\n")
    lines.append("> ⚠️ **质量门禁未通过**，当前仅可查看 Excel 差异明细和审计过程报告，不建议使用管理层结论。\n")
    lines.append(f"- report_allowed: {quality_gate.get('report_allowed', False)}")
    lines.append(f"- critical 失败: {quality_gate.get('critical_failed', 0)}")
    lines.append(f"- major 失败: {quality_gate.get('major_failed', 0)}\n")

    if failed_items:
        lines.append("## 失败项\n")
        for c in failed_items:
            lines.append(f"- ❌ **{c.get('name', '')}** ({c.get('severity', '')})")
            lines.append(f"  - {c.get('detail', '')}\n")

    lines.append("## 可查看交付物\n")
    for key, info in dp.items():
        if info.get("exists"):
            lines.append(f"- ✅ {info.get('path', '')} — {info.get('purpose', '')}")
    lines.append("")

    return "\n".join(lines)


def main():
    demo_mode = "--demo" in sys.argv
    mock_mode = "--mock" in sys.argv
    result_path = "data/output/analysis_result.json"

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--input" and i < len(sys.argv) - 1:
            result_path = sys.argv[i + 1]

    if not Path(result_path).exists():
        console.print(f"[red]错误: 文件不存在 {result_path}[/red]")
        console.print("请先运行 python3 run_full_workflow.py 生成分析结果。")
        sys.exit(1)

    output_path = "data/output/管理层摘要报告.md"
    started_at = datetime.now(timezone.utc).isoformat()

    base_url = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
    model = os.getenv("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

    console.print(f"[bold]读取分析结果:[/bold] {result_path}")
    console.print(f"[bold]输出报告:[/bold] {output_path}")

    if demo_mode:
        console.print("[bold]模式:[/bold] 演示模式（规则化摘要）")
    elif mock_mode:
        console.print("[bold]模式:[/bold] Mock LLM 模式（启动内置模拟服务）")
    else:
        console.print(f"[bold]LLM 服务:[/bold] {base_url}")
        console.print(f"[bold]模型:[/bold] {model}")
    console.print()

    with open(result_path, "r", encoding="utf-8") as f:
        analysis_result = json.load(f)

    # 质量门禁检查
    quality_gate = analysis_result.get("_metadata", {}).get("quality_gate", {})
    report_allowed = quality_gate.get("report_allowed", True)
    critical_failed = quality_gate.get("critical_failed", 0)
    blocked_by_qg = not report_allowed or critical_failed > 0

    if blocked_by_qg and not demo_mode and not mock_mode:
        console.print("[red]✗ 质量门禁未通过，不允许生成管理层结论[/red]")
        console.print(f"  report_allowed={report_allowed}, critical_failed={critical_failed}")
        report = _generate_restricted_report(analysis_result, quality_gate)
        elapsed = 0
        fallback_used = False
        finish_mode = "restricted"
    else:
        config = load_config()

        if mock_mode:
            mock_url = _start_mock_server(0)
            os.environ["LLM_BASE_URL"] = mock_url
            os.environ["LLM_MODEL"] = "mock-llm"
            os.environ["LLM_STREAMING"] = "false"
            base_url = mock_url

        generator = ReportGenerator(config)

        if demo_mode:
            start_time = time.time()
            console.print("[yellow]正在生成演示报告...[/yellow]")
            report = generator.generate_report(analysis_result, demo_mode=True)
            elapsed = time.time() - start_time
            fallback_used = False
            finish_mode = "demo"
        elif mock_mode:
            if not _check_llm(base_url):
                console.print("[red]内置 Mock 服务启动失败，回退到演示模式[/red]")
                report = generator.generate_report(analysis_result, demo_mode=True)
                elapsed = 0
                fallback_used = True
                finish_mode = "demo_fallback"
            else:
                start_time = time.time()
                console.print("[yellow]正在使用 Mock LLM 生成报告...[/yellow]")
                report = generator.generate_report(analysis_result)
                elapsed = time.time() - start_time
                fallback_used = False
                finish_mode = "mock"
        else:
            if not _check_llm(base_url):
                console.print(f"[red]✗ LLM 服务 {base_url} 不可达[/red]")
                console.print()
                console.print("[yellow]解决方案:[/yellow]")
                console.print("  1. [green]python3 scripts/generate_report.py --mock[/green]  — 内置模拟服务")
                console.print("  2. [green]python3 scripts/generate_report.py --demo[/green]  — 演示模式，无需 LLM")
                console.print("  3. 启动 vLLM:  vllm serve <模型名> --host 0.0.0.0 --port 8000")
                console.print("  4. 设置环境变量:  LLM_BASE_URL=your-llm-endpoint LLM_MODEL=your-model")
                sys.exit(1)
            console.print("[green]✓ LLM 服务可达[/green]")
            start_time = time.time()
            console.print("[yellow]正在使用本地 LLM 生成报告...[/yellow]")
            report = generator.generate_report(analysis_result)
            elapsed = time.time() - start_time
            fallback_used = False
            finish_mode = "real_llm"

    finished_at = datetime.now(timezone.utc).isoformat()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report, encoding="utf-8")

    # 保存报告生成元数据
    run_id = analysis_result.get("_metadata", {}).get("run_id", analysis_result.get("run_id", "N/A"))
    mode_label = finish_mode
    metadata = {
        "mode": mode_label,
        "model": model if finish_mode != "restricted" else "N/A",
        "base_url": base_url if finish_mode != "restricted" else "N/A",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": round(elapsed, 3),
        "input_analysis_result": result_path,
        "output_report": output_path,
        "fallback_used": fallback_used,
        "blocked_by_quality_gate": blocked_by_qg,
        "report_allowed": report_allowed,
        "run_id": run_id,
    }
    metadata_path = "data/output/report_generation_metadata.json"
    Path(metadata_path).parent.mkdir(parents=True, exist_ok=True)
    Path(metadata_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print()
    console.rule("[bold green]管理层摘要报告[/bold green]")
    console.print(Markdown(report))
    console.print()
    console.print(f"[green]✓ 报告已保存到 {output_path}[/green]")
    console.print(f"[green]✓ 元数据已保存到 {metadata_path}[/green]")
    console.print(f"[bold]生成耗时:[/bold] {elapsed:.3f}s")

    if finish_mode == "restricted":
        console.print("[yellow]⚠️ 质量门禁未通过，已生成限制性报告而非正常管理层结论[/yellow]")
    elif finish_mode == "demo":
        console.print("[bold]模式:[/bold] 演示模式（规则化摘要，无需 GPU）")
    elif finish_mode == "demo_fallback":
        console.print("[bold]模式:[/bold] Mock 回退到演示模式（无需 GPU）")
    elif finish_mode == "mock":
        console.print("[bold]模式:[/bold] Mock LLM（模拟推理，无 GPU 依赖）")
    else:
        console.print("[bold]模式:[/bold] 本地 LLM 推理（GPU 环节）")


if __name__ == "__main__":
    main()
