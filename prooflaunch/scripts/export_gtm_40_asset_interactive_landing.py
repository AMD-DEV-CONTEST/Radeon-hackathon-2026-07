#!/usr/bin/env python3
"""Export a self-contained interactive landing challenger for the 40-Asset Interview."""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/interactive-landing-v1-40-asset-interview"
EDITORIAL = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
CAROUSEL = ROOT / "artifacts/gtm-last-mile-pk-v1/carousel-challenger-v1-40-asset-interview/carousel-receipt.json"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return os.path.relpath(path, OUTPUT).replace(os.sep, "/")


def seal(payload: dict) -> dict:
    unsigned = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**payload, "content_sha256": hashlib.sha256(unsigned.encode("utf-8")).hexdigest()}


def main() -> dict:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    editorial = load(EDITORIAL)
    carousel = load(CAROUSEL)
    video = load(VIDEO)
    linkedin = next(row for row in editorial["accepted_candidates"] if row["surface_id"] == "linkedin")
    landscape = next(row for row in video["variants"] if row["variant"] == "landscape_4k")
    video_path = ROOT / landscape["video"]["path"]
    poster_path = ROOT / landscape["audit_frames"][0]["path"]
    carousel_path = ROOT / carousel["contact_sheet"]["path"]
    cards = "".join(
        f'<button class="asset-card {"review" if index == 27 else "blocked"}" type="button" aria-label="Asset {index + 1}: {"review" if index == 27 else "blocked"}"><span>{index + 1:02d}</span><b>{"REVIEW" if index == 27 else "×"}</b></button>'
        for index in range(40)
    )
    source_rows = []
    for path, role in ((EDITORIAL, "editorial receipt"), (CAROUSEL, "carousel receipt"), (VIDEO, "dual-aspect video receipt")):
        source_rows.append({"role": role, "path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size})

    evaluator_source = """export function evaluateClaim({ claim, evidencePresent, ownerPresent }) {
  const hasClaim = typeof claim === 'string' && claim.trim().length > 0;
  if (!hasClaim) return { decision: 'BLOCK', state: 'EMPTY', action: 'Add a claim', copy: 'Enter one complete sentence before running the interview.' };
  if (evidencePresent && ownerPresent) return { decision: 'REVIEW', state: 'UNVERIFIED', action: 'Route to human review', copy: 'Evidence and authority are declared. A human may now inspect whether the evidence actually supports this clause.' };
  const missing = [!evidencePresent ? 'evidence object' : '', !ownerPresent ? 'release owner' : ''].filter(Boolean).join(' and ');
  return { decision: 'BLOCK', state: evidencePresent ? 'INFERENCE' : 'HYPOTHESIS', action: ownerPresent ? 'Return for evidence' : 'Return for authority', copy: `Missing ${missing}. The sentence stops before release.` };
}

if (typeof document !== 'undefined') {
  const claim = document.getElementById('claim');
  const evidence = document.getElementById('evidence');
  const owner = document.getElementById('owner');
  const result = document.getElementById('result');
  const label = document.getElementById('result-label');
  const copy = document.getElementById('result-copy');
  const state = document.getElementById('state');
  const action = document.getElementById('action');
  document.getElementById('run').addEventListener('click', () => {
    const next = evaluateClaim({ claim: claim.value, evidencePresent: evidence.checked, ownerPresent: owner.checked });
    result.classList.toggle('review', next.decision === 'REVIEW');
    label.textContent = next.decision;
    copy.textContent = next.copy;
    state.textContent = next.state;
    action.textContent = next.action;
  });
}
"""
    evaluator = OUTPUT / "claim-interview.mjs"
    evaluator.write_text(evaluator_source, encoding="utf-8")

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ProofLaunch — Interview the Claim</title>
  <style>
    :root{{--ink:#0b0b0a;--paper:#f3f0e9;--lime:#dcff3d;--coral:#ff6548;--blue:#4267ff;--line:#bdb9ae;--muted:#66635c}}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}} .wrap{{width:min(1420px,calc(100% - 40px));margin:auto}} a{{color:inherit}}
    nav{{height:66px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);font-size:13px;text-transform:uppercase;letter-spacing:.08em}} nav strong{{font-size:16px;letter-spacing:-.03em;text-transform:none}} nav div{{display:flex;gap:18px}}
    header{{padding:88px 0 60px}} .eyebrow{{font:700 12px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.12em;text-transform:uppercase}} h1{{font-size:clamp(62px,9vw,142px);line-height:.84;letter-spacing:-.078em;margin:26px 0;max-width:1260px}} .lead{{font-size:clamp(20px,2.6vw,38px);line-height:1.12;max-width:1080px}}
    .hero-actions{{display:flex;gap:12px;flex-wrap:wrap;margin-top:34px}} .button{{display:inline-flex;align-items:center;justify-content:center;min-height:56px;padding:0 22px;border:2px solid var(--ink);font-weight:800;text-decoration:none;background:var(--lime)}} .button.alt{{background:transparent}}
    section{{padding:70px 0;border-top:1px solid var(--line)}} .section-head{{display:grid;grid-template-columns:1fr 1.5fr;gap:28px;margin-bottom:34px}} h2{{font-size:clamp(40px,6vw,82px);line-height:.92;letter-spacing:-.06em;margin:0}} .section-head p{{font-size:21px;margin:0;max-width:760px}}
    .wall{{display:grid;grid-template-columns:repeat(8,1fr);gap:10px}} .asset-card{{aspect-ratio:1.45;border:2px solid var(--ink);border-radius:12px;background:#fff;display:flex;flex-direction:column;align-items:flex-start;justify-content:space-between;padding:12px;cursor:pointer}} .asset-card span{{font:700 11px ui-monospace,monospace}} .asset-card b{{font-size:36px;color:var(--coral)}} .asset-card.review{{background:var(--lime)}} .asset-card.review b{{font-size:13px;color:var(--ink)}}
    .counts{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--ink);border:1px solid var(--ink);margin-top:18px}} .counts div{{background:var(--paper);padding:24px}} .counts b{{display:block;font-size:56px;letter-spacing:-.06em}} .counts div:first-child b{{color:var(--coral)}}
    .interview{{display:grid;grid-template-columns:1.25fr .75fr;border:2px solid var(--ink);background:#fff}} .form{{padding:34px}} label{{display:block;font-weight:800;margin:0 0 9px}} textarea{{width:100%;min-height:170px;border:2px solid var(--ink);padding:16px;font:18px/1.4 inherit;resize:vertical}} .checks{{display:grid;gap:11px;margin:20px 0}} .check{{display:flex;align-items:center;gap:12px;padding:14px;border:1px solid var(--line);font-weight:650}} input[type=checkbox]{{width:22px;height:22px;accent-color:var(--blue)}} button.run{{width:100%;min-height:60px;background:var(--ink);color:white;border:0;font:800 17px inherit;cursor:pointer}}
    .result{{padding:34px;background:var(--ink);color:white;display:flex;flex-direction:column;justify-content:space-between}} .result-label{{font-size:clamp(64px,8vw,116px);line-height:.9;letter-spacing:-.06em;color:var(--coral)}} .result.review .result-label{{color:var(--lime)}} .result p{{font-size:19px}} .result dl{{display:grid;grid-template-columns:90px 1fr;gap:9px;font-size:13px}} dt{{font-weight:900;text-transform:uppercase}} dd{{margin:0;color:#c8c8c3}}
    .proof{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}} .proof div{{background:var(--paper);padding:28px;min-height:190px}} .proof b{{display:block;font-size:28px;line-height:1;margin:16px 0}} .proof span{{color:var(--muted)}} video,img{{width:100%;display:block;background:#000}} .media{{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}} .boundary{{padding:28px;background:var(--ink);color:white;font-size:20px}} footer{{padding:50px 0 80px;color:var(--muted)}}
    @media(max-width:820px){{nav div{{display:none}}.section-head,.interview,.media{{grid-template-columns:1fr}}.wall{{grid-template-columns:repeat(4,1fr)}}.proof{{grid-template-columns:repeat(2,1fr)}}}}
  </style>
</head>
<body>
  <nav class="wrap"><strong>ProofLaunch / The 40-Asset Interview</strong><div><a href="#wall">The wall</a><a href="#interview">Run interview</a><a href="#proof">Proof boundary</a></div></nav>
  <header><div class="wrap"><div class="eyebrow">A zero-budget operator utility · local-only interaction</div><h1>Don’t score AI on volume.<br>Score what it refuses.</h1><p class="lead">{html.escape(linkedin['hook'])}</p><div class="hero-actions"><a class="button" href="#interview">Interview one sentence</a><a class="button alt" href="#wall">See the 39 refusals</a></div></div></header>

  <main>
    <section id="wall"><div class="wrap"><div class="section-head"><h2>Forty polished assets walk in.</h2><p>Thirty-nine contain a desired outcome written as if the market already confirmed it. One card stays inside the approved evidence and may advance to human review.</p></div><div class="wall">{cards}</div><div class="counts"><div><b>39</b>blocked before release</div><div><b>1</b>eligible for human review—not approval</div></div></div></section>

    <section id="interview"><div class="wrap"><div class="section-head"><h2>Interview the smoothest sentence.</h2><p>This browser-only diagnostic sends nothing anywhere. A result of REVIEW means the two minimum objects are present; it is not factual verification or publication approval.</p></div><div class="interview">
      <div class="form"><label for="claim">Marketing claim</label><textarea id="claim">This campaign turns interest into qualified pipeline.</textarea><div class="checks"><label class="check"><input id="evidence" type="checkbox">A specific evidence object exists for this clause</label><label class="check"><input id="owner" type="checkbox">A named human release owner is accountable</label></div><button class="run" id="run" type="button">INTERVIEW THIS SENTENCE</button></div>
      <div class="result" id="result" aria-live="polite"><div><div class="eyebrow">Current decision</div><div class="result-label" id="result-label">BLOCK</div><p id="result-copy">No evidence object and no release owner are declared. The sentence stops before release.</p></div><dl><dt>State</dt><dd id="state">HYPOTHESIS</dd><dt>Action</dt><dd id="action">Return for evidence</dd><dt>Authority</dt><dd>Human only</dd></dl></div>
    </div></div></section>

    <section id="proof"><div class="wrap"><div class="section-head"><h2>The four-line release contract.</h2><p>A fluent sentence becomes reviewable only when its claim state, evidence and authority are explicit.</p></div><div class="proof"><div><div class="eyebrow">01</div><b>Supported clause</b><span>What exact words stay inside the approved source?</span></div><div><div class="eyebrow">02</div><b>Evidence object</b><span>Which inspectable object supports those exact words?</span></div><div><div class="eyebrow">03</div><b>Remaining hypothesis</b><span>What outcome still belongs to the future?</span></div><div><div class="eyebrow">04</div><b>Release owner</b><span>Who may approve, return or refuse the action?</span></div></div></div></section>

    <section><div class="wrap"><div class="section-head"><h2>One spine, multiple native assets.</h2><p>The landing utility, 4K film and eight-slide editorial carousel share the same claim boundary while using different information shapes.</p></div><div class="media"><video controls preload="metadata" poster="{html.escape(rel(poster_path))}" src="{html.escape(rel(video_path))}"></video><img loading="lazy" src="{html.escape(rel(carousel_path))}" alt="Eight-slide 40-Asset Interview carousel"></div></div></section>

    <section><div class="wrap"><div class="boundary">Truth boundary: this is a clean-room interactive campaign challenger. It records no user input, calls no model, publishes nothing, and proves no human preference, named-product superiority, market lift, conversion, pipeline or revenue.</div></div></section>
  </main>
  <footer><div class="wrap">ProofLaunch Cortex-X compiles a rights-bound brief into review-ready GTM assets. External release remains a named human decision.</div></footer>
  <script type="module" src="claim-interview.mjs"></script>
</body>
</html>
"""
    index = OUTPUT / "index.html"
    index.write_text(page, encoding="utf-8")
    payload = {
        "schema": "ProofLaunchGTM40AssetInteractiveLandingReceiptV1",
        "landing": {"path": str(index.relative_to(ROOT)), "sha256": sha256(index), "bytes": index.stat().st_size},
        "evaluator": {"path": str(evaluator.relative_to(ROOT)), "sha256": sha256(evaluator), "bytes": evaluator.stat().st_size, "runtime_case_count": 4},
        "creative_concept": "The 40-Asset Interview",
        "asset_card_count": 40,
        "blocked_card_count": 39,
        "review_card_count": 1,
        "network_call_count": 0,
        "model_call_count": 0,
        "external_publish_executed": False,
        "human_release_required": True,
        "human_preference_observed": False,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "source_bindings": source_rows,
        "open_source_modifications": ["standards-only HTML/CSS/JavaScript interactive utility", "content-addressed local media bindings"],
        "truth_boundary": "This artifact proves a local interactive claim-intake experience. REVIEW means required fields are present, not that evidence is valid or release is approved. No human preference, named-product superiority or business effect is proven.",
    }
    receipt = seal(payload)
    receipt_path = OUTPUT / "interactive-landing-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(index), "asset_card_count": 40, "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
