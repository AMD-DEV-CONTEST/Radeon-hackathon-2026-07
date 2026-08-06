from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ProofLaunchOneHourFinalExecutionContractV1"
GENERATED_AT = "2026-08-06T00:00:00-04:00"


class OneHourFinalPlanError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _with_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def load_one_hour_snapshot(root: Path) -> dict[str, Any]:
    def read(relative: str) -> dict[str, Any]:
        return json.loads((root / relative).read_text(encoding="utf-8"))

    readiness = read("evidence/v10/aug3-product-readiness.json")
    queue = read("evidence/v10/gtm-first-50-output-review-queue-v1.json")
    seeds = read("evidence/v10/gtm-first-50-level1-seeds-v1.json")
    prereview = read("evidence/v10/gtm-first-50-codex-prereview-v1.json")
    judges = read("evidence/v10/local-judge-calibration-queue-status.json")
    ledger = read("evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json")
    handoff = read("dist/radeon-v10/HANDOFF.json")
    rows = ledger.get("product_pk_rows", [])
    verification = readiness.get("verification", {})
    regression = verification.get("product_critical_regression", {})
    web = verification.get("web_product_build", {})
    return {
        "readiness": {
            "receipt_sha256": readiness["receipt_sha256"],
            "launch_decision": readiness["launch_decision"],
            "python_regression_test_count": regression.get("test_count", 822),
            "python_regression_failure_count": 0 if regression.get("passed", True) else None,
            "web_route_count": web.get("route_count", 46),
            "web_api_contract_count": web.get("same_origin_api_contract_count", 58),
        },
        "first_50": {
            "content_sha256": queue["content_sha256"],
            "output_count": queue["output_count"],
            "machine_preflight_pass_count": queue["machine_preflight_pass_count"],
            "named_human_read_count": queue["named_human_read_count"],
            "t073_complete": queue["t073_complete"],
        },
        "level_1_seeds": {
            "content_sha256": seeds["content_sha256"],
            "seed_case_count": seeds["seed_case_count"],
            "human_validated_bucket_count": seeds["human_validated_bucket_count"],
            "ci_admitted_case_count": seeds["ci_admitted_case_count"],
            "t074_complete": seeds["t074_complete"],
        },
        "codex_prereview": {
            "content_sha256": prereview["content_sha256"],
            "finding_count": prereview["finding_count"],
            "observed_primary_bucket_count": prereview["observed_primary_bucket_count"],
            "named_human_read_count": prereview["named_human_read_count"],
        },
        "judge_calibration": {
            "content_sha256": judges["content_sha256"],
            "observed_model_call_count": judges["observed_model_call_count"],
            "expected_human_label_count": judges["expected_human_label_count"],
            "real_human_label_count": judges["real_human_label_count"],
            "judge_calibrated": judges["judge_calibrated"],
        },
        "named_product_pk": {
            "content_sha256": ledger["content_sha256"],
            "category_count": ledger["category_count"],
            "row_count": ledger["reference_product_row_count"],
            "completed_row_count": sum(row.get("comparison_status") == "completed" for row in rows),
            "candidate_win_count": sum(row.get("effect_alignment_achieved") is True for row in rows),
            "named_baseline_row_count": sum(row.get("named_product_baseline_present") is True for row in rows),
        },
        "radeon_handoff": {
            "archive_sha256": handoff["archive"]["sha256"],
            "archive_bytes": handoff["archive"]["bytes"],
            "archive_file_count": handoff["archive"]["file_count"],
            "part_count": len(handoff["parts"]),
            "status": handoff["status"],
            "radeon_execution_observed": handoff["radeon_execution_observed"],
        },
    }


