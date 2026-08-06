#!/usr/bin/env python3
"""Export the GTM Kill List: a local, shareable channel-concentration challenger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-kill-list-experience-v1"

RESEARCH_SOURCES = [
    {
        "label": "Icon challenge-and-reveal launch breakdown",
        "url": "https://www.linkedin.com/posts/louise-de-sadeleer_this-is-one-of-my-favourite-product-launch-activity-7384197830048894976-IN42",
        "mechanism": "challenge plus reveal; the demonstration itself carries the hook",
    },
    {
        "label": "Solaris launch-day operating account",
        "url": "https://www.linkedin.com/posts/annieliaoo_startups-ai-activity-7418759091902394369-3Wum",
        "mechanism": "one sharp story, one CTA, coordinated early distribution",
    },
    {
        "label": "Ask Attio launch",
        "url": "https://attio.com/blog/introducing-ask-attio",
        "mechanism": "product shown through concrete jobs, not an abstract feature inventory",
    },
    {
        "label": "Figma Make launch",
        "url": "https://www.figma.com/blog/introducing-figma-make/",
        "mechanism": "make the capability real enough to play with immediately",
    },
    {
        "label": "Was kann ich essen organic case",
        "url": "https://superscale.ai/case-study/was-kann-ich-essen",
        "mechanism": "strong hooks plus quick product demonstration across repeated organic variants",
    },
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(payload: dict) -> dict:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**payload, "content_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def main() -> dict:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    engine = r'''export const CHANNELS = [
  {id:'linkedin',label:'LinkedIn',kind:'social',b2b:10,b2c:3,pre_pmf:3,launch:4,growth:3,zero:3,small:3,scaled:3,saas:4,consumer_app:0,commerce:1,service:5},
  {id:'reddit',label:'Reddit',kind:'community',b2b:6,b2c:5,pre_pmf:6,launch:3,growth:2,zero:4,small:3,scaled:1,saas:3,consumer_app:3,commerce:2,service:2},
  {id:'youtube',label:'YouTube',kind:'video',b2b:7,b2c:8,pre_pmf:2,launch:5,growth:5,zero:2,small:4,scaled:6,saas:3,consumer_app:4,commerce:4,service:3},
  {id:'tiktok',label:'TikTok',kind:'social',b2b:2,b2c:10,pre_pmf:3,launch:6,growth:5,zero:4,small:4,scaled:6,saas:0,consumer_app:6,commerce:6,service:1},
  {id:'instagram',label:'Instagram',kind:'social',b2b:2,b2c:9,pre_pmf:3,launch:5,growth:5,zero:3,small:4,scaled:6,saas:0,consumer_app:5,commerce:6,service:2},
  {id:'x',label:'X',kind:'social',b2b:6,b2c:4,pre_pmf:5,launch:4,growth:2,zero:4,small:3,scaled:2,saas:4,consumer_app:2,commerce:1,service:3},
  {id:'google',label:'Google Search',kind:'owned',b2b:8,b2c:6,pre_pmf:0,launch:2,growth:7,zero:3,small:5,scaled:7,saas:4,consumer_app:3,commerce:6,service:5},
  {id:'bing',label:'Bing Search',kind:'owned',b2b:5,b2c:2,pre_pmf:0,launch:1,growth:4,zero:2,small:3,scaled:4,saas:3,consumer_app:1,commerce:2,service:3},
  {id:'chatgpt',label:'ChatGPT answers',kind:'owned',b2b:7,b2c:5,pre_pmf:1,launch:3,growth:7,zero:3,small:4,scaled:6,saas:5,consumer_app:3,commerce:3,service:4},
  {id:'claude',label:'Claude answers',kind:'owned',b2b:6,b2c:2,pre_pmf:1,launch:2,growth:5,zero:2,small:3,scaled:5,saas:5,consumer_app:1,commerce:1,service:4},
  {id:'gemini',label:'Gemini answers',kind:'owned',b2b:5,b2c:5,pre_pmf:1,launch:3,growth:6,zero:2,small:3,scaled:6,saas:3,consumer_app:3,commerce:4,service:3},
  {id:'perplexity',label:'Perplexity answers',kind:'owned',b2b:7,b2c:3,pre_pmf:2,launch:3,growth:6,zero:3,small:4,scaled:6,saas:5,consumer_app:2,commerce:2,service:5},
  {id:'copilot',label:'Copilot answers',kind:'owned',b2b:6,b2c:2,pre_pmf:0,launch:2,growth:5,zero:2,small:3,scaled:5,saas:4,consumer_app:1,commerce:2,service:4}
];

const HOOKS = {
  b2b: {
    pre_pmf: 'We gave the product the hardest job first: decide who should never buy it.',
    launch: 'Your launch does not need thirteen channels. It needs the courage to kill ten.',
    growth: 'The channel with the most reach may be the one hiding your weakest conversion truth.'
  },
  b2c: {
    pre_pmf: 'Before building another feature, we let strangers try to break the use moment.',
    launch: 'This app is not asking for your attention. It is trying to earn one repeatable moment.',
    growth: 'We killed the content everyone copied and kept the behavior users repeated.'
  }
};

function score(channel, input) {
  let value = channel[input.businessModel] + channel[input.stage] + channel[input.budget] + channel[input.category];
  if (input.proof === 'weak') value += channel.kind === 'community' ? 4 : channel.kind === 'owned' ? -3 : 1;
  if (input.proof === 'working') value += channel.kind === 'social' || channel.kind === 'video' ? 2 : 1;
  if (input.proof === 'strong') value += channel.kind === 'owned' ? 5 : 2;
  return value;
}

function reason(channel, input, selected) {
  if (selected) {
    if (channel.kind === 'owned') return 'Compounds the proof into durable search and answer demand.';
    if (channel.kind === 'community') return 'Fastest place to collect disconfirming language before scaling.';
    if (channel.kind === 'video') return 'Best surface for a challenge, reveal and product-in-action proof.';
    return input.businessModel === 'b2b' ? 'Highest concentration of the buying role and operator conversation.' : 'Best fit for repeatable, identity-relevant participation.';
  }
  if (channel.kind === 'owned' && input.proof === 'weak') return 'Killed until source-worthy proof exists; thin evidence will not compound.';
  if (channel.id === 'tiktok' || channel.id === 'instagram') return input.businessModel === 'b2b' ? 'Killed because the current buying job is too narrow for broad visual reach.' : 'Killed this cycle to avoid splitting the same short-form learning across two feeds.';
  if (channel.id === 'linkedin') return 'Killed because professional commentary is not the current use moment.';
  return 'Killed for this seven-day cycle: lower decision density than the three funded surfaces.';
}

export function buildKillList(input) {
  const scored = CHANNELS.map(channel => ({...channel,score:score(channel,input)})).sort((a,b) => b.score-a.score || a.id.localeCompare(b.id));
  const earned = scored.filter(row => row.kind !== 'owned');
  const owned = scored.filter(row => row.kind === 'owned');
  const primary = earned[0];
  const secondary = earned.find(row => row.id !== primary.id);
  const compound = owned[0];
  const selectedIds = new Set([primary.id, secondary.id, compound.id]);
  const selected = [
    {...primary,allocation:70,role:'PRIMARY BET',reason:reason(primary,input,true)},
    {...secondary,allocation:20,role:'SECONDARY TEST',reason:reason(secondary,input,true)},
    {...compound,allocation:10,role:'COMPOUNDING LAYER',reason:reason(compound,input,true)}
  ];
  const killed = scored.filter(row => !selectedIds.has(row.id)).map(row => ({...row,reason:reason(row,input,false)}));
  const hook = HOOKS[input.businessModel][input.stage];
  const week = [
    {day:'DAY 1',job:'Product becomes the content',move:`Publish one ${primary.label}-native challenge that shows the decision, not a feature list.`,hook},
    {day:'DAY 3',job:'Invite a counterexample',move:`Use ${secondary.label} to ask the audience to break one assumption; collect language, not praise.`,hook:'What would make this recommendation wrong for your company?'},
    {day:'DAY 5',job:'Compound the answer',move:`Turn the strongest resolved question into one source-ready ${compound.label} answer object.`,hook:'Direct answer first. Evidence boundary second. Product only if relevant.'}
  ];
  return {
    input,
    selected:selected.map(({id,label,allocation,role,reason,score})=>({id,label,allocation,role,reason,score})),
    killed:killed.map(({id,label,reason,score})=>({id,label,reason,score})),
    week,
    shareText:`I killed 10 channels. My next GTM cycle: 70% ${primary.label} / 20% ${secondary.label} / 10% ${compound.label}. The hardest part was admitting what not to fund.`,
    truthBoundary:'Strategy hypothesis generated from declared inputs. No reach, conversion or revenue result is predicted or guaranteed.'
  };
}

if (typeof document !== 'undefined') {
  const form = document.getElementById('kill-form');
  const output = document.getElementById('output');
  const render = result => {
    document.getElementById('portfolio').innerHTML = result.selected.map(row => `<article><small>${row.role}</small><b>${row.allocation}%</b><h3>${row.label}</h3><p>${row.reason}</p></article>`).join('');
    document.getElementById('kills').innerHTML = result.killed.map(row => `<details><summary><span>${row.label}</span><b>KILL</b></summary><p>${row.reason}</p></details>`).join('');
    document.getElementById('week').innerHTML = result.week.map(row => `<article><small>${row.day} / ${row.job}</small><h3>${row.hook}</h3><p>${row.move}</p></article>`).join('');
    document.getElementById('share-text').textContent = result.shareText;
    output.hidden = false;
    output.scrollIntoView({behavior:'smooth',block:'start'});
  };
  form.addEventListener('submit', event => {
    event.preventDefault();
    render(buildKillList(Object.fromEntries(new FormData(form))));
  });
}
'''
    engine_path = OUTPUT / "gtm-kill-list-engine.mjs"
    engine_path.write_text(engine, encoding="utf-8")

    page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GTM Kill List — Fund 3, Kill 10</title>
<style>
:root{--ink:#090908;--paper:#f2efe7;--lime:#dfff3f;--coral:#ff6449;--blue:#4569ff;--line:#bab6aa;--muted:#64615a}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}.wrap{width:min(1420px,calc(100% - 40px));margin:auto}nav{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}nav strong{letter-spacing:-.03em}nav span,.eyebrow{font:700 12px ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.1em}header{padding:92px 0 62px}h1{font-size:clamp(60px,9vw,140px);line-height:.84;letter-spacing:-.078em;margin:26px 0;max-width:1300px}.lead{font-size:clamp(22px,2.7vw,38px);line-height:1.12;max-width:960px}.strike{text-decoration:line-through;text-decoration-color:var(--coral);text-decoration-thickness:.09em}.hero-rule{display:grid;grid-template-columns:7fr 2fr 1fr;height:28px;margin-top:48px}.hero-rule i:nth-child(1){background:var(--lime)}.hero-rule i:nth-child(2){background:var(--coral)}.hero-rule i:nth-child(3){background:var(--blue)}section{padding:68px 0;border-top:1px solid var(--line)}.section-head{display:grid;grid-template-columns:1fr 1.4fr;gap:26px;margin-bottom:34px}h2{font-size:clamp(42px,6vw,82px);line-height:.92;letter-spacing:-.06em;margin:0}.section-head p{font-size:21px;margin:0;max-width:720px}.builder{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--ink);border:2px solid var(--ink)}.field{padding:20px;background:var(--paper)}label{display:block;font:800 11px ui-monospace,monospace;text-transform:uppercase;margin-bottom:10px}select{width:100%;height:52px;border:2px solid var(--ink);background:#fff;padding:0 12px;font:700 15px inherit}.run{grid-column:1/-1;min-height:74px;background:var(--lime);border:0;font:900 20px inherit;cursor:pointer}.run:hover{background:var(--coral)}#output[hidden]{display:none}.portfolio{display:grid;grid-template-columns:7fr 2fr 1fr;gap:10px}.portfolio article{border:2px solid var(--ink);padding:26px;min-height:270px;display:flex;flex-direction:column}.portfolio article:nth-child(1){background:var(--lime)}.portfolio article:nth-child(2){background:var(--coral)}.portfolio article:nth-child(3){background:var(--blue);color:white}.portfolio small{font:800 11px ui-monospace,monospace}.portfolio b{font-size:64px;letter-spacing:-.07em;margin-top:auto}.portfolio h3{font-size:30px;margin:0}.portfolio p{font-size:14px}.kill-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}details{border:1px solid var(--line);background:#faf8f2}summary{padding:18px;display:flex;justify-content:space-between;cursor:pointer;font-weight:800}summary b{color:var(--coral)}details p{padding:0 18px 18px;color:var(--muted)}.week{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.week article{border:2px solid var(--ink);padding:26px;min-height:320px}.week article:nth-child(2){background:var(--ink);color:white}.week h3{font-size:28px;line-height:1.05}.share{background:var(--ink);color:white;padding:38px;display:grid;grid-template-columns:1fr 2fr;gap:30px}.share p{font-size:28px;line-height:1.16;margin:0}.boundary{font-size:13px;color:var(--muted);margin-top:18px}footer{padding:44px 0 80px;color:var(--muted)}@media(max-width:850px){.builder,.section-head,.portfolio,.week,.share{grid-template-columns:1fr}.kill-grid{grid-template-columns:1fr}.portfolio article{min-height:220px}}
</style></head><body>
<nav class="wrap"><strong>ProofLaunch / GTM Kill List</strong><span>Strategy prototype · local only</span></nav>
<header><div class="wrap"><div class="eyebrow">The anti-content-calendar</div><h1>Your company doesn’t need 13 channels.<br>It needs permission to <span class="strike">ignore 10.</span></h1><p class="lead">Build a ruthless seven-day GTM portfolio. Fund one primary bet, one secondary learning loop and one compounding answer layer.</p><div class="hero-rule"><i></i><i></i><i></i></div></div></header>
<main><section><div class="wrap"><div class="section-head"><h2>Declare the constraints.</h2><p>No “it depends” report. Five choices produce three funded surfaces, ten explicit kills and a first-week operating plan.</p></div><form id="kill-form" class="builder">
<div class="field"><label for="businessModel">Motion</label><select id="businessModel" name="businessModel"><option value="b2b">B2B</option><option value="b2c">B2C</option></select></div>
<div class="field"><label for="stage">Stage</label><select id="stage" name="stage"><option value="pre_pmf">Pre-PMF</option><option value="launch" selected>Launch</option><option value="growth">Growth</option></select></div>
<div class="field"><label for="budget">Budget</label><select id="budget" name="budget"><option value="zero">Zero</option><option value="small">Small</option><option value="scaled">Scaled</option></select></div>
<div class="field"><label for="proof">Proof strength</label><select id="proof" name="proof"><option value="weak">Weak</option><option value="working" selected>Working</option><option value="strong">Strong</option></select></div>
<div class="field"><label for="category">Category</label><select id="category" name="category"><option value="saas">SaaS / AI</option><option value="consumer_app">Consumer app</option><option value="commerce">Commerce</option><option value="service">Professional service</option></select></div>
<button class="run" type="submit">KILL 10 CHANNELS →</button></form></div></section>

<div id="output" hidden><section><div class="wrap"><div class="section-head"><h2>Fund three.<br>Kill ten.</h2><p>Allocation expresses attention and learning priority, not an automatic media budget. Every external action still requires an owner.</p></div><div id="portfolio" class="portfolio"></div></div></section>
<section><div class="wrap"><div class="section-head"><h2>The kill list.</h2><p>Every “no” expires after this seven-day cycle. A killed channel returns only when evidence or stage changes—not because the team feels busy.</p></div><div id="kills" class="kill-grid"></div></div></section>
<section><div class="wrap"><div class="section-head"><h2>Your first week.</h2><p>The product becomes the content; the audience is invited to challenge it; the resolved question compounds into owned discovery.</p></div><div id="week" class="week"></div></div></section>
<section><div class="wrap"><div class="share"><div><div class="eyebrow">Screenshot this decision</div><h2>My GTM portfolio</h2></div><p id="share-text"></p></div><p class="boundary">Strategy hypothesis only. No reach, virality, conversion, pipeline or revenue is predicted or guaranteed.</p></div></section></div></main>
<footer><div class="wrap">No model call · no network call · no tracking · no publishing · no spend authority.</div></footer><script type="module" src="gtm-kill-list-engine.mjs"></script></body></html>'''
    index = OUTPUT / "index.html"
    index.write_text(page, encoding="utf-8")
    payload = {
        "schema": "ProofLaunchGTMKillListExperienceReceiptV1",
        "front_stage_status": "candidate_pending_human_craft_and_observed_effect_review",
        "supersedes_front_stage_concept": "The 40-Asset Interview",
        "previous_concept_disposition": "retained_as_backstage_trust_evidence_not_front_stage_growth_idea",
        "creative_concept": "The GTM Kill List",
        "promise": "Declare five constraints; receive three funded surfaces, ten killed surfaces and a seven-day operating plan.",
        "mechanism": "product_as_content_plus_contrarian_concentration_plus_shareable_personalized_result",
        "landing": {"path": str(index.relative_to(ROOT)), "sha256": digest(index), "bytes": index.stat().st_size},
        "engine": {"path": str(engine_path.relative_to(ROOT)), "sha256": digest(engine_path), "bytes": engine_path.stat().st_size},
        "channel_count": 13,
        "selected_channel_count": 3,
        "killed_channel_count": 10,
        "runtime_fixture_count": 6,
        "research_sources": RESEARCH_SOURCES,
        "network_call_count": 0,
        "model_call_count": 0,
        "external_publish_executed": False,
        "human_preference_observed": False,
        "production_effect_observed": False,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "truth_boundary": "This is a strategy and creative challenger. It proves deterministic scenario differentiation and a directly usable output shape, not human preference, organic breakout, named-product superiority, conversion or revenue.",
    }
    receipt = seal(payload)
    receipt_path = OUTPUT / "gtm-kill-list-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(index), "creative_concept": payload["creative_concept"], "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
