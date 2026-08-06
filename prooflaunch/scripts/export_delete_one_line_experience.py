#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402


EDITORIAL = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-receipt.json"
AUDIT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-quality-audit.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    result["content_sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    return result


def javascript() -> str:
    return r'''const form = document.querySelector('#trial');
const output = document.querySelector('#output');
const claimInput = document.querySelector('#claim');
const evidenceInput = document.querySelector('#evidence');
const sourceInput = document.querySelector('#source');
const populationInput = document.querySelector('#population');
const periodInput = document.querySelector('#period');
const limitationInput = document.querySelector('#limitation');
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const normalize = value => String(value || '').trim().replace(/\s+/g, ' ');
const risky = /\b(viral|guarantee|best|leading|top[- ]?1|convert|conversion|revenue|roi|increase|boost|improve|eliminate|ensure|always|never|any brand|everyone)\b/i;

function evaluateClaim() {
  const claim = normalize(claimInput.value);
  const evidence = normalize(evidenceInput.value);
  const fields = {
    source: normalize(sourceInput.value),
    population: normalize(populationInput.value),
    period: normalize(periodInput.value),
    limitation: normalize(limitationInput.value),
  };
  const checked = [...document.querySelectorAll('[name="witness"]:checked')].map(node => node.value);
  const missing = Object.entries(fields).filter(([, value]) => !value).map(([key]) => key);
  if (!claim) return {verdict:'NO CLAIM ENTERED', className:'neutral', action:'Enter one exact public sentence. The experience cannot audit a slogan it cannot see.', missing:['claim'], checked, claim:'—'};
  if (!evidence && checked.length === 0) return {verdict:'NO WITNESS', className:'reject', action:'Delete this sentence from public proof or label it explicitly as a hypothesis. Do not replace it with a softer unsupported synonym.', missing:['observable evidence', ...missing], checked, claim};
  if (!evidence || missing.length) return {verdict:'WITNESS INCOMPLETE', className:'hold', action:'Hold release. Keep the claim outside public proof until the observation, source, population, period, and material limitation are all reviewable.', missing:[...(!evidence ? ['observable evidence'] : []), ...missing], checked, claim};
  return {verdict:'HUMAN REVIEW REQUIRED', className:'review', action:'The docket is structurally complete enough for a named human review. This is not automated substantiation, legal approval, or evidence that the claim is true.', missing:[], checked, claim};
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const result = evaluateClaim();
  const evidenceState = result.checked.length ? result.checked.join(' · ') : 'none selected';
  output.className = `result ${result.className}`;
  output.hidden = false;
  output.innerHTML = `<div class="verdict"><small>LOCAL VERDICT</small><strong>${escapeHtml(result.verdict)}</strong><p>${escapeHtml(result.action)}</p></div>
    <div class="docket"><div class="before"><small>BEFORE</small><p>${escapeHtml(result.claim)}</p></div>
    <div class="after"><small>RELEASE STATE</small><p>${result.verdict === 'NO WITNESS' ? '<span class="redaction">DELETE FROM PUBLIC PROOF</span>' : escapeHtml(result.verdict)}</p></div>
    <dl><div><dt>Witness class</dt><dd>${escapeHtml(evidenceState)}</dd></div><div><dt>Missing</dt><dd>${escapeHtml(result.missing.join(' · ') || 'none at structural gate')}</dd></div><div><dt>Next owner</dt><dd>named human release reviewer</dd></div></dl></div>`;
  if (!document.body.classList.contains('demo-result')) {
    output.scrollIntoView({behavior:'auto', block:'center'});
  }
});

document.querySelector('#load-example').addEventListener('click', () => {
  claimInput.value = 'An AI GTM employee that makes any brand go viral.';
  evidenceInput.value = '';
  sourceInput.value = '';
  populationInput.value = '';
  periodInput.value = '';
  limitationInput.value = '';
  for (const node of document.querySelectorAll('[name="witness"]')) node.checked = false;
  claimInput.focus();
});

if (new URLSearchParams(location.search).get('demo') === 'no-witness') {
  document.body.classList.add('demo-result');
  requestAnimationFrame(() => form.requestSubmit());
}'''


def html_page(linkedin: dict[str, object], tiktok: dict[str, object], instagram: dict[str, object]) -> str:
    claim = "An AI GTM employee that makes any brand go viral."
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Delete One Line — ProofLaunch Claim Trial</title>
<style>
:root{{--paper:#f2eee4;--ink:#090a08;--acid:#dfff2d;--red:#ff4e38;--blue:#3158ff;--rule:#8e8c84;--muted:#5f605b}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:17px/1.42 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}button,input,textarea{{font:inherit}}.wrap{{width:min(1420px,calc(100% - 40px));margin:auto}}nav{{height:68px;border-bottom:2px solid var(--ink);display:flex;align-items:center;justify-content:space-between;font:900 12px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.09em}}nav span{{color:var(--muted)}}header{{padding:74px 0 68px}}.eyebrow,.label,small,dt{{font:900 12px/1.1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.11em;text-transform:uppercase}}h1{{font-size:clamp(72px,12.8vw,188px);line-height:.76;letter-spacing:-.085em;margin:32px 0 42px;max-width:1390px}}h1 em{{font-style:normal;color:var(--red)}}.intro{{display:grid;grid-template-columns:1.2fr .8fr;gap:44px;align-items:end}}.intro>p{{font-size:clamp(24px,3vw,43px);line-height:1.05;margin:0;max-width:900px}}.redacted{{background:var(--ink);color:white;padding:28px 32px;transform:rotate(-1deg);box-shadow:12px 12px 0 var(--red)}}.redacted small{{color:var(--acid)}}.redacted p{{font-size:26px;line-height:1.12;margin:18px 0 0}}.redacted s{{text-decoration-color:var(--red);text-decoration-thickness:7px}}section{{border-top:2px solid var(--ink);padding:68px 0}}.section-head{{display:grid;grid-template-columns:.85fr 1.15fr;gap:40px;margin-bottom:34px}}h2{{font-size:clamp(52px,7vw,104px);line-height:.82;letter-spacing:-.065em;margin:0}}.section-head p{{font-size:22px;max-width:760px;margin:0}}form{{display:grid;grid-template-columns:1.1fr .9fr;gap:12px}}.claim-field{{grid-column:1/-1;background:var(--ink);color:white;padding:26px}}label{{display:block}}label>span{{display:block;font:900 12px/1 ui-monospace,monospace;letter-spacing:.09em;text-transform:uppercase;margin-bottom:10px}}textarea,input{{width:100%;border:2px solid var(--ink);background:#fff;padding:15px 16px;color:var(--ink)}}.claim-field textarea{{min-height:112px;font-size:26px;font-weight:850;background:#171914;color:white;border-color:#686b62}}.field{{border:2px solid var(--ink);padding:20px;background:#faf7ef}}.field textarea{{min-height:92px}}.witnesses{{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.witnesses label{{border:2px solid var(--ink);background:#fff;padding:18px;font-weight:850;cursor:pointer}}.witnesses input{{width:auto;margin-right:8px}}.actions{{grid-column:1/-1;display:grid;grid-template-columns:2fr 1fr;gap:10px}}button{{border:2px solid var(--ink);min-height:76px;font-weight:950;cursor:pointer}}button[type=submit]{{background:var(--acid);font-size:22px}}button[type=button]{{background:transparent}}button:hover{{background:var(--red);color:var(--ink)}}.result{{display:grid;grid-template-columns:.9fr 1.1fr;gap:12px;margin-top:28px;scroll-margin-top:20px}}.result[hidden]{{display:none}}.verdict,.docket{{border:3px solid var(--ink);padding:30px;min-height:420px}}.verdict{{background:var(--red);display:flex;flex-direction:column}}.verdict strong{{font-size:clamp(58px,7vw,108px);line-height:.78;letter-spacing:-.06em;margin:auto 0;transform:rotate(-2deg)}}.verdict p{{font-size:20px;font-weight:750}}.hold .verdict{{background:#ffb72d}}.review .verdict{{background:var(--acid)}}.neutral .verdict{{background:#ccc9bf}}.docket{{background:white}}.before,.after{{border-bottom:2px solid var(--ink);padding:8px 0 24px;margin-bottom:24px}}.before p,.after p{{font-size:28px;line-height:1.05;font-weight:850;margin:12px 0 0}}.redaction{{background:var(--ink);color:white;padding:5px 9px}}dl{{display:grid;gap:12px}}dl div{{display:grid;grid-template-columns:160px 1fr;border-bottom:1px solid #bbb;padding-bottom:10px}}dt,dd{{margin:0}}.system{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.native{{border:2px solid var(--ink);padding:26px;min-height:360px;display:flex;flex-direction:column}}.native:nth-child(1){{background:var(--acid)}}.native:nth-child(2){{background:var(--blue);color:white}}.native:nth-child(3){{background:var(--red)}}.native h3{{font-size:38px;line-height:.96;letter-spacing:-.04em;margin:28px 0 18px}}.native p{{font-size:18px}}.native .tail{{margin-top:auto;font-weight:850}}.boundary{{font:700 14px/1.5 ui-monospace,SFMono-Regular,monospace;color:#4e4f4a;max-width:1100px}}footer{{padding:34px 0 70px;border-top:2px solid var(--ink);font:850 13px ui-monospace,monospace}}body.demo-result nav,body.demo-result header,body.demo-result #trial,body.demo-result main>section:first-child .section-head,body.demo-result main>section:not(:first-child),body.demo-result footer{{display:none}}body.demo-result main>section:first-child{{border:0;padding:24px 0}}body.demo-result .result{{margin-top:0}}@media(max-width:850px){{.intro,.section-head,form,.result{{grid-template-columns:1fr}}.claim-field,.witnesses,.actions{{grid-column:auto}}.witnesses,.system{{grid-template-columns:1fr}}h1{{font-size:23vw}}.actions{{grid-template-columns:1fr}}}}
</style></head><body><nav class="wrap"><strong>PROOFLAUNCH / CLAIM TRIAL</strong><span>LOCAL · PRIVATE · NO AUTO-PUBLISH</span></nav>
<header><div class="wrap"><div class="eyebrow">THE ZERO-BUDGET LAUNCH IS THE PRODUCT DEMO</div><h1>DELETE<br><em>ONE LINE.</em></h1><div class="intro"><p>Find the homepage sentence you most want buyers to remember. Now ask it for one witness. If none appears, delete the sentence—not your ambition.</p><div class="redacted"><small>THE LINE WE DELETED</small><p><s>{claim}</s></p></div></div></div></header>
<main><section><div class="wrap"><div class="section-head"><h2>Call a witness.</h2><p>Your text stays in this browser. This deterministic gate checks whether the docket is structurally reviewable; it does not decide truth, legality, or publication.</p></div>
<form id="trial"><label class="claim-field"><span>Exact public sentence</span><textarea id="claim">{claim}</textarea></label>
<label class="field"><span>Observable evidence</span><textarea id="evidence" placeholder="What was directly observed? Leave blank to test the unsupported version."></textarea></label>
<label class="field"><span>Authorized source</span><input id="source" placeholder="Report, dataset, study, reconciled record"></label>
<label class="field"><span>Population</span><input id="population" placeholder="Who or what was observed?"></label>
<label class="field"><span>Period</span><input id="period" placeholder="Exact observation window"></label>
<label class="field"><span>Material limitation</span><input id="limitation" placeholder="Where does the evidence stop?"></label>
<div class="witnesses"><label><input type="checkbox" name="witness" value="independent preference">Independent preference</label><label><input type="checkbox" name="witness" value="organic observation">Organic observation</label><label><input type="checkbox" name="witness" value="attributed conversion">Attributed conversion</label><label><input type="checkbox" name="witness" value="reconciled revenue">Reconciled revenue</label></div>
<div class="actions"><button type="submit">PUT THE LINE ON TRIAL →</button><button id="load-example" type="button">RESET THE SELF-TRIAL</button></div></form><div id="output" hidden></div></div></section>
<section><div class="wrap"><div class="section-head"><h2>One act. Three native jobs.</h2><p>The campaign does not paste one caption everywhere. LinkedIn asks for a founder confession, short video makes deletion visible, and Instagram turns the witness rule into a saved diagnostic.</p></div><div class="system">
<article class="native"><small>LINKEDIN / OPERATOR CONFESSION</small><h3>{linkedin['hook']}</h3><p>{linkedin['body'][1]}</p><p class="tail">{linkedin['cta']}</p></article>
<article class="native"><small>SHORT VIDEO / VISIBLE CONFLICT</small><h3>{tiktok['hook']}</h3><p>{tiktok['body'][0]}</p><p class="tail">{tiktok['body'][-1]}</p></article>
<article class="native"><small>INSTAGRAM / SAVEABLE OBJECT</small><h3>{instagram['hook']}</h3><p>{instagram['body'][1]}</p><p class="tail">{instagram['body'][-1]}</p></article>
</div></div></section><section><div class="wrap"><p class="boundary">TRUTH BOUNDARY — This is an original local campaign challenger and deterministic editorial gate. It records no input, sends no network request, publishes nothing, spends nothing, and proves no human preference, organic breakout, conversion, revenue, agency quality, or named-product superiority. A structurally complete docket still requires the appropriate named human and specialist review.</p></div></section></main>
<footer><div class="wrap">DELETE THE CLAIM · KEEP THE HYPOTHESIS · EARN THE WITNESS</div></footer><script src="delete-one-line.js"></script></body></html>'''


def main() -> None:
    editorial = json.loads(EDITORIAL.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if editorial.get("accepted_surface_count") != 13 or audit.get("pre_human_quality_pass_count") != 13:
        raise SystemExit("thirteen platform candidates must pass the pre-human gate")
    candidates = {row["surface_id"]: row for row in editorial["accepted_candidates"]}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html_path = OUTPUT / "index.html"
    js_path = OUTPUT / "delete-one-line.js"
    atomic_write_text(html_path, html_page(candidates["linkedin"], candidates["tiktok"], candidates["instagram"]))
    atomic_write_text(js_path, javascript())
    receipt = seal({
        "schema": "ProofLaunchDeleteOneLineExperienceReceiptV1",
        "source_editorial_receipt_sha256": editorial["content_sha256"],
        "source_quality_audit_sha256": audit["content_sha256"],
        "surface_candidate_count": 13,
        "pre_human_quality_pass_count": 13,
        "files": {
            "index.html": {"sha256": sha256_file(html_path), "bytes": html_path.stat().st_size},
            "delete-one-line.js": {"sha256": sha256_file(js_path), "bytes": js_path.stat().st_size},
        },
        "network_requests_implemented": 0,
        "browser_persistence_implemented": False,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "human_review_count": 0,
        "production_effect_observed": False,
        "truth_boundary": "This receipt proves only a local interactive campaign challenger bound to thirteen pre-human platform drafts. It proves no human preference, publication, organic breakout, conversion, revenue, agency quality, or named-product superiority.",
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "content_sha256": receipt["content_sha256"], "files": receipt["files"]}, sort_keys=True))


if __name__ == "__main__":
    main()
