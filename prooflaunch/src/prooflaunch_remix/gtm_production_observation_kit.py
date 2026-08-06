from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import zipfile
from typing import Mapping


class ProductionObservationKitError(ValueError):
    """The field kit could not be bound to an approved experiment contract."""


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _csv_template() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "arm",
            "eligible_reach",
            "qualified_actions",
            "evidence_engagements",
            "complaints",
            "conversions",
            "revenue_usd",
            "spend_usd",
        )
    )
    writer.writerow(("candidate", "", "", "", "", "", "", ""))
    writer.writerow(("baseline", "", "", "", "", "", "", ""))
    return output.getvalue().encode("utf-8")


def compile_aggregate_attribution_plan(
    *,
    run_id: str,
    campaign_id: str,
    experiment_id: str,
    strategy_plan_sha256: str,
    attribution: Mapping[str, object],
) -> dict[str, object]:
    required = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
    values: dict[str, str] = {}
    for key in required:
        value = attribution.get(key)
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ProductionObservationKitError(f"attribution.{key} is invalid")
        values[key] = value

    def arm_tags(arm: str) -> dict[str, str]:
        suffix = f"-{arm}"
        content = values["utm_content"][: 128 - len(suffix)] + suffix
        return {
            "utm_source": values["utm_source"],
            "utm_medium": values["utm_medium"],
            "utm_campaign": values["utm_campaign"],
            "utm_content": content,
            "pl_experiment": experiment_id,
            "pl_arm": arm,
            "pl_run": run_id,
        }

    core: dict[str, object] = {
        "schema": "ProofLaunchAggregateAttributionPlanV1",
        "run_id": run_id,
        "campaign_id": campaign_id,
        "experiment_id": experiment_id,
        "strategy_plan_sha256": strategy_plan_sha256,
        "arms": {
            "candidate": arm_tags("candidate"),
            "baseline": arm_tags("baseline"),
        },
        "event_taxonomy": [
            {"event_name": "pl_eligible_reach", "aggregate_metric": "eligible_reach"},
            {"event_name": "pl_qualified_action", "aggregate_metric": "qualified_actions"},
            {"event_name": "pl_evidence_engagement", "aggregate_metric": "evidence_engagements"},
            {"event_name": "pl_complaint", "aggregate_metric": "complaints"},
            {"event_name": "pl_conversion", "aggregate_metric": "conversions"},
        ],
        "required_event_dimensions": [
            "pl_experiment",
            "pl_arm",
            "channel",
            "occurred_at",
        ],
        "aggregate_export_dimensions": [
            "experiment_id",
            "arm",
            "channel",
            "window_start",
            "window_end",
        ],
        "finance_reconciliation_fields": ["revenue_usd", "spend_usd"],
        "deduplication_contract": {
            "performed_upstream": True,
            "first_party_ephemeral_deduplication_key_allowed": True,
            "deduplication_key_exported_to_prooflaunch": False,
        },
        "prohibited_export_fields": [
            "name",
            "email",
            "phone",
            "address",
            "user_id",
            "device_id",
            "cookie_id",
            "ip_address",
            "fingerprint",
            "raw_comment",
            "transcript",
            "creative_body",
        ],
        "tracking_pixel_included": False,
        "person_level_export_allowed": False,
        "cross_site_identity_resolution_allowed": False,
        "automatic_external_submission_enabled": False,
        "randomization_claim": (
            "Arm tags identify exposure groups but do not establish random assignment; "
            "randomized_controlled may be selected only when the external assignment "
            "mechanism was actually randomized and separately audited."
        ),
    }
    plan = dict(core)
    plan["attribution_plan_sha256"] = hashlib.sha256(_json_bytes(core)).hexdigest()
    return plan


