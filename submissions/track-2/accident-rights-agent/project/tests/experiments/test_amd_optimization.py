from __future__ import annotations

import json
from pathlib import Path

from app.memory.protected_fields import protected_set
from benchmarks.amd.common import summarize_runs
from benchmarks.amd.prepare_inputs import project_necessary_tool_fields
from benchmarks.amd.security_checks import endpoint_scan, privacy_scan
from experiments.memory.gpu import PATTERNS


def test_projection_deduplicates_capsule_without_losing_protected_fields() -> None:
    payload = {
        "task": "duplicate",
        "facts": [{"fact_id": "FACT-1", "source_node_ids": ["NODE-1"]}],
        "citations": [{"source_id": "LAW-1"}],
        "protected_values": {
            "date": ["2026-08-02"],
            "fact_id": ["FACT-1"],
            "evidence_id": ["NODE-1"],
            "law_id": ["LAW-1"],
        },
        "capsule": {
            "confirmed_facts": [{"fact_id": "FACT-1"}],
            "citations": [{"source_id": "LAW-1"}],
            "missing_evidence": [],
            "version": 2,
        },
    }
    projected = project_necessary_tool_fields(payload)
    assert "confirmed_facts" not in projected["capsule"]
    assert "citations" not in projected["capsule"]
    assert "missing_evidence" not in projected["capsule"]
    assert "task" not in projected
    assert protected_set(payload) <= protected_set(projected)


def test_summary_records_failures_and_oom() -> None:
    runs = [
        {
            "success": True,
            "input_tokens": 100,
            "output_tokens": 20,
            "ttft_seconds": 0.1,
            "tpot_seconds": 0.02,
            "total_latency_seconds": 0.5,
            "quality": {"verifier_pass": True, "quality_score": 98},
        },
        {"success": False, "error": "CUDA out of memory (OOM)"},
    ]
    summary = summarize_runs(runs, wall_seconds=1.0)
    assert summary["completed_requests"] == 1
    assert summary["failed_requests"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["oom_count"] == 1


def test_amd_smi_patterns_include_temperature() -> None:
    sample = """
        GFX_ACTIVITY: 99 %
        SOCKET_POWER: 207 W
        EDGE: 61 °C
        HOTSPOT: 72 °C
        MEM: 70 °C
        USED_VRAM: 43820 MB
    """
    assert PATTERNS["gpu_utilization_pct"].search(sample).group(1) == "99"
    assert PATTERNS["edge_temperature_c"].search(sample).group(1) == "61"
    assert PATTERNS["hotspot_temperature_c"].search(sample).group(1) == "72"
    assert PATTERNS["vram_temperature_c"].search(sample).group(1) == "70"


def test_security_and_privacy_scans(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "client.py").write_text(
        'MODEL_URL = "https://api.openai.com/v1"\n', encoding="utf-8"
    )
    findings = endpoint_scan(tmp_path)
    assert {item["kind"] for item in findings} >= {
        "openai",
        "non_loopback_model_url",
    }
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "report.json").write_text(
        json.dumps({"姓名": "张三", "电话": "13800138000"}, ensure_ascii=False),
        encoding="utf-8",
    )
    privacy = privacy_scan([demo])
    assert {item["kind"] for item in privacy} == {"name", "phone"}


def test_security_scan_ignores_runtime_url_template(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "serve.sh").write_text(
        "printf 'LISTEN=http://%s:%s/v1\\n' \"$host\" \"$port\"\n",
        encoding="utf-8",
    )
    assert endpoint_scan(tmp_path) == []


def test_privacy_scan_ignores_floating_point_metrics(tmp_path: Path) -> None:
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "metrics.json").write_text(
        json.dumps(
            {
                "tpot_seconds": 0.040052330652469874,
                "latency": 1.3800138000123456,
            }
        ),
        encoding="utf-8",
    )
    assert privacy_scan([demo]) == []


def test_privacy_scan_finds_valid_identity(tmp_path: Path) -> None:
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "report.json").write_text(
        json.dumps({"身份证": "11010519491231002X"}, ensure_ascii=False),
        encoding="utf-8",
    )
    findings = privacy_scan([demo])
    assert {item["kind"] for item in findings} == {"identity"}
