"""MEM-03/04/05: full context vs task-scoped Case Capsule on Golden Case."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.demo.golden_case import seed_golden_case
from app.agents.vehicle_nature import VehicleNatureAgent
from app.memory.context_builder import ContextBuilder, estimate_tokens
from app.memory.protected_fields import protected_set
from app.memory.service import bootstrap_case_memory
from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex
from app.schemas.legal import LegalCitation
from app.services.case_service import CaseService
from app.rag.retrieval import HybridLegalRetriever
from experiments.memory.evaluation import (
    conclusion_consistency,
    evaluate_answer,
)
from experiments.memory.gpu import AmdGpuSampler
from experiments.memory.streaming import stream_chat


SYSTEM_PROMPT = (
    "你是交通事故责任与权益分析 Agent。只依据输入上下文；不得发明 Fact ID、"
    "Evidence ID 或 Law ID；缺证据时必须保留不确定性；未经人工批准不得称可提交。"
    "严格输出 JSON，字段为 answer、fact_ids、evidence_ids、law_ids、"
    "liability_hypotheses、missing_evidence、uncertainty、approval_status。"
    "answer 必须非空且不超过120个汉字；Fact/Evidence/Law ID 各选最关键的1至5个；"
    "law_ids 只能使用 citations 中精确的 source_id，不得使用 document_id；"
    "liability_hypotheses 恰好2项、每项不超过80个汉字；missing_evidence 最多4项；"
    "uncertainty 必须非空且不超过80个汉字。不要复制上下文，不要输出额外字段。"
)
TASK = "分析违法行为、原因力、事故责任假设、关键权益期限和人工审批状态"


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _runtime(root: Path) -> tuple[CaseService, dict[str, Any]]:
    cases = CaseService(root / "cases")
    case_id = seed_golden_case(cases.workspace)
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    corpus_path = root / "legal.sqlite3"
    LegalCorpusStore(corpus_path).replace(documents, chunks)
    qdrant_path = root / "qdrant"
    index = LegalVectorIndex(qdrant_path, HashEmbeddingProvider(dimension=384))
    index.rebuild(chunks)
    retriever = HybridLegalRetriever(
        LegalCorpusStore(corpus_path),
        index,
    )
    citations: dict[str, LegalCitation] = {}
    try:
        for query in (
            "两轮电动车车辆属性登记鉴定和技术参数",
            "路口信号让行逆行观察制动与事故原因力",
            "机动车与非机动车事故责任和赔偿路径",
            "事故认定复核期限和人工批准",
        ):
            for citation in retriever.citations(query, top_k=3, candidate_k=10):
                citations[citation.source_id] = citation
    finally:
        retriever.close()
    store = cases.workspace.store(case_id)
    exported = store.export_case(case_id)
    vehicle = VehicleNatureAgent().run(
        facts=exported["facts"],
        legal_citations=list(citations.values()),
        conflicts=exported["conflicts"],
        accident_date=date(2026, 7, 20),
    )
    state = {
        "case_id": case_id,
        "thread_id": "THREAD-MEMORY-BASELINE",
        "current_node": "liability",
        "progress": 0.5,
        "route": "liability",
        "approval_status": "pending",
        "document_status": "draft",
        "protected_fields_valid": True,
        "vehicle_classification": {
            "classification": vehicle.classification.value,
            "confidence": vehicle.confidence,
            "conclusion_status": vehicle.conclusion_status,
        },
        "missing_evidence": [
            item.model_dump(mode="json") for item in vehicle.missing_evidence
        ],
        "legal_citations": [
            item.model_dump(mode="json") for item in citations.values()
        ],
    }
    return cases, state


def _allowed_ids(payload: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    facts = payload.get("facts", [])
    citations = payload.get("citations", [])
    protected = payload.get("protected_values", {})
    fact_ids = {str(item["fact_id"]) for item in facts if item.get("fact_id")}
    fact_ids.update(str(item) for item in protected.get("fact_id", []))
    evidence_ids = {
        str(evidence_id)
        for item in facts
        for evidence_id in item.get("source_node_ids", [])
    }
    evidence_ids.update(str(item) for item in payload.get("evidence_ids", []))
    evidence_ids.update(str(item) for item in protected.get("evidence_id", []))
    law_ids = {str(item["source_id"]) for item in citations if item.get("source_id")}
    law_ids.update(str(item) for item in protected.get("law_id", []))
    return fact_ids, evidence_ids, law_ids


def _messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"task": TASK, "context": payload},
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _measured_call(payload: dict[str, Any], *, max_tokens: int) -> dict[str, Any]:
    with AmdGpuSampler() as sampler:
        result = stream_chat(_messages(payload), max_tokens=max_tokens)
    allowed = _allowed_ids(payload)
    quality = evaluate_answer(
        result.content,
        allowed_fact_ids=allowed[0],
        allowed_evidence_ids=allowed[1],
        allowed_law_ids=allowed[2],
    )
    return {
        **result.as_dict(),
        "gpu": sampler.summary(),
        "quality": quality,
    }


def run_memory_experiment(
    output_dir: Path,
    *,
    max_tokens: int = 700,
    concurrency: int = 1,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="memory-experiment-") as temporary:
        cases, state = _runtime(Path(temporary))
        case_id = state["case_id"]
        store = cases.workspace.store(case_id)
        memory, capsule = bootstrap_case_memory(cases.workspace, case_id)
        facts = store.list_facts(case_id)
        citations = [
            LegalCitation.model_validate(item)
            for item in state.get("legal_citations", [])
        ]
        history = [
            {
                "event_id": item["id"],
                "event_type": item["event_type"],
                "actor": item["actor"],
                "timestamp": item["created_at"],
            }
            for item in store.list_audit_events(case_id)
        ]
        full_state = {
            key: value for key, value in state.items() if key != "legal_citations"
        }
        full_payload = {
            "case_id": case_id,
            "task": TASK,
            "capsule": capsule.model_dump(mode="json"),
            "facts": facts,
            "citations": [item.model_dump(mode="json") for item in citations],
            "workflow_state": full_state,
            "history": history,
        }
        bundle = ContextBuilder(memory).build(
            task=TASK,
            capsule=capsule,
            facts=facts,
            citations=citations,
            top_k_facts=8,
            top_k_citations=4,
            node_name="memory_experiment",
            workflow_state=full_state,
            full_history=history,
        )
        compact_payload = bundle.prompt_payload()
        _json_dump(output_dir / "full_context_input.json", full_payload)
        _json_dump(output_dir / "case_capsule_input.json", compact_payload)

        baseline = _measured_call(full_payload, max_tokens=max_tokens)
        optimized = _measured_call(compact_payload, max_tokens=max_tokens)
        before_fields = protected_set(full_payload)
        after_fields = protected_set(compact_payload)
        missing = sorted(before_fields - after_fields)
        retention = len(before_fields & after_fields) / max(1, len(before_fields))
        baseline_input_tokens = baseline.get("input_tokens") or estimate_tokens(
            _messages(full_payload)
        )
        optimized_input_tokens = optimized.get("input_tokens") or estimate_tokens(
            _messages(compact_payload)
        )
        comparison = {
            "schema_version": 1,
            "case_id": case_id,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "concurrency": concurrency,
            "token_reduction_ratio": round(
                1 - optimized_input_tokens / max(1, baseline_input_tokens), 6
            ),
            "latency_change_ratio": round(
                optimized["total_latency_seconds"]
                / max(0.000001, baseline["total_latency_seconds"])
                - 1,
                6,
            ),
            "vram_peak_change_mb": _peak_vram(optimized) - _peak_vram(baseline),
            "conclusion_consistency": conclusion_consistency(
                baseline["quality"]["payload"],
                optimized["quality"]["payload"],
            ),
            "protected_field_count": len(before_fields),
            "protected_field_retention": round(retention, 6),
            "missing_protected_fields": [
                {"kind": kind, "value": value} for kind, value in missing
            ],
            "fidelity_passed": retention == 1.0 and not missing,
        }
        baseline_report = {
            "schema_version": 1,
            "kind": "full_context_baseline",
            "case_id": case_id,
            "context_estimated_tokens": estimate_tokens(full_payload),
            **baseline,
        }
        optimized_report = {
            "schema_version": 1,
            "kind": "case_capsule_optimized",
            "case_id": case_id,
            "context_estimated_tokens": estimate_tokens(compact_payload),
            "context_builder_before_tokens": bundle.before_token_count,
            "context_builder_after_tokens": bundle.after_token_count,
            "protected_field_retention": bundle.protected_field_retention,
            **optimized,
        }
        _json_dump(output_dir / "baseline.json", baseline_report)
        _json_dump(output_dir / "optimized.json", optimized_report)
        _json_dump(output_dir / "comparison.json", comparison)
        _write_csv(output_dir / "memory_results.csv", baseline_report, optimized_report)
        if not comparison["fidelity_passed"]:
            raise RuntimeError(f"Protected fields lost: {missing}")
        return {
            "baseline": baseline_report,
            "optimized": optimized_report,
            "comparison": comparison,
        }


def _peak_vram(result: dict[str, Any]) -> float:
    value = result.get("gpu", {}).get("metrics", {}).get("vram_used_mb", {}).get(
        "peak"
    )
    return float(value or 0.0)


def _write_csv(path: Path, *rows: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            lineterminator="\n",
            fieldnames=[
                "kind",
                "input_tokens",
                "output_tokens",
                "ttft_seconds",
                "tpot_seconds",
                "total_latency_seconds",
                "tokens_per_second",
                "gpu_utilization_mean_pct",
                "gpu_utilization_peak_pct",
                "vram_used_peak_mb",
                "quality_score",
                "verifier_pass",
            ],
        )
        writer.writeheader()
        for row in rows:
            metrics = row["gpu"]["metrics"]
            writer.writerow(
                {
                    "kind": row["kind"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "ttft_seconds": row["ttft_seconds"],
                    "tpot_seconds": row["tpot_seconds"],
                    "total_latency_seconds": row["total_latency_seconds"],
                    "tokens_per_second": row["tokens_per_second"],
                    "gpu_utilization_mean_pct": metrics["gpu_utilization_pct"]["mean"],
                    "gpu_utilization_peak_pct": metrics["gpu_utilization_pct"]["peak"],
                    "vram_used_peak_mb": metrics["vram_used_mb"]["peak"],
                    "quality_score": row["quality"]["quality_score"],
                    "verifier_pass": row["quality"]["verifier_pass"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=Path("experiments/results/memory")
    )
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    result = run_memory_experiment(
        args.output_dir,
        max_tokens=args.max_tokens,
        concurrency=args.concurrency,
    )
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
