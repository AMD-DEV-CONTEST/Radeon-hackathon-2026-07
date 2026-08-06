#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_OUTPUT = ROOT / "evidence/v10/gtm-case-funnel-operational-progress-v2.json"
WEB_OUTPUT = ROOT / "artifacts/gtm-case-funnel-operational-progress-v2/index.html"


def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _progress(count: int, target: int) -> dict[str, Any]:
    return {
        "count": count,
        "target": target,
        "ratio": count / target,
        "percent": round(100 * count / target, 3),
    }


def main() -> int:
    discovery = _load("evidence/v10/gtm-all-subvertical-discovery-v2.json")
    unified = _load("evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json")
    queue = _load("evidence/v10/gtm-admission-acceleration-queue-v2.json")
    dossier = _load("evidence/v10/gtm-emailoctopus-admission-dossier-v2.json")
    buffer_dossier = _load("evidence/v10/gtm-buffer-admission-dossier-v2.json")
    flodesk_dossier = _load("evidence/v10/gtm-flodesk-admission-dossier-v2.json")
    postbridge_dossier = _load("evidence/v10/gtm-postbridge-admission-dossier-v2.json")
    parqet_dossier = _load("evidence/v10/gtm-parqet-admission-dossier-v2.json")
    spendbase_dossier = _load("evidence/v10/gtm-spendbase-admission-dossier-v2.json")
    barn2_dossier = _load("evidence/v10/gtm-barn2-admission-dossier-v2.json")
    rightmessage_dossier = _load("evidence/v10/gtm-rightmessage-admission-dossier-v2.json")
    socially_dossier = _load("evidence/v10/gtm-socially-admission-dossier-v2.json")
    automatio_blocker = _load("evidence/v10/gtm-automatio-blocker-dossier-v2.json")
    normalized = _load("data/gtm_case_funnel_v2/candidates.json")
    registry_path = ROOT / "data/gtm_case_funnel_v2/admitted-candidates.json"
    admitted = json.loads(registry_path.read_text()) if registry_path.exists() else {"candidate_count": 0, "formal_candidate_quota_credit": 0}
    target = 16_200
    stages = [
        {
            "stage": "public_leads",
            "label": "公开线索",
            "count": discovery["unique_discovery_lead_count"],
            "credit_semantics": "discovery_only",
            "next_action": "route and capture source-bound surfaces",
        },
        {
            "stage": "provisionally_routed_leads",
            "label": "已路由线索",
            "count": discovery["provisionally_routed_lead_count"],
            "credit_semantics": "provisional_route_only",
            "next_action": "resolve identity, period, market, budget, result and duplicates",
        },
        {
            "stage": "named_review_packets",
            "label": "实名复核包",
            "count": unified["review_packet_count"],
            "credit_semantics": "review_work_only",
            "next_action": "named human inspects exact public sources",
        },
        {
            "stage": "machine_ready_for_named_review",
            "label": "机器就绪",
            "count": unified["machine_ready_for_named_review_count"],
            "credit_semantics": "not_admitted",
            "next_action": "execute P0, then quantified P1 review lanes",
        },
        {
            "stage": "normalized_zero_credit_records",
            "label": "结构化但未入账",
            "count": normalized["candidate_count"],
            "credit_semantics": "CaseCandidateV2_shape_without_source_bound_budget_admission",
            "next_action": "close source-bound budget and human evidence gates",
        },
        {
            "stage": "formal_casecandidate_v2",
            "label": "正式 CaseCandidateV2",
            "count": admitted.get("formal_candidate_quota_credit", 0),
            "credit_semantics": "formal_quota_credit",
            "next_action": "continue admission while preserving all six marginal quotas",
        },
    ]
    email_card = {
        "company": "EmailOctopus",
        "prepared_gate_count": dossier["evidence_ready_gate_count"],
        "gate_count": dossier["gate_count"],
        "captured_source_count": dossier["captured_source_count"],
        "independent_source_count": dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-emailoctopus-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_emailoctopus_case_v2.py --intake /absolute/path/emailoctopus-named-review-intake-v2.json",
    }
    buffer_card = {
        "company": "Buffer",
        "prepared_gate_count": buffer_dossier["evidence_ready_gate_count"],
        "gate_count": buffer_dossier["gate_count"],
        "captured_source_count": buffer_dossier["captured_source_count"],
        "independent_source_count": buffer_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-buffer-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_buffer_case_v2.py --intake /absolute/path/buffer-named-review-intake-v2.json",
    }
    flodesk_card = {
        "company": "Flodesk",
        "prepared_gate_count": flodesk_dossier["evidence_ready_gate_count"],
        "gate_count": flodesk_dossier["gate_count"],
        "captured_source_count": flodesk_dossier["captured_source_count"],
        "independent_source_count": flodesk_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-flodesk-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_flodesk_case_v2.py --intake /absolute/path/flodesk-named-review-intake-v2.json",
    }
    postbridge_card = {
        "company": "Post Bridge",
        "prepared_gate_count": postbridge_dossier["evidence_ready_gate_count"],
        "gate_count": postbridge_dossier["gate_count"],
        "captured_source_count": postbridge_dossier["captured_source_count"],
        "independent_source_count": postbridge_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-postbridge-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_postbridge_case_v2.py --intake /absolute/path/post-bridge-named-review-intake-v2.json",
    }
    parqet_card = {
        "company": "Parqet",
        "prepared_gate_count": parqet_dossier["evidence_ready_gate_count"],
        "gate_count": parqet_dossier["gate_count"],
        "captured_source_count": parqet_dossier["captured_source_count"],
        "independent_source_count": parqet_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-parqet-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_parqet_case_v2.py --intake /absolute/path/parqet-named-review-intake-v2.json",
    }
    spendbase_card = {
        "company": "Spendbase",
        "prepared_gate_count": spendbase_dossier["evidence_ready_gate_count"],
        "gate_count": spendbase_dossier["gate_count"],
        "captured_source_count": spendbase_dossier["captured_source_count"],
        "independent_source_count": spendbase_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-spendbase-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_spendbase_case_v2.py --intake /absolute/path/spendbase-named-review-intake-v2.json",
    }
    barn2_card = {
        "company": "Barn2",
        "prepared_gate_count": barn2_dossier["evidence_ready_gate_count"],
        "gate_count": barn2_dossier["gate_count"],
        "captured_source_count": barn2_dossier["captured_source_count"],
        "independent_source_count": barn2_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-barn2-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_barn2_case_v2.py --intake /absolute/path/barn2-named-review-intake-v2.json",
    }
    rightmessage_card = {
        "company": "RightMessage",
        "prepared_gate_count": rightmessage_dossier["evidence_ready_gate_count"],
        "gate_count": rightmessage_dossier["gate_count"],
        "captured_source_count": rightmessage_dossier["captured_source_count"],
        "independent_source_count": rightmessage_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-rightmessage-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_rightmessage_case_v2.py --intake /absolute/path/rightmessage-named-review-intake-v2.json",
    }
    socially_card = {
        "company": "Socially (RazrTech)",
        "prepared_gate_count": socially_dossier["evidence_ready_gate_count"],
        "gate_count": socially_dossier["gate_count"],
        "captured_source_count": socially_dossier["captured_source_count"],
        "independent_source_count": socially_dossier["independent_captured_source_count"],
        "remaining_gate": "named_human_exact_binding",
        "named_review_page": "../gtm-socially-named-review-v2/index.html",
        "post_review_command": "PYTHONPATH=src .venv/bin/python scripts/admit_gtm_socially_case_v2.py --intake /absolute/path/socially-(razrtech)-named-review-intake-v2.json",
    }
    closure_cards = [email_card, buffer_card, flodesk_card, postbridge_card, parqet_card, spendbase_card, barn2_card, rightmessage_card, socially_card]
    one_review_away = sum(
        card["prepared_gate_count"] == 10 and card["gate_count"] == 11 for card in closure_cards
    )
    payload = {
        "schema": "ProofLaunchGTMCaseFunnelOperationalProgressV2",
        "formal_target": target,
        "formal_admitted_count": admitted.get("formal_candidate_quota_credit", 0),
        "formal_gap": target - admitted.get("formal_candidate_quota_credit", 0),
        "public_lead_count": discovery["unique_discovery_lead_count"],
        "provisionally_routed_lead_count": discovery["provisionally_routed_lead_count"],
        "review_packet_count": unified["review_packet_count"],
        "machine_ready_for_named_review_count": unified["machine_ready_for_named_review_count"],
        "admission_acceleration_task_count": queue["task_count"],
        "p0_high_transparency_count": queue["priority_lane_counts"]["p0_high_transparency"],
        "p0_triaged_count": one_review_away + 1,
        "p0_blocked_count": 1,
        "one_named_review_away_count": one_review_away,
        "p0_machine_closure": _progress(one_review_away, queue["priority_lane_counts"]["p0_high_transparency"]),
        "progress_lenses": {
            "public_discovery_coverage": _progress(discovery["unique_discovery_lead_count"], target),
            "review_packet_coverage": _progress(unified["review_packet_count"], target),
            "machine_ready_coverage": _progress(unified["machine_ready_for_named_review_count"], target),
            "ten_of_eleven_closure_coverage": _progress(one_review_away, target),
            "formal_admission_coverage": _progress(admitted.get("formal_candidate_quota_credit", 0), target),
        },
        "stages": stages,
        "closure_cards": closure_cards,
        "operational_headline": {
            "acquired_public_leads": discovery["unique_discovery_lead_count"],
            "machine_ready_reviews": unified["machine_ready_for_named_review_count"],
            "one_named_review_away": one_review_away,
            "p0_machine_closure": f'{one_review_away}/{queue["priority_lane_counts"]["p0_high_transparency"]}',
            "p0_triage": f'{one_review_away + 1}/{queue["priority_lane_counts"]["p0_high_transparency"]}',
            "formal_after_named_admission": admitted.get("formal_candidate_quota_credit", 0),
        },
        "metric_policy": {
            "0_over_16200_is_formally_correct": admitted.get("formal_candidate_quota_credit", 0) == 0,
            "0_over_16200_is_not_a_complete_operational_status": True,
            "discovery_review_and_machine_ready_counts_must_remain_visible": True,
            "nonadmitted_work_may_not_be_relabeled_as_formal_candidates": True,
            "formal_zero_must_not_be_used_as_the_sole_progress_headline": True,
        },
        "truth_boundary": "The formal numerator remains strict, but the operational view must expose acquisition, routing, review, machine readiness, and the exact final gate. This prevents both fabricated credit and the false impression that no work exists.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(EVIDENCE_OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    cards = "".join(
        f'<article><b>{row["count"]:,}</b><span>{html.escape(row["label"])}</span><small>{html.escape(row["credit_semantics"])}</small></article>'
        for row in stages
    )
    closure_sections = "".join(
        f'''<section class="hot"><p>{html.escape(card["company"])} · 闭环卡</p><div class="gate">{card["prepared_gate_count"]}/{card["gate_count"]}</div><p>{card["captured_source_count"]} 个公开来源、{card["independent_source_count"]} 个独立结果面、六项成本、主体、episode 与去重已绑定；只剩实名检查原文并确认。</p><a href="{html.escape(card["named_review_page"], quote=True)}">打开 {html.escape(card["company"])} 实名复核页 →</a><h3>复核后服务器命令</h3><code>{html.escape(card["post_review_command"])}</code></section>'''
        for card in closure_cards
    )
    lenses = payload["progress_lenses"]
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GTM Case Funnel</title><style>
body{{margin:0;background:#0b1020;color:#f5f7ff;font:15px/1.55 ui-sans-serif,system-ui}}main{{max-width:1120px;margin:0 auto;padding:50px 24px}}h1{{font-size:42px;line-height:1.08;max-width:900px}}.sub{{color:#aab6d3;max-width:900px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:32px 0}}article,section{{border:1px solid #293655;background:#111a31;border-radius:18px;padding:22px}}article b{{font-size:34px;display:block}}article span{{display:block;font-weight:700}}small{{color:#8fa0c8}}.hot{{border-color:#4b7dff;background:linear-gradient(135deg,#152348,#111a31)}}.gate{{font-size:54px;font-weight:800}}a{{color:white;background:#356dff;text-decoration:none;padding:12px 17px;border-radius:10px;display:inline-block;font-weight:750}}code{{display:block;white-space:pre-wrap;background:#09101f;padding:13px;border-radius:10px;color:#b9c8ed}}.meter{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}}.meter div{{padding:18px;border:1px solid #30436b;border-radius:14px;background:#101a32}}.meter b{{display:block;font-size:28px}}.warning{{border-left:4px solid #ffb44b;padding-left:14px}}@media(max-width:760px){{.grid,.meter{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main><p>ProofLaunch · 运营进度与赛制入账分开</p><h1>P0 已完成 10/10 证据裁决：9 个到 10/11，1 个预算证据不足被阻断。</h1><p class="sub">可签收闭环率 {one_review_away}/{payload["p0_high_transparency_count"]}（{payload["p0_machine_closure"]["percent"]:.0f}%），不是 0 进度。全量漏斗同时保留：{lenses["public_discovery_coverage"]["percent"]:.2f}% 已发现，{lenses["review_packet_coverage"]["percent"]:.2f}% 已成复核包，{lenses["machine_ready_coverage"]["percent"]:.2f}% 已机器就绪。</p><div class="meter"><div><b>{payload["public_lead_count"]:,}</b>公开线索</div><div><b>{payload["review_packet_count"]:,}</b>实名复核包</div><div><b>{payload["machine_ready_for_named_review_count"]:,}</b>机器就绪</div><div><b>{payload["one_named_review_away_count"]}</b>案例已到 10/11</div></div><p class="sub warning">正式入库层暂为 {payload["formal_admitted_count"]:,}/{target:,}，只表示实名人类逐源检查并通过服务器准入的数量。它不是生产进度主指标，未签收数据也不会冒充正式案例。</p><section><h2>Automatio · 9/11 blocker</h2><p>{html.escape(automatio_blocker["truth_boundary"])}</p><code>{html.escape(automatio_blocker["admission_status"])}</code></section><p><a href="../gtm-seven-case-batch-review-v2/index.html">先批量复核 7 案 →</a></p><div class="grid">{cards}</div>{closure_sections}</main></body></html>'''
    WEB_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(WEB_OUTPUT, page)
    print(json.dumps({
        "evidence": str(EVIDENCE_OUTPUT),
        "web": str(WEB_OUTPUT),
        "formal_admitted_count": payload["formal_admitted_count"],
        "machine_ready_for_named_review_count": payload["machine_ready_for_named_review_count"],
        "one_named_review_away_count": payload["one_named_review_away_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
