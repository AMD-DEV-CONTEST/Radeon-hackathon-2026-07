from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / "evidence/v10/prooflaunch-front-stage-brief-v1.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(payload: dict) -> dict:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**payload, "content_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def main() -> None:
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True)

    engine = r'''const SUPERLATIVES = /\b(best|leading|top[- ]?1|number one|#1|world[- ]class|4a[- ]grade|unmatched|ultimate)\b/gi;
const GUARANTEES = /\b(guarantee[sd]?|always|never fails?|any brand|everyone|zero risk)\b/gi;
const OUTCOMES = /\b(viral|revenue|conversion|pipeline|roi|sales|growth|retention|signups?)\b/gi;
const NUMBERS = /(?:\b\d+(?:\.\d+)?%|\b\d+x\b|\$\d+)/gi;

const unique = values => [...new Set(values.map(value => value.toLowerCase()))];
const hits = (text, pattern) => unique(text.match(pattern) || []);

function evidenceScore(input) {
  let score = 0;
  if (input.evidence.trim().length >= 32) score += 2;
  if (input.source.trim().length >= 8) score += 2;
  if (input.sample === 'measured') score += 2;
  if (input.sample === 'independent') score += 3;
  if (input.period === 'current') score += 1;
  if (input.limitations.trim().length >= 16) score += 1;
  return score;
}

function boundedRewrite(input, signals) {
  const evidence = input.evidence.trim();
  if (!evidence) return 'Describe the product’s observable job first. Add an outcome only after a named source, population, period and limitation are attached.';
  const source = input.source.trim() || 'the cited source';
  const boundary = input.limitations.trim() ? ` Limitation: ${input.limitations.trim()}` : '';
  return `${evidence.replace(/[.!]+$/, '')}, according to ${source}.${boundary}`;
}

export function tryClaim(input) {
  const claim = String(input.claim || '').trim();
  const signals = {
    superlatives: hits(claim, SUPERLATIVES),
    guarantees: hits(claim, GUARANTEES),
    outcomes: hits(claim, OUTCOMES),
    numbers: hits(claim, NUMBERS)
  };
  const risk = signals.superlatives.length * 2 + signals.guarantees.length * 3 + signals.outcomes.length * 2 + signals.numbers.length * 2;
  const proof = evidenceScore(input);
  let verdict = 'NEEDS A BOUNDARY';
  let charge = 'The claim outruns the attached evidence boundary.';
  if (claim.length < 18) {
    verdict = 'TOO VAGUE TO TRY';
    charge = 'There is no falsifiable job, population or outcome to examine.';
  } else if (!input.evidence.trim() && risk >= 2) {
    verdict = 'NO WITNESS';
    charge = 'The claim asks the audience to believe an outcome without a named observation.';
  } else if (proof >= 7 && proof >= risk) {
    verdict = 'PROVISIONALLY SUPPORTED';
    charge = 'The evidence shape can support a bounded version, pending source and human review.';
  } else if (risk === 0 && proof >= 4) {
    verdict = 'PROVISIONALLY SUPPORTED';
    charge = 'The operational claim is narrow and has a reviewable evidence trail.';
  }
  const flags = [...signals.superlatives, ...signals.guarantees, ...signals.outcomes, ...signals.numbers];
  const missing = [];
  if (!input.evidence.trim()) missing.push('observable result');
  if (!input.source.trim()) missing.push('named source');
  if (input.sample === 'none') missing.push('population or sample');
  if (input.period === 'none') missing.push('measurement period');
  if (!input.limitations.trim()) missing.push('material limitation');
  const rewrite = boundedRewrite(input, signals);
  return {
    claim, verdict, charge, risk, proof, flags, missing, rewrite,
    witness: proof >= 7 ? 'Evidence entered; independent/human review still required.' : 'No admissible witness yet.',
    launchHook: verdict === 'NO WITNESS'
      ? `We asked our own product to defend “${claim}”. It refused.`
      : `Before publishing “${claim}”, we put it on trial.`,
    juryQuestion: 'What single source would change this verdict?',
    shareText: `CLAIM TRIAL / ${verdict}\n“${claim}”\nMissing: ${missing.join(', ') || 'no structural field'}\nThe market will cross-examine it anyway.`,
    truthBoundary: 'Creative evidence challenge only. Not legal advice, substantiation approval, publication proof or observed market effect.'
  };
}

if (typeof document !== 'undefined') {
  const form = document.getElementById('trial-form');
  const render = (result, shouldScroll = true) => {
    document.getElementById('verdict').textContent = result.verdict;
    document.getElementById('charge').textContent = result.charge;
    document.getElementById('flags').innerHTML = result.flags.length ? result.flags.map(x=>`<span>${x}</span>`).join('') : '<span>no high-risk phrase detected</span>';
    document.getElementById('missing').innerHTML = result.missing.length ? result.missing.map(x=>`<li>${x}</li>`).join('') : '<li>no structural field missing</li>';
    document.getElementById('rewrite').textContent = result.rewrite;
    document.getElementById('hook').textContent = result.launchHook;
    document.getElementById('jury').textContent = result.juryQuestion;
    document.getElementById('share').textContent = result.shareText;
    const out = document.getElementById('trial-output'); out.hidden = false;
    if (shouldScroll) out.scrollIntoView({behavior:'smooth'});
  };
  form.addEventListener('submit', event => {event.preventDefault(); render(tryClaim(Object.fromEntries(new FormData(form))))});
  render(tryClaim(Object.fromEntries(new FormData(form))), false);
}
'''
    module = OUTPUT / "claim-trial-engine.mjs"
    module.write_text(engine, encoding="utf-8")
    browser_engine = OUTPUT / "claim-trial-browser.js"
    browser_engine.write_text(
        engine.replace("export function tryClaim", "function tryClaim"),
        encoding="utf-8",
    )

    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim Trial — Put the claim on trial before the market does</title><style>
