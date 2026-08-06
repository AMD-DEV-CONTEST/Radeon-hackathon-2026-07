from __future__ import annotations

from html import escape
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_evidence_funnel_v2 import (
    FUNNEL_TARGETS,
    verify_case_evidence_funnel_coverage,
    verify_case_evidence_funnel_standard,
)
from .gtm_case_identity_resolution_v2 import verify_case_identity_resolution
from .gtm_mechanism_review_queue_v2 import verify_mechanism_review_queue
from .gtm_wave1_discovery_leads_v2 import verify_wave1_discovery_leads


SCHEMA = "ProofLaunchGTMCoverageDashboardManifestV2"


class GTMCoverageDashboardError(ValueError):
    pass


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _digest_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    )


def _percentage(value: int, target: int) -> float:
    return round(100.0 * value / target, 4) if target else 0.0


def build_coverage_dashboard(
    standard: Mapping[str, Any],
    coverage: Mapping[str, Any],
    discovery: Mapping[str, Any],
    identity: Mapping[str, Any],
    mechanism_queue: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    verify_case_evidence_funnel_standard(standard)
    verify_case_evidence_funnel_coverage(coverage)
    verify_wave1_discovery_leads(discovery)
    verify_case_identity_resolution(identity)
    verify_mechanism_review_queue(mechanism_queue)
    if coverage.get("standard_sha256") != standard.get("content_sha256"):
        raise GTMCoverageDashboardError("coverage is not bound to the supplied standard")

    coverage_rows = coverage.get("subvertical_coverage", [])
    if len(coverage_rows) != 81:
        raise GTMCoverageDashboardError("dashboard requires all 81 subvertical rows")
    global_counts = dict(coverage["global_funnel_counts"])
    global_targets = dict(standard["global_funnel_targets"])
    rows = []
    for row in coverage_rows:
        counts = dict(row["funnel_counts"])
        funnel_gaps = dict(row["funnel_gaps"])
        marginal_gaps = row.get("marginal_quota_gaps", {})
        rows.append({
            "subvertical_id": row["subvertical_id"],
            "business_model": row["business_model"],
            "vertical": row["vertical"],
            "subvertical": row["subvertical"],
            "status": row["status"],
            "candidate_count": counts["structured_candidates"],
            "candidate_target": FUNNEL_TARGETS["structured_candidates"],
            "mechanism_count": counts["mechanism_deep_audits"],
            "mechanism_target": FUNNEL_TARGETS["mechanism_deep_audits"],
            "outcome_count": counts["outcome_cross_verifications"],
            "outcome_target": FUNNEL_TARGETS["outcome_cross_verifications"],
            "blueprint_count": counts["execution_case_blueprints"],
            "blueprint_target": FUNNEL_TARGETS["execution_case_blueprints"],
            "candidate_gap": funnel_gaps.get("structured_candidates", 0),
            "mechanism_gap": funnel_gaps.get("mechanism_deep_audits", 0),
            "outcome_gap": funnel_gaps.get("outcome_cross_verifications", 0),
            "blueprint_gap": funnel_gaps.get("execution_case_blueprints", 0),
            "marginal_gap_dimension_count": len(marginal_gaps),
            "marginal_gap_bucket_count": sum(len(value) for value in marginal_gaps.values()),
        })

    dashboard_data = {
        "schema": "ProofLaunchGTMCoverageDashboardDataV2",
        "global_status": coverage["global_status"],
        "completion_claim_allowed": coverage["completion_claim_allowed"],
        "complete_subvertical_count": coverage["complete_subvertical_count"],
        "coverage_gap_subvertical_count": coverage["coverage_gap_subvertical_count"],
        "global_counts": global_counts,
        "global_targets": global_targets,
        "global_percentages": {
            key: _percentage(global_counts[key], global_targets[key]) for key in global_targets
        },
        "discovery_leads": {
            "total": discovery["lead_count"],
            "captured": discovery["captured_lead_count"],
            "capture_gaps": discovery["source_capture_gap_count"],
            "quota_credit": 0,
        },
        "identity_resolution": {
            "records": identity["record_count"],
            "unique_entities": identity["unique_entity_count"],
            "unique_episodes": identity["unique_episode_count"],
            "exact_mirrors": identity["exact_mirror_count"],
            "fuzzy_reviews": identity["fuzzy_review_count"],
        },
        "mechanism_review": {
            "pending": mechanism_queue["pending_human_review_count"],
            "quota_credit": mechanism_queue["mechanism_quota_credit"],
        },
        "rows": rows,
    }
    embedded = json.dumps(dashboard_data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    title = "ProofLaunch · GTM Evidence Coverage V2"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'none'">
  <title>{escape(title)}</title>
  <style>
    :root{{--bg:#07110f;--panel:#0d1b18;--ink:#effff9;--muted:#9ab4aa;--line:#28443b;--mint:#69e7b0;--amber:#f6c86b;--danger:#ff846f;--blue:#79b9ff}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 15% 0%,#15362c 0,transparent 34%),var(--bg);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    main{{max-width:1500px;margin:auto;padding:32px}} h1{{font-size:clamp(30px,4vw,58px);line-height:1;margin:0 0 12px;letter-spacing:-.04em}} h2{{font-size:17px;margin:0}} p{{color:var(--muted)}}
    .eyebrow{{color:var(--mint);font-weight:800;letter-spacing:.14em;text-transform:uppercase}} .truth{{display:inline-flex;gap:9px;align-items:center;background:#3d1a17;color:#ffd9d2;border:1px solid #7a342c;border-radius:999px;padding:8px 12px;font-weight:800}}
    .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:24px 0}} .card{{background:linear-gradient(145deg,#10231e,#0a1714);border:1px solid var(--line);border-radius:18px;padding:18px;min-height:132px}} .metric{{font-size:32px;font-weight:850;letter-spacing:-.04em;margin:8px 0 2px}} .meta{{font-size:12px;color:var(--muted)}}
    progress{{width:100%;height:9px;border:0;margin-top:12px}} progress::-webkit-progress-bar{{background:#173028;border-radius:99px}} progress::-webkit-progress-value{{background:linear-gradient(90deg,var(--mint),var(--blue));border-radius:99px}}
    .controls{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:10px;margin:20px 0}} input,select{{width:100%;background:#0c1a17;color:var(--ink);border:1px solid var(--line);border-radius:11px;padding:12px}}
    .table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:18px;background:#091512}} table{{border-collapse:collapse;width:100%;min-width:1120px}} th,td{{text-align:left;padding:12px 14px;border-bottom:1px solid #1c342d;white-space:nowrap}} th{{position:sticky;top:0;background:#12241f;color:#cfe9df;font-size:12px;letter-spacing:.04em;text-transform:uppercase}} tr:hover td{{background:#10231e}}
    .badge{{display:inline-block;border-radius:99px;padding:4px 8px;font-size:11px;font-weight:800}} .gap{{background:#40221c;color:#ffd3c8}} .ok{{background:#14382c;color:#aef5d5}} .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}} .zero{{color:var(--danger)}} .small{{font-size:12px;color:var(--muted)}}
    .foot{{display:flex;justify-content:space-between;gap:18px;margin-top:18px;color:var(--muted);font-size:12px}} @media(max-width:900px){{main{{padding:20px}}.grid{{grid-template-columns:1fr 1fr}}.controls{{grid-template-columns:1fr}}}} @media(max-width:560px){{.grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
<main>
  <div class="eyebrow">CoverageCubeV2 · evidence operations</div>
  <h1>81 subverticals. No synthetic completion.</h1>
  <p>Every row is bound to the sealed 200 → 40 → 10 → 5 funnel. Discovery signals and unreviewed drafts remain zero-credit.</p>
  <div class="truth" id="truthState">Completion claim blocked</div>
  <section class="grid" id="metrics" aria-label="Global evidence metrics"></section>
  <section class="card">
    <h2>Operational intake</h2>
    <div class="grid" id="intake" style="margin-bottom:0"></div>
  </section>
  <div class="controls">
    <label><span class="small">Search ID, vertical or subvertical</span><input id="query" type="search" placeholder="manufacturing, beauty, b2b…"></label>
    <label><span class="small">Business model</span><select id="model"><option value="">All</option><option>b2b</option><option>b2c</option></select></label>
    <label><span class="small">Status</span><select id="status"><option value="">All</option><option value="coverage_gap">coverage_gap</option><option value="complete">complete</option></select></label>
  </div>
  <div class="table-wrap"><table><thead><tr><th>Subvertical</th><th>Model</th><th>Status</th><th>Cases</th><th>Deep audits</th><th>Outcomes</th><th>Blueprints</th><th>Quota gaps</th></tr></thead><tbody id="rows"></tbody></table></div>
  <div class="foot"><span id="visibleCount"></span><span>Public signals ≠ causality · vendor cases ≠ independent proof · missing evidence stays a gap</span></div>
</main>
<script id="dashboard-data" type="application/json">{embedded}</script>
<script>
const data=JSON.parse(document.getElementById('dashboard-data').textContent);
const labels={{structured_candidates:'Structured candidates',mechanism_deep_audits:'Mechanism deep audits',outcome_cross_verifications:'Outcome cross-verifications',execution_case_blueprints:'Execution blueprints'}};
document.getElementById('truthState').textContent=data.completion_claim_allowed?'Completion claim allowed':'Completion claim blocked · '+data.coverage_gap_subvertical_count+'/81 subverticals have gaps';
document.getElementById('metrics').innerHTML=Object.keys(labels).map(k=>`<article class="card"><div class="small">${{labels[k]}}</div><div class="metric">${{data.global_counts[k].toLocaleString()}} <span class="small">/ ${{data.global_targets[k].toLocaleString()}}</span></div><div class="meta">${{data.global_percentages[k].toFixed(4)}}% verified</div><progress max="${{data.global_targets[k]}}" value="${{data.global_counts[k]}}"></progress></article>`).join('');
const intake=[['Captured discovery leads',data.discovery_leads.captured+' / '+data.discovery_leads.total,'zero candidate credit'],['Pending mechanism reviews',data.mechanism_review.pending,'zero audit credit'],['Unique candidate episodes',data.identity_resolution.unique_episodes,'of '+data.identity_resolution.records+' identity records'],['Duplicate review load',data.identity_resolution.exact_mirrors+' exact · '+data.identity_resolution.fuzzy_reviews+' fuzzy','mirrors never count twice']];
document.getElementById('intake').innerHTML=intake.map(x=>`<article class="card"><div class="small">${{x[0]}}</div><div class="metric">${{x[1]}}</div><div class="meta">${{x[2]}}</div></article>`).join('');
const q=document.getElementById('query'),model=document.getElementById('model'),status=document.getElementById('status'),tbody=document.getElementById('rows');
function render(){{const needle=q.value.trim().toLowerCase();const visible=data.rows.filter(r=>(!needle||[r.subvertical_id,r.vertical,r.subvertical].join(' ').toLowerCase().includes(needle))&&(!model.value||r.business_model===model.value)&&(!status.value||r.status===status.value));tbody.innerHTML=visible.map(r=>`<tr><td><div>${{r.subvertical.replaceAll('_',' ')}}</div><div class="small mono">${{r.subvertical_id}}</div></td><td>${{r.business_model.toUpperCase()}}</td><td><span class="badge ${{r.status==='complete'?'ok':'gap'}}">${{r.status}}</span></td><td class="${{r.candidate_count?'':'zero'}}">${{r.candidate_count}} / ${{r.candidate_target}} <span class="small">(−${{r.candidate_gap}})</span></td><td class="${{r.mechanism_count?'':'zero'}}">${{r.mechanism_count}} / ${{r.mechanism_target}}</td><td class="${{r.outcome_count?'':'zero'}}">${{r.outcome_count}} / ${{r.outcome_target}}</td><td class="${{r.blueprint_count?'':'zero'}}">${{r.blueprint_count}} / ${{r.blueprint_target}}</td><td>${{r.marginal_gap_dimension_count}} dimensions · ${{r.marginal_gap_bucket_count}} buckets</td></tr>`).join('');document.getElementById('visibleCount').textContent=visible.length+' of 81 subverticals visible';}}
[q,model,status].forEach(el=>el.addEventListener('input',render));render();
</script>
</body>
</html>
"""
    html_bytes = html.encode("utf-8")
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "coverage_sha256": coverage["content_sha256"],
        "discovery_sha256": discovery["content_sha256"],
        "identity_sha256": identity["content_sha256"],
        "mechanism_queue_sha256": mechanism_queue["content_sha256"],
        "subvertical_row_count": len(rows),
        "completion_claim_allowed": coverage["completion_claim_allowed"],
        "html_sha256": _digest_bytes(html_bytes),
        "truth_boundary": "The dashboard renders sealed counts and gaps; it cannot alter evidence or grant quota credit.",
    }
    manifest["content_sha256"] = _digest(manifest)
    return html, manifest


def verify_coverage_dashboard(html: str, manifest: Mapping[str, Any]) -> None:
    unsigned = dict(manifest)
    supplied = unsigned.pop("content_sha256", None)
    if manifest.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCoverageDashboardError("dashboard manifest seal is invalid")
    if manifest.get("subvertical_row_count") != 81:
        raise GTMCoverageDashboardError("dashboard does not cover all 81 subverticals")
    if manifest.get("html_sha256") != _digest_bytes(html.encode("utf-8")):
        raise GTMCoverageDashboardError("dashboard HTML hash drifted")
    required = (
        "Completion claim blocked", "CoverageCubeV2", "dashboard-data",
        "Public signals ≠ causality", "81 subverticals",
    )
    if any(token not in html for token in required):
        raise GTMCoverageDashboardError("dashboard truth or interaction contract is incomplete")
    if "http://" in html or "https://" in html:
        raise GTMCoverageDashboardError("dashboard unexpectedly depends on a remote resource")


__all__ = [
    "GTMCoverageDashboardError",
    "build_coverage_dashboard",
    "verify_coverage_dashboard",
]
