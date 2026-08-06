from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BRIEF = ROOT / "evidence/v10/prooflaunch-front-stage-brief-v1.json"
SOURCE_BASELINE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen-image/qwen-image-2512-raw-baseline.png"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-v2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(payload: dict) -> dict:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**payload, "content_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    if not SOURCE_BASELINE.is_file():
        raise FileNotFoundError(SOURCE_BASELINE)
    brief = json.loads(SOURCE_BRIEF.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True)

    card = '''<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1350px;overflow:hidden}body{background:#080a08;color:#f3eedf;font-family:Arial,Helvetica,sans-serif;padding:54px 58px 48px;display:flex;flex-direction:column;position:relative}body:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 86% 14%,rgba(220,255,33,.11),transparent 28%),repeating-linear-gradient(115deg,rgba(255,255,255,.018) 0 1px,transparent 1px 7px);pointer-events:none}.top{position:relative;z-index:1;display:flex;justify-content:space-between;border-bottom:2px solid #76776f;padding-bottom:16px;font:900 19px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.08em}.charge{position:relative;z-index:1;margin-top:44px;font:900 17px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.14em;color:#d9ff28}.claim{position:relative;z-index:1;margin:18px 0 0;font-size:116px;line-height:.82;letter-spacing:-.075em;font-weight:950}.claim em{font-style:normal;color:#d9ff28}.source{position:relative;z-index:1;margin:30px 0 0;border-left:8px solid #d9ff28;padding:5px 0 5px 22px;font:700 27px/1.12 ui-monospace,SFMono-Regular,monospace;max-width:900px}.turn{position:relative;z-index:1;margin:36px 0 0;font-size:42px;line-height:1;font-weight:950;letter-spacing:-.035em}.verdict{position:relative;z-index:1;margin:22px 0 26px auto;width:700px;background:#ff543e;color:#080a08;border:4px solid #f3eedf;padding:27px 32px;text-align:center;font-size:83px;line-height:.86;font-weight:950;letter-spacing:-.045em;transform:rotate(-2deg)}.docket{position:relative;z-index:1;border-top:2px solid #76776f;border-bottom:2px solid #76776f;display:grid;grid-template-columns:repeat(3,1fr);padding:24px 0}.metric{padding:0 20px;border-right:1px solid #76776f}.metric:first-child{padding-left:0}.metric:last-child{border:0}.metric b{display:block;color:#d9ff28;font-size:58px;line-height:.9}.metric span{display:block;margin-top:11px;font:800 15px/1.17 ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.05em}.kill{position:relative;z-index:1;margin-top:30px;font-size:45px;line-height:.95;font-weight:950;letter-spacing:-.04em}.kill s{color:#ff543e;text-decoration-thickness:7px}.cta{position:relative;z-index:1;margin-top:auto;background:#d9ff28;color:#080a08;padding:24px 28px;font:950 27px/1.08 ui-monospace,SFMono-Regular,monospace;letter-spacing:-.02em}.micro{position:relative;z-index:1;margin-top:14px;color:#9fa097;font:700 13px/1.2 ui-monospace,SFMono-Regular,monospace}
</style></head><body><div class="top"><span>PROOFLAUNCH / CLAIM TRIAL</span><span>SELF-TRIAL 002</span></div><div class="charge">THE CLAIM</div><h1 class="claim">OUR AI<br><em>PROMISED</em><br>VIRAL.</h1><div class="source">“A 4A-grade GTM employee that makes any brand go viral.”</div><div class="turn">SO WE MADE IT TESTIFY.</div><div class="verdict">NO WITNESS</div><div class="docket"><div class="metric"><b>0</b><span>independent wins entered</span></div><div class="metric"><b>0</b><span>organic breakouts observed</span></div><div class="metric"><b>0</b><span>conversions attributed</span></div></div><div class="kill">WE <s>KILLED THE CLAIM</s><br>KEPT THE PRODUCT.</div><div class="cta">DROP THE HOMEPAGE LINE YOU TRUST LEAST →</div><div class="micro">CURRENT EVIDENCE RECORD · NOT A PERFORMANCE OR VIRALITY CLAIM</div></body></html>'''
    card_path = OUTPUT / "claim-trial-v2-1080x1350.html"
    card_path.write_text(card, encoding="utf-8")

    launch_pack = {
        "schema": "ProofLaunchClaimTrialCreativeLaunchPackV2",
        "organizing_idea": "Our AI promised viral. We made it testify.",
        "primary_channel": "LinkedIn",
        "primary_post": {
            "hook": "Our AI promised virality. We made it testify.",
            "body": [
                "It wrote the line every AI marketing product wants on its homepage: ‘A 4A-grade GTM employee that makes any brand go viral.’",
                "Then we asked for the witnesses: one independent preference win, one observed organic breakout, one attributed conversion, one dollar of proven revenue.",
                "It had none. So we killed the sentence—in public.",
                "That is the product demo. ProofLaunch does not help unsupported copy travel faster. It makes the claim name its evidence, population, period and limitation before a human decides what ships.",
                "If your AI will not challenge your claim, it is not your GTM employee. It is your hype intern.",
            ],
            "conversation_cta": "Drop the line on your homepage you trust least. We will return the docket—not a softer synonym.",
            "reply_protocol": [
                "Acknowledge the exact claim without mocking the submitter.",
                "Name the single most decision-changing missing witness.",
                "Offer one bounded rewrite only when the supplied evidence supports it.",
                "Never imply publication, virality, conversion or legal approval.",
            ],
        },
        "x_post": "Our AI wrote: ‘makes any brand go viral.’ We made it testify. 0 independent wins entered. 0 organic breakouts observed. 0 conversions attributed. Verdict: NO WITNESS. We killed the claim, kept the product. What line on your homepage would fail cross-examination?",
        "short_video": {
            "duration_seconds": 15,
            "beats": [
                {"seconds": "0-2", "onscreen": "OUR AI PROMISED VIRAL.", "voice": "Our AI promised viral."},
                {"seconds": "2-5", "onscreen": "SO WE MADE IT TESTIFY.", "voice": "So we asked it for one witness."},
                {"seconds": "5-9", "onscreen": "0 wins · 0 breakouts · 0 conversions", "voice": "No independent win. No organic breakout. No attributed conversion."},
                {"seconds": "9-12", "onscreen": "NO WITNESS", "voice": "Verdict: no witness."},
                {"seconds": "12-15", "onscreen": "DROP THE LINE YOU TRUST LEAST", "voice": "Which line on your homepage would fail?"},
            ],
        },
        "organic_loop": {
            "input": "One voluntarily submitted homepage claim plus any evidence the submitter chooses to provide.",
            "return": "A private claim docket first; public use requires explicit human approval and identity choice.",
            "share_trigger": "The verdict is useful even when negative because it names the next proof asset to earn.",
            "series_format": "Claim Trial #NNN: claim, verdict, one missing witness, one bounded rewrite.",
            "learning_signal": "Save/share rate, qualified claim submissions, evidence-source completion and return submission—not raw impressions alone.",
        },
        "truth_boundary": brief["truth_boundary"],
    }
    launch_path = OUTPUT / "launch-pack-v2.json"
    launch_path.write_text(json.dumps(launch_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = seal(
        {
            "schema": "ProofLaunchClaimTrialCreativeReceiptV2",
            "source_brief_sha256": digest(SOURCE_BRIEF),
            "source_baseline_sha256": digest(SOURCE_BASELINE),
            "cross_pollinated_observations": [
                "Preserve the local baseline's dark, high-contrast, oversized-type stopping power.",
                "Remove its unauthorized extra line, duplicate footer and ambiguous hierarchy.",
                "Replace insider-first 4A framing with a universal AI-promised-viral conflict while retaining the exact source claim.",
                "Add a response-worthy audience invitation rather than a generic product CTA.",
            ],
            "card_html": {"path": str(card_path.relative_to(ROOT)), "sha256": digest(card_path)},
            "launch_pack": {"path": str(launch_path.relative_to(ROOT)), "sha256": digest(launch_path)},
            "status": "creative_candidate_not_promoted_pending_human_preference_and_live_effect_evidence",
            "network_calls": 0,
            "external_publish_executed": False,
            "human_preference_observed": False,
            "production_effect_observed": False,
            "truth_boundary": brief["truth_boundary"],
        }
    )
    receipt_path = OUTPUT / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
