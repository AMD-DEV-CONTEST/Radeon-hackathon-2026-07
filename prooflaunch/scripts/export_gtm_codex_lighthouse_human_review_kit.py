#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_codex_lighthouse_portfolio import (  # noqa: E402
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)


PORTFOLIO_PATH = ROOT / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
QUALITY_PATH = ROOT / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/codex-lighthouse-human-review-kit-v1"
KIT_SCHEMA = "ProofLaunchCodexLighthouseHumanReviewKitV1"
REVIEW_SCHEMA = "ProofLaunchCodexLighthouseHumanReviewV1"
PRIVATE_MAPPING_SCHEMA = "ProofLaunchCodexLighthousePrivateMappingV1"
REVIEWER_COUNT = 5
DIMENSIONS = (
    "strategy_quality",
    "platform_native_copy",
    "originality",
    "audience_fit",
    "evidence_discipline",
    "execution_coherence",
)
ATTESTATION = (
    "I independently reviewed the complete source-hidden case without model, author, "
    "other-reviewer, or private-mapping information. My answers are my own human judgment."
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def _review_candidate(candidate: Mapping[str, Any], blind_case_id: str) -> dict[str, Any]:
    allowed = (
        "selector",
        "fixture",
        "campaign_system",
        "channel_decision",
        "platform_assets",
        "email",
        "seo_page",
        "geo_answer",
        "video_script",
        "experiment",
        "truth_boundary",
    )
    payload = {key: candidate[key] for key in allowed}
    return {
        "blind_case_id": blind_case_id,
        "candidate_content_sha256": candidate["content_sha256"],
        "case": payload,
    }


def _pretty(value: object) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2), quote=False)


def _case_html(row: Mapping[str, Any], index: int) -> str:
    case = row["case"]
    fixture = case["fixture"]
    selector = case["selector"]
    campaign = case["campaign_system"]
    assets = case["platform_assets"]
    dimensions = "".join(
        f'<label>{html.escape(dimension.replace("_", " ").title())}'
        f'<select data-score="{dimension}" required><option value="">Score 1–5</option>'
        + "".join(f'<option value="{score}">{score}</option>' for score in range(1, 6))
        + "</select></label>"
        for dimension in DIMENSIONS
    )
    asset_blocks = "".join(
        "<article class=\"asset\">"
        f"<h4>{html.escape(asset['surface_id'])} · {html.escape(asset['native_format'])}</h4>"
        f"<p><strong>Audience state</strong><br>{html.escape(asset['audience_state'])}</p>"
        f"<p><strong>Hook</strong><br>{html.escape(asset['hook'])}</p>"
        f"<pre>{html.escape(asset['full_copy'])}</pre>"
        f"<p><strong>CTA</strong><br>{html.escape(asset['cta'])}</p>"
        f"<p><strong>Proof boundary</strong><br>{html.escape(asset['proof_and_limitation'])}</p>"
        "</article>"
        for asset in assets
    )
    return f"""
<section class="case" data-case-index="{index}" data-case-id="{html.escape(row['blind_case_id'])}" data-candidate-sha="{html.escape(row['candidate_content_sha256'])}">
  <div class="case-head"><span>Case {index + 1}</span><code>{html.escape(row['blind_case_id'])}</code></div>
  <h2>{html.escape(campaign['name'])}</h2>
  <p class="meta">{html.escape(selector['business_model'])} · {html.escape(selector['industry_archetype'])} · {html.escape(selector['lifecycle'])} · {html.escape(selector['budget'])}</p>
  <div class="grid">
    <article><h3>Frozen brief</h3><p><strong>Product</strong><br>{html.escape(fixture['product_name'])}</p><p><strong>Audience</strong><br>{html.escape(fixture['audience'])}</p><p><strong>JTBD</strong><br>{html.escape(fixture['jtbd'])}</p><p><strong>Approved claim</strong><br>{html.escape(fixture['approved_claim'])}</p></article>
    <article><h3>Campaign system</h3><p><strong>Human tension</strong><br>{html.escape(campaign['human_tension'])}</p><p><strong>Category enemy</strong><br>{html.escape(campaign['category_enemy'])}</p><p><strong>Organizing idea</strong><br>{html.escape(campaign['organizing_idea'])}</p><p><strong>Falsifier</strong><br>{html.escape(campaign['falsifier'])}</p></article>
  </div>
  <h3>Platform-native execution</h3>{asset_blocks}
  <details><summary>Email · SEO · GEO · 15-second video · experiment</summary><pre>{_pretty({key: case[key] for key in ('email', 'seo_page', 'geo_answer', 'video_script', 'experiment')})}</pre></details>
  <p class="boundary">{html.escape(case['truth_boundary'])}</p>
  <fieldset class="review"><legend>Independent quality verdict</legend><div class="scores">{dimensions}</div>
    <label>Directly publishable after required legal/brand approval?<select data-field="directly_publishable" required><option value="">Choose</option><option value="true">Yes</option><option value="false">No</option></select></label>
    <label>Requires major creative rework?<select data-field="major_rework" required><option value="">Choose</option><option value="true">Yes</option><option value="false">No</option></select></label>
    <label>Blocking defect<select data-field="blocking_defect" required><option value="">Choose</option><option value="none">None</option><option value="strategy">Strategy</option><option value="platform">Platform fit</option><option value="copy">Copy/craft</option><option value="proof">Proof/claim</option><option value="legal">Legal/privacy</option><option value="other">Other</option></select></label>
    <label>Located rationale (40+ chars)<textarea data-field="rationale" minlength="40" required></textarea></label>
    <label>Strongest element (20+ chars)<textarea data-field="strongest_element" minlength="20" required></textarea></label>
    <label>First repair, if any (20+ chars; write “No repair recommended …” when none)<textarea data-field="first_repair" minlength="20" required></textarea></label>
  </fieldset>
</section>"""


