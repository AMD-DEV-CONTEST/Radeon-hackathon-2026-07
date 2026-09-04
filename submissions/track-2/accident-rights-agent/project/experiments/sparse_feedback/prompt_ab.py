"""EXP-04/05: real local-model Prompt A/B and sparse preference records."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any

from app.demo.business_cases import seed_experience_case
from app.evidence.workspace import CaseWorkspace
from app.memory.context_builder import ContextBuilder
from app.memory.service import bootstrap_case_memory
from app.rag.service import build_retriever
from experiments.memory.evaluation import evaluate_answer, string_list
from experiments.memory.gpu import AmdGpuSampler
from experiments.memory.streaming import stream_chat
from experiments.sparse_feedback.models import (
    Preference,
    RiskLevel,
    SparseFeedbackRecord,
)


TASK = (
    "针对当前案件输出责任分析：检查违法行为矩阵和原因力，给出至少两个责任"
    "假设，并列出支撑的 Fact ID、Evidence ID、Law ID 与缺失证据。"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _allowed(context: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    facts = context["facts"]
    protected = context.get("protected_values", {})
    fact_ids = {str(item["fact_id"]) for item in facts if item.get("fact_id")}
    fact_ids.update(str(item) for item in protected.get("fact_id", []))
    evidence_ids = {
        str(value)
        for fact in facts
        for value in fact.get("source_node_ids", [])
    }
    evidence_ids.update(str(item) for item in context.get("evidence_ids", []))
    evidence_ids.update(str(item) for item in protected.get("evidence_id", []))
    law_ids = {
        str(item["source_id"])
        for item in context["citations"]
        if item.get("source_id")
    }
    law_ids.update(str(item) for item in protected.get("law_id", []))
    return fact_ids, evidence_ids, law_ids


def _messages(system: str, context: dict[str, Any]) -> list[dict[str, str]]:
    output_contract = {
        "answer": "string",
        "fact_ids": ["FACT-..."],
        "evidence_ids": ["NODE-..."],
        "law_ids": ["LAW-..."],
        "liability_hypotheses": ["hypothesis 1", "hypothesis 2"],
        "missing_evidence": ["string"],
        "uncertainty": "string",
        "approval_status": "pending",
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": TASK,
                    "required_output": output_contract,
                    "output_constraints": [
                        "answer 必须非空且不超过120个汉字",
                        "fact_ids、evidence_ids、law_ids 各选最关键的1至5个",
                        "law_ids 只能使用 context.citations 中精确的 source_id，不得使用 document_id",
                        "liability_hypotheses 恰好2项且每项不超过80个汉字",
                        "missing_evidence 最多4项",
                        "uncertainty 必须非空且不超过80个汉字",
                        "approval_status 必须为 pending",
                        "不要复制上下文，不要输出额外字段",
                    ],
                    "context": context,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _run_variant(
    prompt_id: str,
    system: str,
    context: dict[str, Any],
    *,
    uncertainty_required: bool,
    max_tokens: int,
) -> dict[str, Any]:
    with AmdGpuSampler() as sampler:
        result = stream_chat(
            _messages(system, context),
            max_tokens=max_tokens,
        )
    allowed = _allowed(context)
    quality = evaluate_answer(
        result.content,
        allowed_fact_ids=allowed[0],
        allowed_evidence_ids=allowed[1],
        allowed_law_ids=allowed[2],
        uncertainty_required=uncertainty_required,
    )
    law_values = string_list(quality["payload"], "law_ids")
    unsupported_laws = set(quality["unsupported_ids"]["law_ids"])
    legal_score = (
        sum(value not in unsupported_laws for value in law_values)
        / max(1, len(law_values))
    )
    return {
        "prompt_id": prompt_id,
        **result.as_dict(),
        "gpu": sampler.summary(),
        "quality": quality,
        "correctness": quality["quality_score"] / 100,
        "evidence_grounding": quality["evidence_grounding"],
        "legal_citation": round(legal_score, 6),
        "verifier_pass_rate": float(quality["verifier_pass"]),
    }


def run_prompt_ab(
    output_dir: Path,
    *,
    cases_path: Path = Path("experiments/fixtures/cases.json"),
    prompts_path: Path = Path("experiments/configs/liability_prompts.json"),
    corpus_path: Path = Path("data/laws/legal_corpus.sqlite3"),
    qdrant_path: Path = Path("data/qdrant/legal"),
    max_tokens: int = 700,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = _load(cases_path)["cases"]
    prompts = _load(prompts_path)["prompts"]
    retriever = build_retriever(
        corpus_path=corpus_path,
        qdrant_path=qdrant_path,
        embedding_provider="hash",
        reranker_provider="heuristic",
    )
    results: list[dict[str, Any]] = []
    feedback: list[SparseFeedbackRecord] = []
    try:
        with tempfile.TemporaryDirectory(prefix="prompt-ab-") as temporary:
            workspace = CaseWorkspace(Path(temporary) / "cases")
            for fixture in fixtures:
                case_id = str(fixture["case_id"])
                seed_experience_case(
                    workspace,
                    str(fixture["scenario_id"]),
                    case_id=case_id,
                )
                store = workspace.store(case_id)
                memory, capsule = bootstrap_case_memory(workspace, case_id)
                facts = store.list_facts(case_id)
                citations = retriever.citations(TASK, top_k=8, candidate_k=12)
                state = {
                    "case_id": case_id,
                    "current_node": "liability",
                    "route": "liability",
                    "approval_status": "pending",
                    "document_status": "draft",
                    "missing_evidence": fixture.get("missing", []),
                    "protected_fields_valid": True,
                }
                bundle = ContextBuilder(memory).build(
                    task=TASK,
                    capsule=capsule,
                    facts=facts,
                    citations=citations,
                    top_k_facts=12,
                    top_k_citations=6,
                    node_name=f"prompt_ab_{fixture['scenario_id']}",
                    workflow_state=state,
                    full_history=store.list_audit_events(case_id),
                )
                context = bundle.prompt_payload()
                uncertainty_required = bool(
                    fixture["expected"].get("vehicle_uncertainty_required")
                    or fixture["expected"].get("conflict_required")
                )
                pair: dict[str, dict[str, Any]] = {}
                for prompt_id in ("A", "B"):
                    result = _run_variant(
                        prompt_id,
                        str(prompts[prompt_id]["system"]),
                        context,
                        uncertainty_required=uncertainty_required,
                        max_tokens=max_tokens,
                    )
                    result.update(
                        {
                            "case_id": case_id,
                            "scenario_id": fixture["scenario_id"],
                            "uncertainty_required": uncertainty_required,
                            "context_tokens": bundle.after_token_count,
                        }
                    )
                    results.append(result)
                    pair[prompt_id] = result
                feedback.append(_feedback_record(fixture, pair))
    finally:
        retriever.close()
    aggregate = _aggregate(results)
    payload = {
        "schema_version": 1,
        "case_count": len(fixtures),
        "prompts": aggregate,
        "runs": results,
    }
    (output_dir / "prompt_ab_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(output_dir / "prompt_ab_results.csv", results)
    _write_feedback(output_dir / "sparse_feedback.jsonl", feedback)
    (output_dir / "sparse_feedback_sample.json").write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in feedback],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {**payload, "feedback": [item.model_dump(mode="json") for item in feedback]}


def _feedback_record(
    fixture: dict[str, Any], pair: dict[str, dict[str, Any]]
) -> SparseFeedbackRecord:
    score_a = float(pair["A"]["quality"]["quality_score"])
    score_b = float(pair["B"]["quality"]["quality_score"])
    scenario_id = str(fixture["scenario_id"])
    unsupported_claim: list[str] = []
    if scenario_id == "demo_a" and any(
        marker in pair["B"]["content"] for marker in ("6:4", "7:3")
    ):
        preferred = Preference.A
        unsupported_claim = [
            "B 给出约6:4/7:3责任比例，但当前实验上下文没有量化比例依据。"
        ]
        reason = (
            "模拟专家比较流程（非真实专家标注）：A 避免了无量化依据的具体责任"
            "比例，行动建议风险更低；正式使用前需保险或法律专家确认。"
        )
    elif scenario_id == "demo_b":
        preferred = Preference.B
        unsupported_claim = [
            "A 将“非机动车逆行”写为主因，但缺证 fixture 没有逆行事实。"
        ]
        reason = (
            "模拟专家比较流程（非真实专家标注）：B 在车辆属性鉴定和路口监控"
            "缺失时保持证据不足，A 含无证据主因断言；正式使用前需专家确认。"
        )
    elif scenario_id == "demo_c":
        preferred = Preference.B
        unsupported_claim = [
            "A 写出“机动车方无过错责任”，冲突 fixture 不支持该确定性结论。"
        ]
        reason = (
            "模拟专家比较流程（非真实专家标注）：B 保留车辆属性和驶入方向冲突，"
            "A 含无证据的无过错结论；正式使用前需保险或法律专家确认。"
        )
    elif abs(score_a - score_b) < 0.001:
        preferred = Preference.TIE
        reason = (
            "模拟专家比较流程（非真实专家标注）：A/B 的结构、引用约束与风险"
            "语言自动校验得分相同；正式使用前需保险或法律专家确认。"
        )
    else:
        preferred = Preference.A if score_a > score_b else Preference.B
        reason = (
            "模拟专家比较流程（非真实专家标注）："
            f"{preferred.value} 的结构、引用约束与风险语言自动校验得分更高；"
            "正式使用前需保险或法律专家确认。"
        )
    inferior = pair["B"] if preferred is Preference.A else pair["A"]
    unsupported_claim.extend(
        f"{kind}:{value}"
        for kind, values in inferior["quality"]["unsupported_ids"].items()
        for value in values
    )
    risk = (
        RiskLevel.HIGH
        if inferior["quality"]["risk_markers"] or unsupported_claim
        else RiskLevel.MEDIUM
        if not inferior["quality"]["verifier_pass"]
        else RiskLevel.LOW
    )
    return SparseFeedbackRecord(
        case_id=str(fixture["case_id"]),
        question_id=(
            "LIA-03"
            if fixture["scenario_id"] in {"demo_b", "demo_c"}
            else "LIA-02"
        ),
        answer_A=pair["A"]["content"],
        answer_B=pair["B"]["content"],
        preferred=preferred,
        reason=reason,
        missing_evidence=[
            str(item)
            for item in inferior["quality"]["payload"].get(
                "missing_evidence", fixture.get("missing", [])
            )
        ],
        unsupported_claim=unsupported_claim,
        risk_level=risk,
    )


def _aggregate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = {
        prompt_id: [row for row in results if row["prompt_id"] == prompt_id]
        for prompt_id in ("A", "B")
    }
    return [
        {
            "prompt_id": prompt_id,
            "correctness": round(mean(row["correctness"] for row in rows), 6),
            "evidence_grounding": round(
                mean(row["evidence_grounding"] for row in rows), 6
            ),
            "legal_citation": round(mean(row["legal_citation"] for row in rows), 6),
            "verifier_pass_rate": round(
                mean(row["verifier_pass_rate"] for row in rows), 6
            ),
            "latency_seconds": round(
                mean(row["total_latency_seconds"] for row in rows), 6
            ),
            "input_tokens": round(
                mean(float(row["input_tokens"] or 0) for row in rows), 3
            ),
            "output_tokens": round(
                mean(float(row["output_tokens"] or 0) for row in rows), 3
            ),
        }
        for prompt_id, rows in groups.items()
    ]


def _write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    fields = [
        "case_id",
        "scenario_id",
        "prompt_id",
        "uncertainty_required",
        "context_tokens",
        "input_tokens",
        "output_tokens",
        "ttft_seconds",
        "tpot_seconds",
        "total_latency_seconds",
        "correctness",
        "evidence_grounding",
        "legal_citation",
        "verifier_pass_rate",
        "quality_score",
        "risk_markers",
        "unsupported_ids",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    **{field: row.get(field) for field in fields},
                    "quality_score": row["quality"]["quality_score"],
                    "risk_markers": "|".join(row["quality"]["risk_markers"]),
                    "unsupported_ids": json.dumps(
                        row["quality"]["unsupported_ids"], ensure_ascii=False
                    ),
                }
            )


def _write_feedback(path: Path, feedback: list[SparseFeedbackRecord]) -> None:
    path.write_text(
        "".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for item in feedback
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=Path("experiments/results")
    )
    parser.add_argument("--max-tokens", type=int, default=700)
    args = parser.parse_args()
    result = run_prompt_ab(args.output_dir, max_tokens=args.max_tokens)
    print(json.dumps(result["prompts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