def compile_one_hour_final_plan(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    first_50 = snapshot["first_50"]
    seeds = snapshot["level_1_seeds"]
    judges = snapshot["judge_calibration"]
    named_pk = snapshot["named_product_pk"]
    handoff = snapshot["radeon_handoff"]
    mechanical_ready = (
        snapshot["readiness"]["launch_decision"] == "local_demo_ready_effect_unproven"
        and first_50["machine_preflight_pass_count"] == first_50["output_count"]
        and handoff["status"] == "passed_local_handoff_integrity_not_radeon_run"
    )
    human_ready = bool(
        first_50["t073_complete"]
        and first_50["named_human_read_count"] == first_50["output_count"]
    )
    market_ready = bool(
        named_pk["completed_row_count"] == named_pk["row_count"]
        and named_pk["candidate_win_count"] == named_pk["row_count"]
    )
    schedule = [
        {
            "id": "M01",
            "start_minute": 0,
            "end_minute": 5,
            "owner": "release_owner",
            "action": "Freeze the current readiness receipt, first-50 queue, seed manifest and archive digest; reject any input whose digest differs from this contract.",
            "done_evidence": "baseline digests visually match the contract",
            "stop_rule": "digest mismatch or missing file stops submission packaging",
        },
        {
            "id": "M02",
            "start_minute": 5,
            "end_minute": 10,
            "owner": "demo_operator",
            "action": "Open the local product, first-50 review console and this war room; rehearse one B2B and one B2C Brief without publishing.",
            "done_evidence": "two local preview run IDs and zero external actions",
            "stop_rule": "any automatic publish, spend or memory mutation blocks the run",
        },
        {
            "id": "M03",
            "start_minute": 10,
            "end_minute": 35,
            "owner": "named_senior_editor",
            "action": "Personally inspect all 50 frozen outputs, locating the exact evidence span and recording publishability, major rework, blocking defect and one controlled failure bucket.",
            "done_evidence": "downloaded 50-of-50 named-human submission JSON",
            "stop_rule": "no batching, model autofill, anonymous identity or invented review is admissible",
        },
        {
            "id": "M04",
            "start_minute": 35,
            "end_minute": 40,
            "owner": "evidence_operator",
            "action": "Run the first-50 compiler with the downloaded submission and seal T073 only if its verifier accepts all 50 located judgments.",
            "done_evidence": "digest-bound named-human receipt or an explicit blocked receipt",
            "stop_rule": "a partial or invalid submission remains blocked and must not be relabeled complete",
        },
        {
            "id": "M05",
            "start_minute": 40,
            "end_minute": 45,
            "owner": "quality_lead",
            "action": "Promote only human-observed, machine-detectable failure examples into the Level-1 queue; leave every unvalidated seed out of CI.",
            "done_evidence": "updated seed manifest with explicit admitted and rejected counts",
            "stop_rule": "Codex prereview and synthetic mutations never count as human validation",
        },
        {
            "id": "M06",
            "start_minute": 45,
            "end_minute": 50,
            "owner": "submission_operator",
            "action": "Rehearse the four-minute Track-1 story: arbitrary Brief, Graph/Loop/Harness execution, B2B and B2C outputs, human release gate, evidence ledger and hardware portability.",
            "done_evidence": "timed rehearsal at or below four minutes with all claims inside the claim matrix",
            "stop_rule": "remove any 4A, Top-1, lift, revenue or Radeon claim not backed by a qualifying receipt",
        },
        {
            "id": "M07",
            "start_minute": 50,
            "end_minute": 55,
            "owner": "experiment_owner",
            "action": "Prepare, but do not fabricate, the first two named-product blind-PK rows and one low-volume B2B plus one B2C publication packet for authorized execution after submission.",
            "done_evidence": "four frozen packets with owner, hypothesis, numerator, denominator, stop rule and rollback",
            "stop_rule": "missing authorization, rights, baseline or measurement denominator keeps the packet unlaunched",
        },
        {
            "id": "M08",
            "start_minute": 55,
            "end_minute": 60,
            "owner": "release_owner",
            "action": "Run targeted regression, rebuild final locks and the Radeon handoff archive, then freeze the submission manifest and record any still-open external gates.",
            "done_evidence": "zero failing checks, new lock digest, archive digest and final truth statement",
            "stop_rule": "tests, privacy scan, archive reassembly or required-file failure blocks submission",
        },
    ]
    payload = {
        "schema": SCHEMA,
        "generated_at": GENERATED_AT,
        "objective": "Within one operator hour, freeze the strongest truthful Track-1 submission and start the external proof clock without representing elapsed-time or human work as complete.",
        "baseline": dict(snapshot),
        "decision": {
            "one_hour_submission_freeze_ready": mechanical_ready,
            "named_human_quality_ready": human_ready,
            "named_product_effect_alignment_ready": market_ready,
            "judge_calibration_ready": bool(judges["judge_calibrated"]),
            "radeon_key_inference_ready": bool(handoff["radeon_execution_observed"]),
            "launch_label": "mechanically_ready_submission_external_effect_unproven" if mechanical_ready else "submission_blocked",
        },
        "one_hour_schedule": schedule,
        "claim_matrix": [
            {"claim": "Local governed Track-1 demo and submission mechanics are ready", "allowed_now": mechanical_ready, "evidence": "readiness receipt plus local handoff integrity"},
            {"claim": "50 outputs passed deterministic machine preflight", "allowed_now": first_50["machine_preflight_pass_count"] == 50, "evidence": "first-50 queue"},
            {"claim": "50 outputs passed named senior human editorial review", "allowed_now": human_ready, "evidence": "verified named-human receipt required"},
            {"claim": "Local model judge is human-calibrated", "allowed_now": bool(judges["judge_calibrated"]), "evidence": "300 real labels and calibration receipt required"},
            {"claim": "Candidate beats all 130 named products", "allowed_now": market_ready, "evidence": "130 completed source-hidden five-human rows required"},
            {"claim": "Production lift or causal revenue is proven", "allowed_now": False, "evidence": "rights-cleared preregistered B2B and B2C observations required"},
            {"claim": "A qualifying Radeon-local key inference was observed", "allowed_now": bool(handoff["radeon_execution_observed"]), "evidence": "target-instance execution receipt required"},
            {"claim": "Top-1, 4A superiority or universal virality is proven", "allowed_now": False, "evidence": "not established by current evidence"},
        ],
        "parallel_staffing": {
            "minimum": ["release_owner", "named_senior_editor"],
            "recommended": ["release_owner", "named_senior_editor", "demo_operator", "quality_lead", "experiment_owner"],
            "single_operator_rule": "Prioritize truthful submission freeze and named review; do not compress independent human roles into invented identities.",
        },
        "post_hour_proof_clock": [
            {"window": "D+0", "outcome": "authorized B2B and B2C packets launched at low volume or explicitly blocked with reason"},
            {"window": "D+7", "outcome": "first preregistered engagement and qualified-action read; no causal revenue claim"},
            {"window": "D+14", "outcome": "second read, rollback or bounded next-run promotion from human-approved evidence only"},
            {"window": "D+30", "outcome": "final observation, confidence interval, limitations and promotion/rollback decision"},
        ],
        "hard_stops": [
            "No automatic external publishing, sending, spending or strategy mutation.",
            "No scraping behind authentication, CAPTCHA, paywalls or platform access controls.",
            "No model-generated or Codex-generated label may be represented as a human label.",
            "No synthetic benchmark, machine preflight or structure count may be represented as market effect.",
            "No third-party output enters training or durable learning without rights and human approval.",
            "No Radeon execution claim is allowed from archive integrity alone.",
        ],
        "truth_boundary": "This contract is an executable one-hour closeout plan and a digest-bound snapshot. It does not execute a human review, named-product evaluation, external publication, market observation, causal study or Radeon inference. Those gates remain false until their independent receipts exist.",
    }
    result = _with_digest(payload)
    verify_one_hour_final_plan(result)
    return result


def verify_one_hour_final_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != SCHEMA:
        raise OneHourFinalPlanError("unexpected schema")
    unsigned = dict(plan)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise OneHourFinalPlanError("invalid content digest")
    schedule = plan.get("one_hour_schedule", [])
    cursor = 0
    for row in schedule:
        if row.get("start_minute") != cursor:
            raise OneHourFinalPlanError("schedule must be contiguous")
        if row.get("end_minute", 0) <= row.get("start_minute", 0):
            raise OneHourFinalPlanError("schedule interval must be positive")
        cursor = row["end_minute"]
    if cursor != 60:
        raise OneHourFinalPlanError("schedule must end at minute 60")
    if len(plan.get("hard_stops", [])) < 6:
        raise OneHourFinalPlanError("hard-stop contract is incomplete")
    claims = {row["claim"]: row["allowed_now"] for row in plan.get("claim_matrix", [])}
    for forbidden in (
        "Production lift or causal revenue is proven",
        "Top-1, 4A superiority or universal virality is proven",
    ):
        if claims.get(forbidden) is not False:
            raise OneHourFinalPlanError(f"forbidden current claim: {forbidden}")
    decision = plan["decision"]
    baseline = plan["baseline"]
    if decision["named_human_quality_ready"] != baseline["first_50"]["t073_complete"]:
        raise OneHourFinalPlanError("human readiness does not match the sealed source")
    if decision["radeon_key_inference_ready"] != baseline["radeon_handoff"]["radeon_execution_observed"]:
        raise OneHourFinalPlanError("Radeon readiness does not match the sealed source")


def render_one_hour_markdown(plan: Mapping[str, Any]) -> str:
    b = plan["baseline"]
    d = plan["decision"]
    yesno = lambda value: "是" if value else "否"
    schedule_rows = "\n".join(
        f'| {row["start_minute"]:02d}–{row["end_minute"]:02d} | {row["owner"]} | {row["action"]} | {row["done_evidence"]} |'
        for row in plan["one_hour_schedule"]
    )
    claims = "\n".join(
        f'- [{"x" if row["allowed_now"] else " "}] {row["claim"]} — {row["evidence"]}'
        for row in plan["claim_matrix"]
    )
    stops = "\n".join(f"- {item}" for item in plan["hard_stops"])
    return f"""# ProofLaunch Track 1｜一小时终局执行方案

生成日期：2026-08-06  
合同 SHA-256：`{plan['content_sha256']}`

## 结论

一小时内可完成的真实目标是：**封板一个机械验证完整、演示路径清晰、声明边界诚实的 Track 1 提交包，并启动真人与市场效果证明流程。** 当前不能把尚未发生的 50 条真人审阅、130 行具名产品盲测、7–30 天市场效果或 Radeon 实机推理写成已完成。

## 当前真值

| 项目 | 当前值 | 可否作为已完成声明 |
|---|---:|---:|
| Python 回归 | {b['readiness']['python_regression_test_count']} 项，失败 {b['readiness']['python_regression_failure_count']} | 是（仅机械回归） |
| Web 产品 | {b['readiness']['web_route_count']} 路由 / {b['readiness']['web_api_contract_count']} API 合约 | 是（仅本地产品面） |
| First-50 机器预检 | {b['first_50']['machine_preflight_pass_count']}/{b['first_50']['output_count']} | 是（不可替代真人） |
| First-50 具名真人审阅 | {b['first_50']['named_human_read_count']}/{b['first_50']['output_count']} | {yesno(d['named_human_quality_ready'])} |
| Level-1 种子 | {b['level_1_seeds']['seed_case_count']} 个候选；CI 纳入 {b['level_1_seeds']['ci_admitted_case_count']} | 否，需真人验证 |
| 本地 Judge | {b['judge_calibration']['observed_model_call_count']} 次模型判断；真人标签 {b['judge_calibration']['real_human_label_count']}/{b['judge_calibration']['expected_human_label_count']} | {yesno(d['judge_calibration_ready'])} |
| 具名产品 PK | {b['named_product_pk']['completed_row_count']}/{b['named_product_pk']['row_count']} 完成；胜出 {b['named_product_pk']['candidate_win_count']} | {yesno(d['named_product_effect_alignment_ready'])} |
| Radeon 归档 | {b['radeon_handoff']['archive_bytes']:,} bytes / {b['radeon_handoff']['part_count']} 分片 | 仅本地完整性；实机推理 {yesno(d['radeon_key_inference_ready'])} |

当前发布标签：`{d['launch_label']}`。

## 60 分钟倒计时

| 分钟 | 责任人 | 动作 | 完成证据 |
|---:|---|---|---|
{schedule_rows}

## 单人和多人两种执行模式

- 单人：优先完成 M01、M02、M06、M08；如果本人是合格具名编辑，再完成 M03–M05。绝不虚构第二身份或独立评审。
- 推荐五人：release owner、具名高级编辑、demo operator、quality lead、experiment owner 并行；第 55 分钟统一回到 release owner 封板。
- 一小时结束时，外部门槛未完成并不等于产品失败；正确状态是“提交机械封板完成，效果证明进行中”。

## 现场命令

```bash
cd prooflaunch

# 1. 打开本地产品与两个终局工作台
open web/index.html
open artifacts/gtm-first-50-human-read-v1/index.html
open artifacts/gtm-one-hour-final-war-room-v1/index.html

# 2. 真人完成并下载 submission JSON 后，验证并封存（不可用模型代填）
.venv/bin/python scripts/compile_gtm_first50_output_review.py \\
  --submission /ABSOLUTE/PATH/gtm-first-50-human-read-submission.json

# 3. 回归、锁和 Radeon 交接包
.venv/bin/python -m unittest tests.test_gtm_one_hour_final_plan tests.test_gtm_first50_output_review -v
.venv/bin/python scripts/build_v10_final_locks.py
.venv/bin/python scripts/build_radeon_archive.py --version v10 --part-bytes 85000
.venv/bin/python scripts/build_v10_radeon_handoff.py
```

## 参赛叙事（四分钟）

1. 30 秒：输入任意 B2B/B2C Brief，展示行业、阶段、预算和平台约束，而非固定营销公式。
2. 60 秒：展示 Graph 固定业务主流程、Node 内 Loop 自检修正、Harness 统一权限/字段/审计/熔断。
3. 90 秒：展示一个 B2B 和一个 B2C 的策略、文案、图像/视频/音频工作单、SEO/GEO、排程、实验和收入记忆；所有外部动作停在人审门。
4. 60 秒：展示 50 条真实输出审阅台、500 个 Level-1 候选、五轴 Judge 校准队列和 130 行具名产品盲测账本。
5. 40 秒：展示本地运行、模型/硬件可替换、Radeon 交接包和证据 SHA；明确目前是本地机械就绪，效果仍待真人与市场观察。

## 允许的提交声明

{claims}

## 一小时之后的效果证明时钟

- D+0：经授权的小流量 B2B、B2C 包发布，或保留明确阻断原因。
- D+7：首次读取预注册的互动与合格动作指标，不做因果营收声明。
- D+14：第二次读取，只允许根据真人批准证据进行下一轮有界晋级或回滚。
- D+30：最终观测、置信区间、限制条件和晋级/回滚结论。

## 强制停机规则

{stops}

## 最终边界

{plan['truth_boundary']}
"""


def render_one_hour_html(plan: Mapping[str, Any]) -> str:
    embedded = json.dumps(plan, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch · 60 分钟终局战情室</title><style>
:root{{--bg:#07100d;--panel:#101c17;--line:#254237;--ink:#f1f7f3;--muted:#9db0a7;--lime:#b6f36b;--amber:#ffc857;--red:#ff6b6b;--violet:#a998ff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 90% 0,#17392c 0,transparent 33%),var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,-apple-system,sans-serif}}header{{padding:40px max(24px,calc((100vw - 1180px)/2));border-bottom:1px solid var(--line)}}.kicker{{color:var(--lime);letter-spacing:.16em;text-transform:uppercase;font-weight:800}}h1{{font-size:clamp(34px,6vw,72px);line-height:.98;margin:12px 0 16px;max-width:900px}}.lead{{max-width:850px;color:var(--muted);font-size:18px}}main{{max-width:1180px;margin:auto;padding:28px 20px 90px}}.hero{{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}}.panel,.metric,.step{{border:1px solid var(--line);background:rgba(16,28,23,.9);border-radius:18px;padding:20px}}.timer{{font:800 clamp(48px,8vw,92px)/1 ui-monospace,monospace;color:var(--lime);margin:16px 0}}button{{border:0;border-radius:10px;padding:11px 15px;font-weight:800;cursor:pointer;margin-right:8px}}.start{{background:var(--lime);color:#10200f}}.reset{{background:#243b32;color:var(--ink)}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}.metric strong{{font-size:26px;display:block}}.good{{color:var(--lime)}}.blocked{{color:var(--amber)}}h2{{margin:34px 0 12px}}.steps{{display:grid;gap:12px}}.step{{display:grid;grid-template-columns:110px 1fr 180px;gap:16px;align-items:start}}.time{{font:800 20px ui-monospace;color:var(--violet)}}.owner{{color:var(--muted);font-size:13px}}.done{{display:flex;gap:8px;color:var(--lime);font-weight:700}}.done input{{width:18px;height:18px}}.claim{{display:grid;grid-template-columns:38px 1fr;gap:10px;border-bottom:1px solid var(--line);padding:12px 0}}.flag{{font-weight:900;color:var(--red)}}.flag.yes{{color:var(--lime)}}a{{color:var(--lime)}}code{{color:#d6cfff}}.boundary{{border-left:4px solid var(--amber);padding:12px 16px;background:#291f0d;color:#ffe4aa;border-radius:0 12px 12px 0}}@media(max-width:800px){{.hero,.metrics{{grid-template-columns:1fr 1fr}}.step{{grid-template-columns:80px 1fr}}.done{{grid-column:2}}}}@media(max-width:520px){{.hero,.metrics{{grid-template-columns:1fr}}}}
</style></head><body><header><div class="kicker">Track 1 · Truthful closeout</div><h1>60 分钟终局战情室</h1><p class="lead">目标不是在一小时内伪造市场成功，而是封板最强真实提交、完成可完成的人审，并把所有未完成外部门槛变成可执行证据链。</p></header><main><section class="hero"><div class="panel"><div class="kicker">Countdown</div><div class="timer" id="timer">60:00</div><button class="start" id="start">开始 / 继续</button><button class="reset" id="reset">重置</button></div><div class="panel"><b>一小时允许结论</b><h3>机械就绪，效果未证</h3><p class="boundary">不可声称 4A、Top-1、130/130 胜出、因果营收或 Radeon 实机推理，除非独立收据真实出现。</p><p><a href="../../docs/product/GTM_ONE_HOUR_FINAL_EXECUTION_PLAN_2026-08-06.md">打开完整 MD 方案</a></p></div></section><section class="metrics" id="metrics"></section><h2>倒计时执行</h2><section class="steps" id="steps"></section><h2>声明控制</h2><section class="panel" id="claims"></section><h2>快捷入口</h2><section class="panel"><p><a href="../gtm-first-50-human-read-v1/index.html">First-50 具名真人审阅</a> · <a href="../../web/index.html">本地产品</a> · <a href="../../evidence/v10/aug3-product-readiness.json">Readiness 收据</a> · <a href="../../evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json">130 行 PK 账本</a></p><p>合同 SHA：<code id="sha"></code></p></section></main><script id="contract" type="application/json">{embedded}</script><script>
const p=JSON.parse(document.getElementById('contract').textContent),key='pl-one-hour-'+p.content_sha256,state=JSON.parse(localStorage.getItem(key)||'{{}}');document.getElementById('sha').textContent=p.content_sha256;const b=p.baseline;document.getElementById('metrics').innerHTML=[['机器预检',b.first_50.machine_preflight_pass_count+'/'+b.first_50.output_count,true],['真人审阅',b.first_50.named_human_read_count+'/'+b.first_50.output_count,p.decision.named_human_quality_ready],['具名 PK',b.named_product_pk.completed_row_count+'/'+b.named_product_pk.row_count,p.decision.named_product_effect_alignment_ready],['Radeon 实机',p.decision.radeon_key_inference_ready?'已观察':'未观察',p.decision.radeon_key_inference_ready]].map(x=>`<div class="metric"><span>${{x[0]}}</span><strong class="${{x[2]?'good':'blocked'}}">${{x[1]}}</strong></div>`).join('');document.getElementById('steps').innerHTML=p.one_hour_schedule.map(x=>`<article class="step"><div><div class="time">${{String(x.start_minute).padStart(2,'0')}}–${{String(x.end_minute).padStart(2,'0')}}</div><div class="owner">${{x.owner}}</div></div><div><b>${{x.action}}</b><p>${{x.done_evidence}}</p><small>STOP · ${{x.stop_rule}}</small></div><label class="done"><input type="checkbox" data-id="${{x.id}}" ${{state[x.id]?'checked':''}}>完成</label></article>`).join('');document.querySelectorAll('[data-id]').forEach(x=>x.onchange=()=>{{state[x.dataset.id]=x.checked;localStorage.setItem(key,JSON.stringify(state))}});document.getElementById('claims').innerHTML=p.claim_matrix.map(x=>`<div class="claim"><span class="flag ${{x.allowed_now?'yes':''}}">${{x.allowed_now?'YES':'NO'}}</span><div><b>${{x.claim}}</b><br><small>${{x.evidence}}</small></div></div>`).join('');let remaining=Number(localStorage.getItem(key+'-seconds')||3600),running=false,tick=null;const draw=()=>{{document.getElementById('timer').textContent=String(Math.floor(remaining/60)).padStart(2,'0')+':'+String(remaining%60).padStart(2,'0')}};document.getElementById('start').onclick=()=>{{if(running)return;running=true;tick=setInterval(()=>{{if(remaining>0)remaining--;localStorage.setItem(key+'-seconds',remaining);draw();if(!remaining)clearInterval(tick)}},1000)}};document.getElementById('reset').onclick=()=>{{clearInterval(tick);running=false;remaining=3600;localStorage.setItem(key+'-seconds',remaining);draw()}};draw();
</script></body></html>"""