def _reviewer_html(slot: int, rows: list[dict[str, Any]]) -> str:
    cases = "".join(_case_html(row, index) for index, row in enumerate(rows))
    state = {
        "schema": REVIEW_SCHEMA,
        "kit_schema": KIT_SCHEMA,
        "reviewer_slot": slot,
        "attestation": ATTESTATION,
        "dimensions": list(DIMENSIONS),
        "expected_case_count": len(rows),
    }
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source-hidden GTM lighthouse review · reviewer {slot}</title>
<style>
:root{{--ink:#17211d;--muted:#5c6862;--paper:#f5f1e8;--card:#fffdf7;--line:#d8d0c1;--accent:#c64f2f;--green:#315f4b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 ui-sans-serif,system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px 100px}}header,.case{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:28px;margin-bottom:24px;box-shadow:0 12px 32px #3d332416}}h1{{font-size:clamp(2rem,5vw,4rem);line-height:1;margin:.2em 0}}h2{{font-size:2rem;margin:.3em 0}}h3{{margin-top:1.4em}}code,.meta{{color:var(--muted)}}.case-head{{display:flex;justify-content:space-between;color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.08em}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}article,.asset,fieldset,details{{border:1px solid var(--line);border-radius:12px;padding:18px;margin:12px 0;background:#fff}}pre{{white-space:pre-wrap;font:15px/1.55 ui-monospace,SFMono-Regular,monospace}}.boundary{{border-left:5px solid var(--accent);padding:12px 16px;background:#fff1e9}}.scores{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}label{{display:grid;gap:6px;margin:12px 0;font-weight:650}}select,textarea,input{{font:inherit;padding:10px;border:1px solid #a89e90;border-radius:8px;background:white}}textarea{{min-height:88px}}button{{font:inherit;font-weight:800;padding:14px 22px;border:0;border-radius:999px;background:var(--green);color:white;cursor:pointer}}#status{{font-weight:700;margin-left:12px}}.protocol{{max-width:78ch}}
</style></head><body><main>
<header><p>ProofLaunch · source-hidden human craft gate</p><h1>Eight complete GTM cases.<br>One independent verdict each.</h1><p class="protocol">Judge the actual last-mile work, not feature presence. A high score requires a coherent strategic choice, native platform craft, meaningful originality, audience truth, disciplined claims, and a campaign system that can survive handoff. This is not a comparison against a named-product baseline and cannot establish a PK win or market effect.</p>
<label>Stable reviewer ID<input id="reviewer" minlength="3" autocomplete="off" placeholder="e.g. reviewer-chen-01"></label>
<label><input id="attest" type="checkbox"> {html.escape(ATTESTATION)}</label>
<label><input id="conflict" type="checkbox"> I disclosed conflicts and have no undisclosed commercial, authorship, or evaluation conflict.</label></header>
{cases}
<button id="export">Validate and download local review JSON</button><span id="status" role="status"></span>
</main><script>
const STATE={json.dumps(state, ensure_ascii=False)};
const bool=v=>v==='true';
const canonical=v=>Array.isArray(v)?v.map(canonical):(v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v);
document.getElementById('export').onclick=async()=>{{try{{
 const reviewer=document.getElementById('reviewer').value.trim();
 if(reviewer.length<3||!document.getElementById('attest').checked||!document.getElementById('conflict').checked)throw Error('Complete reviewer ID and both attestations.');
 const reviews=[];
 for(const root of document.querySelectorAll('.case')){{
  const scores={{}};for(const dim of STATE.dimensions){{const v=root.querySelector(`[data-score="${{dim}}"]`).value;if(!v)throw Error(`Complete every score in ${{root.dataset.caseId}}.`);scores[dim]=Number(v)}}
  const read=name=>root.querySelector(`[data-field="${{name}}"]`).value.trim();
  const directly=read('directly_publishable'),major=read('major_rework'),defect=read('blocking_defect'),rationale=read('rationale'),strongest=read('strongest_element'),repair=read('first_repair');
  if(!directly||!major||!defect||rationale.length<40||strongest.length<20||repair.length<20)throw Error(`Complete the full verdict in ${{root.dataset.caseId}}.`);
  if(bool(directly)&&bool(major))throw Error(`${{root.dataset.caseId}} cannot be directly publishable and major rework.`);
  reviews.push({{blind_case_id:root.dataset.caseId,candidate_content_sha256:root.dataset.candidateSha,scores,directly_publishable:bool(directly),major_rework:bool(major),blocking_defect:defect,rationale,strongest_element:strongest,first_repair:repair}})
 }}
 const payload={{schema:STATE.schema,kit_schema:STATE.kit_schema,reviewer_slot:STATE.reviewer_slot,reviewer_pseudonym:reviewer,human_attestation:STATE.attestation,independent_attestation:true,conflict_disclosed:true,reviewed_at:new Date().toISOString(),reviews}};
 const bytes=new TextEncoder().encode(JSON.stringify(canonical(payload)));payload.review_payload_sha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
 const blob=new Blob([JSON.stringify(payload,null,2)+'\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`prooflaunch-lighthouse-reviewer-${{String(STATE.reviewer_slot).padStart(2,'0')}}.json`;a.click();URL.revokeObjectURL(a.href);document.getElementById('status').textContent='Downloaded locally. Nothing transmitted or promoted.';
}}catch(error){{document.getElementById('status').textContent='Blocked: '+error.message}}}};
</script></body></html>"""


def export(output: Path) -> dict[str, Any]:
    portfolio = _load(PORTFOLIO_PATH)
    quality = _load(QUALITY_PATH)
    verify_lighthouse_portfolio(portfolio)
    verify_lighthouse_quality_portfolio(quality, portfolio=portfolio)
    if portfolio.get("candidate_count") != 8 or quality.get("level_1_pass_count") != 8:
        raise SystemExit("review kit requires exactly eight Level-1-passing lighthouse candidates")

    if output.exists():
        shutil.rmtree(output)
    public = output / "public"
    private = output / "private"
    public.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)

    candidates = list(portfolio["candidates"])
    mapping_rows: list[dict[str, Any]] = []
    blind_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        blind_id = f"case-{index:02d}"
        mapping_rows.append({
            "blind_case_id": blind_id,
            "candidate_id": candidate["candidate_id"],
            "candidate_content_sha256": candidate["content_sha256"],
        })
        blind_rows.append(_review_candidate(candidate, blind_id))

    mapping = {
        "schema": PRIVATE_MAPPING_SCHEMA,
        "source_portfolio_sha256": portfolio["content_sha256"],
        "rows": mapping_rows,
        "truth_boundary": "Private deblinding map. Do not expose it to reviewers before all reviews are frozen.",
    }
    mapping["content_sha256"] = _digest(mapping)
    atomic_write_text(private / "blind-case-mapping.json", json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")

    for slot in range(1, REVIEWER_COUNT + 1):
        ordered = list(blind_rows)
        random.Random(f"prooflaunch-lighthouse-reviewer-{slot}").shuffle(ordered)
        atomic_write_text(public / f"reviewer-{slot:02d}.html", _reviewer_html(slot, ordered))

    atomic_write_text(
        output / "README.md",
        "# ProofLaunch source-hidden lighthouse review kit V1\n\n"
        "Give each reviewer only their assigned file under `public/`. Keep `private/` hidden until all five local JSON reviews are frozen. "
        "No page transmits data, publishes content, or claims a named-product win, 4A quality, market effect, conversion, or revenue lift.\n",
    )
    files = []
    for path in sorted(p for p in output.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "schema": KIT_SCHEMA,
        "source_portfolio_sha256": portfolio["content_sha256"],
        "source_quality_audit_sha256": quality["content_sha256"],
        "candidate_count": 8,
        "reviewer_count": REVIEWER_COUNT,
        "expected_human_review_count": 8 * REVIEWER_COUNT,
        "submitted_human_review_count": 0,
        "qualified_human_review_count": 0,
        "dimensions": list(DIMENSIONS),
        "human_attestation": ATTESTATION,
        "identity_hidden_from_reviewers": True,
        "private_mapping_separate": True,
        "network_submission_enabled": False,
        "automatic_publish_enabled": False,
        "named_product_pk_completed_count": 0,
        "production_effect_observed_count": 0,
        "four_a_claim_eligible": False,
        "files": files,
        "truth_boundary": "This kit enables human craft review of eight synthetic Codex-workspace candidates. Zero human reviews are present at export; it is not named-product comparison, market-effect evidence, or release approval.",
    }
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    public_archive = output / "prooflaunch-codex-lighthouse-reviewer-pages-v1.zip"
    with zipfile.ZipFile(public_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.write(output / "README.md", "README.md")
        for path in sorted(p for p in public.rglob("*") if p.is_file()):
            bundle.write(path, path.relative_to(output))

    archive = output / "prooflaunch-codex-lighthouse-coordinator-kit-v1.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(
            p
            for p in output.rglob("*")
            if p.is_file() and p not in {archive, public_archive}
        ):
            bundle.write(path, path.relative_to(output))
    receipt = {
        "schema": "ProofLaunchCodexLighthouseHumanReviewKitExportReceiptV1",
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "coordinator_archive_sha256": sha256_file(archive),
        "coordinator_archive_bytes": archive.stat().st_size,
        "reviewer_archive_sha256": sha256_file(public_archive),
        "reviewer_archive_bytes": public_archive.stat().st_size,
        "reviewer_archive_contains_private_mapping": False,
        "candidate_count": 8,
        "expected_human_review_count": 40,
        "submitted_human_review_count": 0,
        "network_calls": 0,
        "automatic_external_actions": 0,
    }
    atomic_write_text(output / "export-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the source-hidden Codex lighthouse human-review kit.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    receipt = export(args.output.resolve())
    print(json.dumps({"output": str(args.output.resolve()), **receipt}, ensure_ascii=False))


if __name__ == "__main__":
    main()
