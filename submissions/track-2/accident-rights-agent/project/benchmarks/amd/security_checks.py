#!/usr/bin/env python3
"""Generate SEC-01..03 endpoint and privacy evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PUBLIC_MODEL_PATTERNS = {
    "openai": re.compile(r"api\.openai\.com|OPENAI_API_KEY", re.I),
    "dashscope_qwen": re.compile(r"dashscope|aliyuncs.*(qwen|model)", re.I),
    "deepseek": re.compile(r"api\.deepseek\.com|DEEPSEEK_API_KEY", re.I),
    "non_loopback_model_url": re.compile(
        r"https?://(?!127\.0\.0\.1(?::\d+)?(?:/|\b)|localhost(?::\d+)?(?:/|\b))"
        r"[A-Za-z0-9.-]+(?::\d+)?/(?:v1|chat/completions|models)",
        re.I,
    ),
}
PHONE = re.compile(r"(?<![\d.])1[3-9]\d{9}(?!\d)")
IDENTITY = re.compile(
    r"(?<![\d.])[1-9]\d{5}(?:19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"
)
NAME_FIELD = re.compile(
    r"[\"']?(?:姓名|当事人姓名|party_name|person_name|claimant_name)[\"']?\s*[:=]\s*[\"']([^\"'\n]{2,20})[\"']",
    re.I,
)

IDENTITY_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
IDENTITY_CHECK_CODES = "10X98765432"


def valid_identity(value: str) -> bool:
    """Return whether a candidate has a real date and PRC ID checksum."""
    try:
        datetime.strptime(value[6:14], "%Y%m%d")
    except ValueError:
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value[:17], IDENTITY_WEIGHTS))
    return IDENTITY_CHECK_CODES[total % 11] == value[-1].upper()


def text_files(roots: Iterable[Path]) -> Iterable[Path]:
    ignored = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
    allowed = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".env"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or any(part in ignored for part in path.parts):
                continue
            if path.suffix.lower() in allowed or path.name == ".env.example":
                yield path


def endpoint_scan(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    scan_roots = [root / name for name in ("app", "config", "scripts", "benchmarks")]
    for path in text_files(scan_roots):
        if path.name in {"verify_local_only.sh", "security_checks.py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for kind, pattern in PUBLIC_MODEL_PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "kind": kind,
                        "file": str(path.relative_to(root)),
                        "line": text.count("\n", 0, match.start()) + 1,
                        "match": match.group(0)[:160],
                    }
                )
    return findings


def request_proof() -> dict[str, Any]:
    url = "http://127.0.0.1:8000/v1/models"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        status = response.status
    process = subprocess.run(
        ["pgrep", "-af", "vllm serve"],
        check=False,
        capture_output=True,
        text=True,
    )
    listener = subprocess.run(
        ["ss", "-ltnp", "sport", "=", ":8000"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_url": url,
        "http_status": status,
        "models": [item.get("id") for item in payload.get("data", [])],
        "process": process.stdout.strip(),
        "listener": listener.stdout.strip(),
        "passed": status == 200
        and "127.0.0.1" in process.stdout
        and "127.0.0.1:8000" in listener.stdout,
    }


def privacy_scan(roots: Iterable[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    suffixes = {".json", ".jsonl", ".csv", ".md", ".html"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if path.stat().st_size > 10_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for kind, pattern in (("phone", PHONE), ("identity", IDENTITY)):
                for match in pattern.finditer(text):
                    if kind == "identity" and not valid_identity(match.group(0)):
                        continue
                    findings.append(
                        {"kind": kind, "file": str(path), "value": match.group(0)}
                    )
            for match in NAME_FIELD.finditer(text):
                value = match.group(1).strip()
                if not any(marker in value for marker in ("某", "*", "合成", "示例", "demo")):
                    findings.append({"kind": "name", "file": str(path), "value": value})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--demo-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    endpoint_findings = endpoint_scan(args.project_root)
    proof = request_proof()
    privacy_findings = privacy_scan(args.demo_root)
    security_passed = not endpoint_findings and proof["passed"]
    privacy_passed = not privacy_findings
    details = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint_findings": endpoint_findings,
        "localhost_proof": proof,
        "privacy_findings": privacy_findings,
        "security_passed": security_passed,
        "privacy_passed": privacy_passed,
    }
    (args.output_dir / "security_checks.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "localhost_request_proof.log").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    security_md = "\n".join(
        [
            "# SEC-01/02 模型端点安全扫描",
            "",
            f"- 公共模型端点/API Key 模式命中：{len(endpoint_findings)}",
            f"- 实际请求地址：`{proof['request_url']}`",
            f"- HTTP 状态：{proof['http_status']}",
            f"- 监听/进程均为 loopback：{proof['passed']}",
            f"- 结论：{'通过' if security_passed else '未通过'}",
            "",
        ]
    )
    (args.output_dir / "security_scan_report.md").write_text(
        security_md, encoding="utf-8"
    )
    privacy_md = "\n".join(
        [
            "# SEC-03 Demo 隐私检查",
            "",
            f"- 未脱敏姓名/手机号/身份证命中：{len(privacy_findings)}",
            f"- 结论：{'通过' if privacy_passed else '未通过'}",
            "",
        ]
    )
    (args.output_dir / "privacy_check_report.md").write_text(
        privacy_md, encoding="utf-8"
    )
    print(json.dumps(details, ensure_ascii=False, indent=2))
    return 0 if security_passed and privacy_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
