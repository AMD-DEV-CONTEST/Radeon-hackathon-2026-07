#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v1"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise SystemExit("output directory must be empty")
    launch = json.loads((EXPERIENCE / "launch-pack.json").read_text(encoding="utf-8"))
    audio = json.loads((AUDIO / "audio-candidate-receipt.json").read_text(encoding="utf-8"))
    video = json.loads((VIDEO / "receipt.json").read_text(encoding="utf-8"))
    required = [
        EXPERIENCE / "index.html",
        EXPERIENCE / "share-card-1080x1350.png",
        VIDEO / "prooflaunch-claim-trial-vertical-4k.mp4",
        *[ROOT / row["master"]["project_relative_path"] for row in audio["candidates"]],
    ]
    if any(not path.is_file() for path in required):
        raise SystemExit("a bound campaign asset is missing")
    OUTPUT.mkdir(parents=True)
    post = launch["linkedin_post"]
    body = "\n\n".join(post["body"])
    voices = "".join(
        f'''<article><small>{row["candidate_id"]}</small><audio controls preload="metadata" src="../claim-trial-audio-v1/master/{Path(row["master"]["project_relative_path"]).name}"></audio><p>15s · 48 kHz · 24-bit · human listening review pending</p></article>'''
        for row in audio["candidates"]
    )
    lanes = [
        ("Cross-device memory", "Claim + source + limitation + verdict becomes one versioned memory unit."),
        ("Data strategy", "Risk signals and evidence sufficiency determine what question earns the next collection cycle."),
        ("Content scheduling", "LinkedIn self-trial → vertical demonstration → source-ready answer page; no calendar filler."),
        ("Image", "1080×1350 verdict card makes the missing proof screenshotable."),
        ("Video", "15-second 4K vertical claim → verdict → bounded rewrite narrative."),
        ("Audio", "Three local VoiceDesign readings share one frozen script; selection remains human."),
        ("Copy", "The product rejection is the hook; the exact missing proof is the body; retrial is the CTA."),
        ("Analytics", "Primary events: trial completed, verdict saved/shared, witness supplied, retrial completed."),
        ("GEO", "Resolved claim becomes a direct-answer object with named source and visible limitation."),
        ("SEO", "Each retriable claim can become a canonical evidence page rather than thin keyword copy."),
        ("Employee Agent", "The agent refuses its own unsupported superiority and virality language."),
        ("Advertising", "The same conflict can become a creative challenger; activation/spend remains disabled."),
        ("GTM lifecycle", "Claim → cross-examination → bounded rewrite → human release → observation → retrial."),
    ]
    lane_html = "".join(f"<article><small>{i:02d}</small><h3>{name}</h3><p>{text}</p></article>" for i, (name, text) in enumerate(lanes, 1))
    page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim Trial — Campaign Board</title><style>