def _attribution_tags_csv(plan: Mapping[str, object]) -> bytes:
    arms = plan.get("arms")
    if not isinstance(arms, Mapping):
        raise ProductionObservationKitError("attribution plan arms are missing")
    columns = (
        "arm",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "pl_experiment",
        "pl_arm",
        "pl_run",
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for arm in ("candidate", "baseline"):
        tags = arms.get(arm)
        if not isinstance(tags, Mapping):
            raise ProductionObservationKitError(f"attribution plan {arm} arm is missing")
        writer.writerow((arm, *(str(tags[column]) for column in columns[1:])))
    return output.getvalue().encode("utf-8")


def _capture_html(contract: Mapping[str, object]) -> bytes:
    contract_json = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).replace("</", "<\\/")
    title = html.escape(str(contract["campaign_id"]))
    zero_budget = "true" if contract["zero_budget"] is True else "false"
    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src data: blob:; media-src 'none'; form-action 'none'; base-uri 'none'">
  <title>ProofLaunch production observation field kit</title>
  <style>
    :root{color-scheme:dark;--bg:#090b10;--panel:#121722;--line:#293247;--ink:#f7f8fb;--muted:#aab4c8;--accent:#88f0c2;--warn:#ffcc7a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}main{max-width:1080px;margin:auto;padding:32px 20px 64px}h1{font-size:clamp(30px,5vw,58px);line-height:1;margin:.2em 0}h2{margin-top:0}.eyebrow{letter-spacing:.13em;text-transform:uppercase;color:var(--accent);font-size:12px}.boundary{color:var(--muted);max-width:76ch}.binding,.panel{border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:20px;margin:18px 0}.binding{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.binding span{display:block;color:var(--muted);font-size:12px}.binding code{overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.arms{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}fieldset{border:1px solid var(--line);border-radius:12px;padding:14px}label{display:grid;gap:6px;color:var(--muted)}input,select,button{font:inherit}input,select{width:100%;background:#090d15;color:var(--ink);border:1px solid #39445d;border-radius:8px;padding:10px}.check{display:flex;align-items:center;gap:9px}.check input{width:auto}button{border:0;border-radius:999px;padding:12px 18px;background:var(--accent);color:#07110d;font-weight:750;cursor:pointer}button:disabled{opacity:.45}.status{min-height:24px;color:var(--warn)}.small{font-size:12px;color:var(--muted)}
  </style>
</head>
<body><main>
  <p class="eyebrow">Offline · aggregate-only · human submitted</p>
  <h1>Production observation field kit</h1>
  <p class="boundary">Hash an authorized source export locally, enter aggregate counts, and export the exact JSON accepted by ProofLaunch. This page performs no network request, stores no credential, uploads no source file, publishes nothing, and makes no causal or 4A-quality claim.</p>
  <section class="binding">
    <div><span>Campaign</span><strong>__TITLE__</strong></div>
    <div><span>Run</span><code id="run"></code></div>
    <div><span>Experiment</span><code id="experiment"></code></div>
    <div><span>Strategy SHA-256</span><code id="strategy"></code></div>
    <div><span>Attribution plan SHA-256</span><code id="attribution"></code></div>
    <div><span>Budget contract</span><strong id="budget"></strong></div>
    <div><span>Minimum sample</span><strong id="minimum"></strong></div>
  </section>
  <section class="panel"><h2>0 · Apply the frozen arm tags</h2><p class="boundary">Before manual publication, use the exact candidate or baseline row from <code>attribution-tags.csv</code>. The tags label arms only; they do not prove randomization. Export only aggregate dimensions listed in <code>attribution-plan.json</code>.</p></section>
  <form id="observation" class="panel">
    <h2>1 · Bind source and observation window</h2>
    <div class="grid">
      <label>Authorized aggregate source file<input id="source-file" type="file" required></label>
      <label>Local SHA-256<input id="source-sha" pattern="[0-9a-f]{64}" readonly required></label>
      <label>Source kind<select id="source-kind"><option value="first_party_analytics">First-party analytics</option><option value="official_platform_export">Official platform export</option><option value="authorized_manual_entry">Authorized manual entry</option></select></label>
      <label>Channel<input id="channel" value="__CHANNEL__" maxlength="128" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,127}" required></label>
      <label>Assignment<select id="assignment"><option value="observational">Observational attribution</option><option value="randomized_controlled">Randomized controlled</option></select></label>
      <label>Window start<input id="window-start" type="datetime-local" required></label>
      <label>Window end<input id="window-end" type="datetime-local" required></label>
    </div>
    <h2>2 · Enter aggregate metrics</h2>
    <div class="arms">
      <fieldset><legend>Candidate</legend><div id="candidate" class="grid"></div></fieldset>
      <fieldset><legend>Comparable baseline</legend><div id="baseline" class="grid"></div></fieldset>
    </div>
    <div class="grid" style="margin-top:16px">
      <label class="check"><input id="deduplicated" type="checkbox" required>Dataset was deduplicated</label>
      <label class="check"><input id="bot-filter" type="checkbox" required>Bot filtering was applied</label>
    </div>
    <p class="small">The source file is read only to calculate SHA-256 in this browser tab. It is never embedded in the exported JSON.</p>
    <button type="submit">Export observation JSON</button>
    <p id="status" class="status" role="status"></p>
  </form>
  <section class="panel"><h2>3 · Human-controlled submission</h2><p class="boundary">Inspect the JSON, then submit it through the authenticated product UI or the documented API. The server revalidates every field, the strategy binding, sample floor, deduplication, bot filtering, observation window and zero-budget rule.</p></section>
  <script id="contract" type="application/json">__CONTRACT__</script>
  <script>
  (()=>{"use strict";
    const contract=JSON.parse(document.getElementById("contract").textContent);
    const metricSpec=[
      ["eligible_reach","Eligible reach",1,"1"],
      ["qualified_actions","Qualified actions",0,"1"],
      ["evidence_engagements","Evidence engagements",0,"1"],
      ["complaints","Complaints",0,"1"],
      ["conversions","Conversions",0,"1"],
      ["revenue_usd","Revenue USD",0,"0.01"],
      ["spend_usd","Spend USD",0,"0.01"]
    ];
    const byId=(id)=>document.getElementById(id);
    byId("run").textContent=contract.run_id;byId("experiment").textContent=contract.experiment_id;byId("strategy").textContent=contract.strategy_plan_sha256;byId("attribution").textContent=contract.attribution_plan_sha256;byId("budget").textContent=contract.budget_contract;byId("minimum").textContent=String(contract.registered_minimum_sample);
    for(const arm of ["candidate","baseline"]){const root=byId(arm);for(const [key,label,min,step] of metricSpec){const wrapper=document.createElement("label");wrapper.textContent=label;const input=document.createElement("input");input.id=`${arm}-${key}`;input.type="number";input.min=String(min);input.step=step;input.required=true;if(key==="spend_usd"&&contract.zero_budget){input.value="0";input.readOnly=true}wrapper.append(input);root.append(wrapper)}}
    const hex=(buffer)=>Array.from(new Uint8Array(buffer),byte=>byte.toString(16).padStart(2,"0")).join("");
    byId("source-file").addEventListener("change",async(event)=>{const file=event.target.files?.[0];byId("source-sha").value="";if(!file)return;byId("status").textContent="Hashing locally…";byId("source-sha").value=hex(await crypto.subtle.digest("SHA-256",await file.arrayBuffer()));byId("status").textContent=`Source bound locally · ${file.size} bytes · file not uploaded.`});
    const metric=(arm)=>{const out={};for(const [key] of metricSpec){const value=Number(byId(`${arm}-${key}`).value);if(!Number.isFinite(value)||value<0)throw new Error(`${arm}.${key} is invalid`);out[key]=key.endsWith("_usd")?value:Math.trunc(value)}if(out.eligible_reach<1)throw new Error(`${arm}.eligible_reach must be positive`);for(const key of ["qualified_actions","evidence_engagements","complaints","conversions"]){if(out[key]>out.eligible_reach)throw new Error(`${arm}.${key} exceeds eligible reach`)}return out};
    const utc=(value)=>{const date=new Date(value);if(Number.isNaN(date.valueOf()))throw new Error("observation window is invalid");return date.toISOString()};
    const download=(name,value)=>{const blob=new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"});const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)};
    byId("observation").addEventListener("submit",(event)=>{event.preventDefault();try{if(!event.currentTarget.checkValidity()){event.currentTarget.reportValidity();return}const metrics=metric("candidate");const baseline=metric("baseline");if(__ZERO_BUDGET__&&(metrics.spend_usd!==0||baseline.spend_usd!==0))throw new Error("zero-budget contract requires spend_usd=0");const start=utc(byId("window-start").value);const end=utc(byId("window-end").value);if(new Date(end)<=new Date(start))throw new Error("window end must be after start");const id=`obs-${crypto.randomUUID().replaceAll("-","").slice(0,24)}`;const payload={observation_id:id,experiment_id:contract.experiment_id,strategy_plan_sha256:contract.strategy_plan_sha256,source_kind:byId("source-kind").value,source_reference_sha256:byId("source-sha").value,channel:byId("channel").value.trim(),window_start:start,window_end:end,assignment_method:byId("assignment").value,metrics,baseline_metrics:baseline,deduplicated:byId("deduplicated").checked,bot_filter_applied:byId("bot-filter").checked};download(`${id}.json`,payload);byId("status").textContent="Observation JSON exported. Human inspection and authenticated submission remain required."}catch(error){byId("status").textContent=`Blocked: ${error.message}`}});
  })();
  </script>
</main></body></html>'''
    return (
        template.replace("__CONTRACT__", contract_json)
        .replace("__TITLE__", title)
        .replace("__CHANNEL__", html.escape(str(contract["attribution_source"])))
        .replace("__ZERO_BUDGET__", zero_budget)
        .encode("utf-8")
    )


def compile_production_observation_field_kit(
    *,
    run_id: str,
    campaign_id: str,
    product_name: str,
    experiment: Mapping[str, object],
    strategy_plan_sha256: str,
    budget_contract: str,
    generated_at: str,
) -> tuple[bytes, dict[str, object]]:
    """Compile a deterministic, credential-free field kit for real aggregate evidence."""

    for name, value in (("run_id", run_id), ("campaign_id", campaign_id)):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ProductionObservationKitError(f"{name} is invalid")
    if not isinstance(product_name, str) or not product_name.strip() or len(product_name) > 256:
        raise ProductionObservationKitError("product_name is invalid")
    if not _SHA256.fullmatch(strategy_plan_sha256):
        raise ProductionObservationKitError("strategy_plan_sha256 is invalid")
    if not isinstance(experiment, Mapping):
        raise ProductionObservationKitError("experiment must be an object")
    attribution = experiment.get("attribution")
    metrics = experiment.get("metrics")
    if not isinstance(attribution, Mapping) or not isinstance(metrics, list):
        raise ProductionObservationKitError("experiment lacks attribution or metrics")
    experiment_id = attribution.get("experiment_id")
    if not isinstance(experiment_id, str) or not _SAFE_ID.fullmatch(experiment_id):
        raise ProductionObservationKitError("experiment_id is invalid")
    minimum_samples = [
        int(item["minimum_sample"])
        for item in metrics
        if isinstance(item, Mapping)
        and item.get("metric") in {"qualified_action_rate", "evidence_engagement_rate"}
        and type(item.get("minimum_sample")) is int
        and int(item["minimum_sample"]) > 0
    ]
    registered_minimum_sample = max(minimum_samples, default=1)
    zero_budget = budget_contract == "zero"
    attribution_plan = compile_aggregate_attribution_plan(
        run_id=run_id,
        campaign_id=campaign_id,
        experiment_id=experiment_id,
        strategy_plan_sha256=strategy_plan_sha256,
        attribution=attribution,
    )
    binding = {
        "schema": "ProofLaunchProductionObservationFieldBindingV1",
        "run_id": run_id,
        "campaign_id": campaign_id,
        "product_name": product_name.strip(),
        "experiment_id": experiment_id,
        "strategy_plan_sha256": strategy_plan_sha256,
        "attribution_plan_sha256": attribution_plan["attribution_plan_sha256"],
        "attribution_source": attribution["utm_source"],
        "budget_contract": budget_contract,
        "zero_budget": zero_budget,
        "registered_minimum_sample": registered_minimum_sample,
        "registered_metrics": metrics,
        "observation_endpoint": f"/v1/runs/{run_id}/outcomes",
        "economics_endpoint_template": (
            f"/v1/runs/{run_id}/outcomes/{{observation_id}}/economics"
        ),
    }
    observation_template = {
        "observation_id": "replace-with-unique-observation-id",
        "experiment_id": experiment_id,
        "strategy_plan_sha256": strategy_plan_sha256,
        "source_kind": "official_platform_export",
        "source_reference_sha256": "replace-with-lowercase-source-file-sha256",
        "channel": "replace-with-channel-id",
        "window_start": "replace-with-ISO-8601-timezone-aware-start",
        "window_end": "replace-with-ISO-8601-timezone-aware-end",
        "assignment_method": "observational",
        "metrics": {
            "eligible_reach": 0,
            "qualified_actions": 0,
            "evidence_engagements": 0,
            "complaints": 0,
            "conversions": 0,
            "revenue_usd": 0.0,
            "spend_usd": 0.0,
        },
        "baseline_metrics": None,
        "deduplicated": False,
        "bot_filter_applied": False,
    }
    economics_template = {
        "economics_id": "replace-with-unique-economics-id",
        "effect_observation_id": "replace-after-observation-is-recorded",
        "effect_observation_sha256": "replace-with-server-returned-observation-sha256",
        "source_reference_sha256": "replace-with-lowercase-finance-export-sha256",
        "currency": "USD",
        "measurement_basis": "cash_collected",
        "candidate": {
            "conversions": 0,
            "gross_revenue_usd": 0.0,
            "discounts_usd": 0.0,
            "refunds_usd": 0.0,
            "chargebacks_usd": 0.0,
            "variable_cogs_usd": 0.0,
            "fulfillment_cost_usd": 0.0,
            "platform_fees_usd": 0.0,
            "media_spend_usd": 0.0,
            "model_cost_usd": 0.0,
            "operator_cost_usd": 0.0,
            "qualified_pipeline_usd": 0.0,
        },
        "baseline": None,
    }
    readme = f"""# ProofLaunch production observation field kit

This kit is bound to run `{run_id}`, experiment `{experiment_id}`, and strategy
SHA-256 `{strategy_plan_sha256}`. Open `capture.html` locally to hash one authorized
aggregate source export and generate the exact observation JSON. The source file
never leaves the browser and is not included in the JSON.

Before manual publication, apply exactly one row from `attribution-tags.csv` and
retain `attribution-plan.json` with the release receipt. Candidate and baseline
use distinct `utm_content` and `pl_arm` values. These tags identify arms but do
not prove randomized assignment.

Submission remains a human-controlled action. Use the product Experiment Lab, or
POST the reviewed JSON to `{binding['observation_endpoint']}` with tenant bearer,
operator approval and idempotency headers supplied from environment-controlled
secrets. Never paste credentials into this kit.

After the server returns `observation_sha256`, use `economics-template.json` for
the contribution-economics follow-up. Candidate conversions, gross revenue and
media spend must exactly match the recorded observation. Qualified pipeline is
diagnostic and is never counted as revenue.

Hard boundaries: aggregate counts only; no audience identifiers, comments,
transcripts or creative bodies; no automatic publication, spend, strategy
mutation, causal lift claim, annual breakout claim, Top-1 claim or 4A claim.
""".encode("utf-8")
    members: dict[str, bytes] = {
        "README.md": readme,
        "attribution-plan.json": _json_bytes(attribution_plan),
        "attribution-tags.csv": _attribution_tags_csv(attribution_plan),
        "binding.json": _json_bytes(binding),
        "capture.html": _capture_html(binding),
        "economics-template.json": _json_bytes(economics_template),
        "experiment.json": _json_bytes(dict(experiment)),
        "metrics-template.csv": _csv_template(),
        "observation-template.json": _json_bytes(observation_template),
    }
    member_receipts = [
        {
            "path": name,
            "sha256": hashlib.sha256(body).hexdigest(),
            "byte_length": len(body),
        }
        for name, body in sorted(members.items())
    ]
    manifest_core: dict[str, object] = {
        "schema": "ProofLaunchProductionObservationFieldKitV1",
        "generated_at": generated_at,
        "binding": binding,
        "members": member_receipts,
        "source_files_included": False,
        "credentials_included": False,
        "person_level_data_accepted": False,
        "aggregate_attribution_plan_included": True,
        "distinct_candidate_and_baseline_tags_included": True,
        "tracking_pixel_included": False,
        "automatic_submission_executed": False,
        "automatic_external_publish_executed": False,
        "automatic_budget_activation_executed": False,
        "human_submission_required": True,
        "truth_boundary": (
            "This kit operationalizes collection of source-bound aggregate evidence. "
            "It contains no observed production result and proves no lift, revenue "
            "causality, annual breakout, universal quality, Top-1 status or 4A effect."
        ),
    }
    manifest_core["manifest_sha256"] = hashlib.sha256(
        _json_bytes(manifest_core)
    ).hexdigest()
    members["manifest.json"] = _json_bytes(manifest_core)
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, body in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, body)
    return output.getvalue(), manifest_core