:root{{--ink:#0a0a09;--paper:#f1eee5;--acid:#e8ff36;--red:#ff563f;--blue:#3d5afe;--rule:#aaa69b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.42 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}.wrap{{width:min(1440px,calc(100% - 40px));margin:auto}}nav{{height:62px;border-bottom:1px solid var(--rule);display:flex;align-items:center;justify-content:space-between}}nav span,.mono,label,.stamp small{{font:800 11px ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em;text-transform:uppercase}}header{{padding:72px 0 58px}}h1{{font-size:clamp(58px,9.5vw,146px);line-height:.82;letter-spacing:-.08em;margin:24px 0;max-width:1320px}}h1 em{{font-style:normal;color:var(--red)}}.lead{{font-size:clamp(21px,2.7vw,38px);line-height:1.12;max-width:1000px}}.self-indictment{{margin-top:50px;border:2px solid var(--ink);display:grid;grid-template-columns:1fr 220px}}.self-indictment p{{font-size:clamp(24px,3vw,44px);line-height:1.05;padding:28px;margin:0}}.self-indictment b{{background:var(--red);display:grid;place-items:center;font-size:28px;transform:rotate(-2deg)}}section{{border-top:1px solid var(--rule);padding:64px 0}}.head{{display:grid;grid-template-columns:1fr 1.2fr;gap:30px;margin-bottom:30px}}h2{{font-size:clamp(42px,6vw,82px);line-height:.9;letter-spacing:-.06em;margin:0}}.head p{{font-size:20px;margin:0;max-width:700px}}form{{display:grid;grid-template-columns:2fr 1fr;gap:10px}}.field{{border:1px solid var(--rule);background:#faf8f2;padding:18px}}.wide{{grid-column:1/-1}}label{{display:block;margin-bottom:9px}}textarea,input,select{{width:100%;border:2px solid var(--ink);background:white;padding:13px;font:700 16px/1.35 inherit}}textarea{{min-height:92px;resize:vertical}}button{{grid-column:1/-1;border:2px solid var(--ink);background:var(--acid);min-height:76px;font:900 21px inherit;cursor:pointer}}button:hover{{background:var(--red)}}#trial-output[hidden]{{display:none}}.verdict-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:12px}}.stamp{{background:var(--red);border:3px solid var(--ink);padding:34px;min-height:420px;display:flex;flex-direction:column}}.stamp h2{{font-size:clamp(56px,8vw,116px);margin:auto 0;transform:rotate(-3deg)}}.stamp p{{font-size:22px}}.docket{{border:2px solid var(--ink);padding:28px}}.flags{{display:flex;gap:7px;flex-wrap:wrap}}.flags span{{background:var(--ink);color:white;padding:7px 10px;font:800 12px ui-monospace,monospace}}.docket h3{{font-size:26px;margin:28px 0 8px}}.rewrite{{background:var(--acid);border:2px solid var(--ink);padding:22px;font-size:20px;font-weight:750}}.launch{{display:grid;grid-template-columns:2fr 1fr;gap:12px}}.launch article{{border:2px solid var(--ink);padding:28px;min-height:280px}}.launch article:first-child{{background:var(--blue);color:white}}.launch h3{{font-size:36px;line-height:1.04;margin:40px 0 0}}.share{{white-space:pre-line;background:var(--ink);color:white;padding:32px;font:800 24px/1.2 ui-monospace,monospace}}.boundary{{font-size:13px;color:#666;margin-top:18px}}footer{{padding:45px 0 80px;color:#666}}@media(max-width:800px){{form,.head,.verdict-grid,.launch,.self-indictment{{grid-template-columns:1fr}}.self-indictment b{{min-height:110px}}}}
</style></head><body><nav class="wrap"><strong>ProofLaunch / Claim Trial</strong><span>Local challenger · no publishing</span></nav><header><div class="wrap"><div class="mono">The anti-hype product demo</div><h1>Put the claim on trial <em>before the market does.</em></h1><p class="lead">Most AI marketing tools help a weak claim travel faster. This one starts by trying to kill it.</p><div class="self-indictment"><p>“{brief['self_trial_claim']}”</p><b>{brief['self_trial_verdict']}</b></div></div></header><main><section><div class="wrap"><div class="head"><h2>Call your first witness.</h2><p>Enter the exact sentence you want to publish. Evidence must identify an observable result, source, population, period and limitation.</p></div><form id="trial-form"><div class="field wide"><label for="claim">Claim under oath</label><textarea id="claim" name="claim">{brief['self_trial_claim']}</textarea></div><div class="field wide"><label for="evidence">Observable evidence</label><textarea id="evidence" name="evidence" placeholder="What was directly observed? Leave blank to test the unsupported claim."></textarea></div><div class="field"><label for="source">Named source</label><input id="source" name="source" placeholder="Report, dataset, customer record"></div><div class="field"><label for="sample">Evidence shape</label><select id="sample" name="sample"><option value="none">No sample</option><option value="measured">Measured internal sample</option><option value="independent">Independent evaluation</option></select></div><div class="field"><label for="period">Period</label><select id="period" name="period"><option value="none">Not stated</option><option value="historical">Historical</option><option value="current">Current / bounded</option></select></div><div class="field"><label for="limitations">Material limitation</label><input id="limitations" name="limitations" placeholder="Where does this evidence stop?"></div><button type="submit">TRY THE CLAIM →</button></form></div></section><div id="trial-output" hidden><section><div class="wrap"><div class="verdict-grid"><article class="stamp"><small>Verdict</small><h2 id="verdict"></h2><p id="charge"></p></article><article class="docket"><div class="mono">High-risk language</div><div id="flags" class="flags"></div><h3>Missing witnesses</h3><ul id="missing"></ul><h3>Bounded rewrite</h3><div id="rewrite" class="rewrite"></div></article></div></div></section><section><div class="wrap"><div class="head"><h2>Turn the refusal into the launch.</h2><p>A rejection is not a dead end. It is the conflict, demonstration and invitation.</p></div><div class="launch"><article><div class="mono">Launch hook</div><h3 id="hook"></h3></article><article><div class="mono">Ask the jury</div><h3 id="jury"></h3></article></div></div></section><section><div class="wrap"><div class="head"><h2>Make the verdict portable.</h2><p>A result worth sharing names the claim and the missing proof. It does not fake an outcome.</p></div><div id="share" class="share"></div><p class="boundary">Creative evidence challenge only. Not legal advice, automated substantiation approval, publication proof or observed market effect.</p></div></section></div></main><footer><div class="wrap">Product truth: {brief['approved_product_truth']}</div></footer><script src="claim-trial-browser.js"></script></body></html>'''
    index = OUTPUT / "index.html"
    index.write_text(page, encoding="utf-8")

    share_card = f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1350px;overflow:hidden}}body{{background:#f1eee5;color:#090908;font-family:Inter,Arial,sans-serif;padding:62px;display:flex;flex-direction:column}}.top{{display:flex;justify-content:space-between;border-bottom:3px solid #090908;padding-bottom:18px;font:900 22px/1 ui-monospace,monospace;letter-spacing:.06em}}.eyebrow{{margin-top:74px;font:900 21px/1 ui-monospace,monospace;letter-spacing:.08em}}h1{{font-size:108px;line-height:.86;letter-spacing:-.078em;margin:30px 0 42px}}.claim{{font-size:46px;line-height:1.1;border:4px solid #090908;padding:38px}}.verdict{{margin-top:-4px;margin-left:auto;width:620px;background:#ff563f;border:4px solid #090908;padding:32px;text-align:center;font-size:64px;font-weight:950;transform:rotate(-2deg)}}.missing{{margin-top:62px;display:grid;grid-template-columns:220px 1fr;gap:26px;font-size:28px}}.missing b{{font:900 20px ui-monospace,monospace;letter-spacing:.07em}}.footer{{margin-top:auto;background:#090908;color:white;padding:26px 30px;font:900 23px/1.2 ui-monospace,monospace}}em{{font-style:normal;color:#ff563f}}
</style></head><body><div class="top"><span>PROOFLAUNCH / CLAIM TRIAL</span><span>SELF-TRIAL 001</span></div><div class="eyebrow">WE ASKED OUR OWN AI TO PROVE IT</div><h1>It refused<br>to call itself <em>4A.</em></h1><div class="claim">“{brief['self_trial_claim']}”</div><div class="verdict">NO WITNESS</div><div class="missing"><b>MISSING</b><span>Independent preference. Observed organic breakout. Conversion. Revenue.</span></div><div class="footer">IF YOUR AI WON’T CHALLENGE YOUR CLAIM,<br>IT ISN’T YOUR GTM EMPLOYEE.</div></body></html>'''
    share_card_path = OUTPUT / "share-card-4x5.html"
    share_card_path.write_text(share_card, encoding="utf-8")

    launch = {
        "schema": "ProofLaunchClaimTrialLaunchPackV1",
        "organizing_idea": "Put the claim on trial before the market does.",
        "linkedin_post": {
            "hook": "We asked our own AI to prove it was ‘4A-grade.’ It refused.",
            "body": [
                "The original claim: ‘A 4A-grade GTM employee that makes any brand go viral.’",
                "Verdict: NO WITNESS.",
                "No independent preference result. No observed organic breakout. No conversion or revenue evidence. So ProofLaunch would not let ProofLaunch publish it.",
                "That refusal is the product demo. Paste the line your team wants to ship. The Claim Trial identifies the missing witness, writes the bounded version, and leaves the hard question visible.",
                "If your AI will not challenge your claim, it is not your GTM employee. It is your hype intern."
            ],
            "cta": "Put one claim on trial. What single source would change the verdict?"
        },
        "short_video": {
            "duration_seconds": 15,
            "beats": [
                {"seconds": "0-2", "visual": "Oversized claim enters frame", "voice": "We asked our own AI to prove it was 4A."},
                {"seconds": "2-5", "visual": "Claim Trial scans risky phrases", "voice": "It found the problem in three seconds."},
                {"seconds": "5-8", "visual": "Red NO WITNESS verdict lands", "voice": "No witness. No virality evidence. Claim rejected."},
                {"seconds": "8-12", "visual": "Bounded rewrite replaces the hype", "voice": "Then it wrote the version the evidence can carry."},
                {"seconds": "12-15", "visual": "Cursor on Try the claim", "voice": "Put your claim on trial before the market does."}
            ]
        },
        "truth_boundary": brief["truth_boundary"]
    }
    launch_path = OUTPUT / "launch-pack.json"
    launch_path.write_text(json.dumps(launch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = seal({
        "schema": "ProofLaunchClaimTrialReceiptV1",
        "brief_sha256": digest(BRIEF),
        "experience": {"path": str(index.relative_to(ROOT)), "sha256": digest(index)},
        "engine": {"path": str(module.relative_to(ROOT)), "sha256": digest(module)},
        "browser_engine": {"path": str(browser_engine.relative_to(ROOT)), "sha256": digest(browser_engine)},
        "share_card_html": {"path": str(share_card_path.relative_to(ROOT)), "sha256": digest(share_card_path)},
        "launch_pack": {"path": str(launch_path.relative_to(ROOT)), "sha256": digest(launch_path)},
        "front_stage_status": "candidate_pending_human_preference_and_observed_effect_review",
        "self_claim_rejected": True,
        "network_call_count": 0,
        "model_call_count": 0,
        "external_publish_executed": False,
        "human_preference_observed": False,
        "production_effect_observed": False,
        "completed_named_product_pk_count": 0,
        "named_product_win_count": 0,
        "truth_boundary": brief["truth_boundary"]
    })
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(index), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