:root{{--ink:#090908;--paper:#f1eee5;--red:#ff563f;--acid:#e8ff36;--blue:#3d5afe;--line:#aaa69b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.42 Inter,system-ui,sans-serif}}.wrap{{width:min(1480px,calc(100% - 40px));margin:auto}}nav{{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}}nav span,small,.kicker{{font:800 11px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase}}header{{padding:76px 0 58px}}h1{{font-size:clamp(64px,10vw,150px);line-height:.82;letter-spacing:-.08em;margin:20px 0}}h1 em{{font-style:normal;color:var(--red)}}.lead{{font-size:clamp(23px,3vw,40px);line-height:1.1;max-width:1060px}}.stats{{display:grid;grid-template-columns:repeat(5,1fr);border:2px solid var(--ink);margin-top:45px}}.stats div{{padding:22px;border-right:1px solid var(--ink)}}.stats div:last-child{{border:0}}.stats b{{display:block;font-size:42px}}section{{padding:64px 0;border-top:1px solid var(--line)}}.head{{display:grid;grid-template-columns:1fr 1.2fr;gap:28px;margin-bottom:32px}}h2{{font-size:clamp(44px,6vw,84px);line-height:.9;letter-spacing:-.06em;margin:0}}.head p{{font-size:21px;margin:0}}.hero-grid{{display:grid;grid-template-columns:1.55fr .65fr;gap:14px}}iframe{{width:100%;height:900px;border:2px solid var(--ink);background:white}}video{{display:block;width:100%;max-height:900px;background:var(--ink);border:2px solid var(--ink)}}.asset-grid{{display:grid;grid-template-columns:.72fr 1.28fr;gap:14px}}.asset-grid img{{width:100%;border:2px solid var(--ink)}}.copy{{border:2px solid var(--ink);padding:32px;background:#faf8f2}}.copy h3{{font-size:34px;margin:20px 0}}.copy p{{white-space:pre-line;font-size:18px}}.copy .cta{{background:var(--acid);border:2px solid var(--ink);padding:18px;font-weight:850}}.voices{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.voices article{{border:2px solid var(--ink);padding:20px}}audio{{width:100%;margin:26px 0 5px}}.lanes{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.lanes article{{border:1px solid var(--line);padding:22px;min-height:200px;background:#faf8f2}}.lanes article:nth-child(3n+1){{border-top:8px solid var(--red)}}.lanes article:nth-child(3n+2){{border-top:8px solid var(--blue)}}.lanes article:nth-child(3n){{border-top:8px solid var(--acid)}}.lanes h3{{font-size:23px;margin:32px 0 8px}}.boundary{{background:var(--ink);color:white;padding:34px;font-size:22px}}footer{{padding:50px 0 80px;color:#666}}@media(max-width:850px){{.stats,.hero-grid,.asset-grid,.voices,.lanes,.head{{grid-template-columns:1fr}}iframe{{height:760px}}.stats div{{border-right:0;border-bottom:1px solid var(--ink)}}}}
</style></head><body><nav class="wrap"><strong>ProofLaunch / Claim Trial</strong><span>Front-stage challenger · Aug 03</span></nav><header><div class="wrap"><div class="kicker">One product demonstration, not forty disconnected assets</div><h1>It refused to call itself <em>4A.</em></h1><p class="lead">The launch is a public self-cross-examination: ProofLaunch rejects its own unsupported promise, shows the missing witnesses, and invites the audience to try their claim.</p><div class="stats"><div><b>1</b><small>self-claim rejected</small></div><div><b>3</b><small>local voice candidates</small></div><div><b>4K</b><small>vertical master</small></div><div><b>0</b><small>external publishes</small></div><div><b>0</b><small>observed effects</small></div></div></div></header><main><section><div class="wrap"><div class="head"><h2>The product is the content.</h2><p>Try the exact interaction on the left. The same conflict becomes the fifteen-second native story on the right.</p></div><div class="hero-grid"><iframe src="../claim-trial-experience-v1/index.html" title="Interactive Claim Trial"></iframe><video controls playsinline preload="metadata" poster="../claim-trial-video-v1/audit-frames/frame-6.2.png"><source src="../claim-trial-video-v1/prooflaunch-claim-trial-vertical-4k.mp4" type="video/mp4"></video></div></div></section><section><div class="wrap"><div class="head"><h2>The launch unit.</h2><p>One screenshotable verdict and one platform-native post. No “AI agent” feature inventory.</p></div><div class="asset-grid"><img src="../claim-trial-experience-v1/share-card-1080x1350.png" alt="Claim Trial NO WITNESS share card"><div class="copy"><small>LinkedIn launch post</small><h3>{post['hook']}</h3><p>{body}</p><div class="cta">{post['cta']}</div></div></div></div></section><section><div class="wrap"><div class="head"><h2>Choose the human delivery.</h2><p>All three voices were generated offline on Apple Metal from the same frozen script. Mechanical mastering passed; human listening preference has not.</p></div><div class="voices">{voices}</div></div></section><section><div class="wrap"><div class="head"><h2>One nucleus. Thirteen jobs.</h2><p>The capabilities below are consequences of the same claim–evidence–verdict object. They are not thirteen separate feature demos.</p></div><div class="lanes">{lane_html}</div></div></section><section><div class="wrap boundary">This is a local creative challenger. It does not prove human preference, organic breakout, 4A quality, named-product superiority, conversion, pipeline or revenue. Named-product PK remains 0/130 until authorized same-brief opponent outputs and five independent human reviews per row exist.</div></section></main><footer><div class="wrap">No network call · no automatic publishing · no spend authority · every bound file is content-addressed in its source receipt.</div></footer></body></html>'''
    index = OUTPUT / "index.html"
    index.write_text(page, encoding="utf-8")
    payload = {
        "schema": "ProofLaunchClaimTrialCampaignBoardReceiptV1",
        "front_stage_concept": "Claim Trial",
        "index": {"path": str(index.relative_to(ROOT)), "sha256": digest(index)},
        "bound_assets": [{"path": str(path.relative_to(ROOT)), "sha256": digest(path), "bytes": path.stat().st_size} for path in required],
        "capability_lane_count": len(lanes),
        "external_publish_count": 0,
        "observed_effect_count": 0,
        "completed_named_product_pk_count": 0,
        "named_product_win_count": 0,
        "truth_boundary": "Local execution board only; no preference, virality, conversion, revenue, 4A or named-product superiority claim."
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt = {**payload, "content_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(index), "bound_asset_count": len(required), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
