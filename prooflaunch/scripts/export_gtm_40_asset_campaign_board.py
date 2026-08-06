#!/usr/bin/env python3
"""Export one reviewer-facing, evidence-bound GTM campaign board.

The board assembles existing last-mile artifacts. It does not call a model,
publish content, or turn mechanical admission into a quality/superiority claim.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/40-asset-campaign-board-v1"

EDITORIAL = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
B2C_EDITORIAL = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json"
FLIGHTBOOK = ROOT / "artifacts/gtm-last-mile-pk-v1/creative-alpha-flightbook-v1/creative-alpha-flightbook.json"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v3-40-asset-interview/audio-candidate-receipt.json"
IMAGE = ROOT / "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1/prooflaunch-rejection-rule-key-visual-v1.png"
DOSSIERS = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json"
PORTFOLIO = ROOT / "evidence/v10/named-product-pk-portfolio-v1.json"
REVIEW_KIT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v16/prooflaunch-platform-craft-review-kit-v1.zip"
CAROUSEL = ROOT / "artifacts/gtm-last-mile-pk-v1/carousel-challenger-v1-40-asset-interview/carousel-receipt.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return os.path.relpath(path, OUTPUT).replace(os.sep, "/")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def seal(payload: dict) -> dict:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**payload, "content_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def platform_card(row: dict, index: int) -> str:
    body = "".join(f"<li>{esc(item)}</li>" for item in row["body"])
    progression = "".join(f"<span>{esc(item)}</span>" for item in row["progression"])
    return f"""
      <article class="platform-card" id="surface-{esc(row['surface_id'])}">
        <div class="eyebrow"><span>{index:02d}</span>{esc(row['surface_id'].replace('_', ' '))}</div>
        <h3>{esc(row['campaign_platform'])}</h3>
        <blockquote>{esc(row['hook'])}</blockquote>
        <ol>{body}</ol>
        <div class="progression">{progression}</div>
        <dl>
          <dt>Participation</dt><dd>{esc(row['participation_mechanism'])}</dd>
          <dt>CTA</dt><dd>{esc(row['cta'])}</dd>
          <dt>Kill rule</dt><dd>{esc(row['falsifier'])}</dd>
        </dl>
      </article>"""


def main() -> dict:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing board: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    editorial = load(EDITORIAL)
    b2c_editorial = load(B2C_EDITORIAL)
    flightbook = load(FLIGHTBOOK)
    video = load(VIDEO)
    audio = load(AUDIO)
    dossiers = load(DOSSIERS)
    portfolio = load(PORTFOLIO)
    carousel = load(CAROUSEL)

    candidates = editorial["accepted_candidates"]
    b2c_candidates = b2c_editorial["accepted_candidates"]
    variants = {row["variant"]: row for row in video["variants"]}
    audio_candidates = audio["candidates"]
    team = flightbook["team_operating_system"]

    landscape = ROOT / variants["landscape_4k"]["video"]["path"]
    vertical = ROOT / variants["vertical_4k"]["video"]["path"]
    platform_cards = "".join(platform_card(row, i) for i, row in enumerate(candidates, 1))
    b2c_platform_cards = "".join(platform_card(row, i) for i, row in enumerate(b2c_candidates, 1))
    audio_cards = "".join(
        f"""
        <article class="audio-card">
          <div class="eyebrow">{esc(row['candidate_id'])}</div>
          <h3>{esc(row.get('voice_direction', row['candidate_id']))}</h3>
          <audio controls preload="metadata" src="{esc(rel(ROOT / row['master']['project_relative_path']))}"></audio>
          <p>{esc(row.get('voice_direction', 'Local voice direction preserved in receipt.'))}</p>
          <small>{esc(row['master']['sample_rate_hz'])} Hz · {esc(row['master']['channels'])} ch · {esc(row['master']['duration_seconds'])} s</small>
        </article>"""
        for row in audio_candidates
    )
    category_rows = "".join(
        f"""
        <tr>
          <td>{esc(row['category_id'].replace('_', ' '))}</td>
          <td>{esc(row['reference_product_count'])}</td>
          <td>{esc(row['completed_product_pk_rows'])}</td>
          <td>{esc(row['candidate_won_product_pk_rows'])}</td>
          <td>awaiting authorized same-brief baseline + five-person blind review</td>
        </tr>"""
        for row in portfolio["categories"]
    )
    dossier_links = "".join(
        f"<a href=\"{esc(rel(ROOT / row['dossier']['project_relative_path']))}\">{esc(row['category_id'].replace('_', ' '))}</a>"
        for row in dossiers["categories"]
    )

    source_bindings = []
    for path, role in [
        (EDITORIAL, "13-surface editorial receipt"),
        (B2C_EDITORIAL, "13-surface B2C contrast-case receipt"),
        (FLIGHTBOOK, "B2B/B2C creative operating system"),
        (VIDEO, "dual-aspect 4K video receipt"),
        (AUDIO, "three-direction local audio receipt"),
        (IMAGE, "rights-clear key visual"),
        (DOSSIERS, "13-category challenger dossier manifest"),
        (PORTFOLIO, "130-row PK state"),
        (REVIEW_KIT, "five-reviewer source-hidden craft kit"),
        (CAROUSEL, "eight-slide 4:5 editorial carousel receipt"),
    ]:
        source_bindings.append(
            {"role": role, "path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size}
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ProofLaunch — The 40-Asset Interview</title>
  <style>
    :root{{--ink:#10100f;--paper:#f2efe8;--lime:#dfff4f;--coral:#ff6b4a;--blue:#4267ff;--line:#c9c5bb;--muted:#64625c}}
    *{{box-sizing:border-box}} html{{scroll-behavior:smooth}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
    a{{color:inherit}} .wrap{{width:min(1480px,calc(100% - 40px));margin:auto}} .top{{position:sticky;top:0;z-index:5;background:rgba(242,239,232,.92);backdrop-filter:blur(16px);border-bottom:1px solid var(--line)}}
    nav{{height:62px;display:flex;align-items:center;justify-content:space-between;gap:20px}} nav strong{{letter-spacing:-.03em}} nav div{{display:flex;gap:18px;font-size:13px;text-transform:uppercase;letter-spacing:.08em}}
    header{{padding:86px 0 48px;border-bottom:1px solid var(--line)}} .kicker,.eyebrow{{font:700 12px/1.2 ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.1em}}
    h1{{font-size:clamp(54px,9vw,136px);line-height:.86;letter-spacing:-.075em;margin:24px 0;max-width:1180px}} .lede{{font-size:clamp(19px,2.4vw,34px);line-height:1.12;max-width:1040px;margin:0}}
    .status{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-top:54px}} .status div{{background:var(--paper);padding:20px}} .status b{{display:block;font-size:30px;letter-spacing:-.05em}} .status small{{color:var(--muted)}}
    section{{padding:64px 0;border-bottom:1px solid var(--line)}} .section-head{{display:grid;grid-template-columns:1fr 2fr;gap:24px;margin-bottom:34px}} h2{{font-size:clamp(36px,5vw,72px);letter-spacing:-.055em;line-height:.95;margin:0}} .section-head p{{font-size:20px;max-width:800px;margin:0}}
    .spine{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}} .spine article{{min-height:260px;padding:24px;border:1px solid var(--ink);display:flex;flex-direction:column;justify-content:space-between}} .spine article:nth-child(1){{background:var(--lime)}} .spine article:nth-child(4){{background:var(--ink);color:white}} .spine strong{{font-size:42px;letter-spacing:-.05em}} .media-grid{{display:grid;grid-template-columns:1.65fr .8fr;gap:18px}} video,img{{width:100%;display:block;background:#000}} .vertical{{max-height:720px;object-fit:contain}} .media-meta{{padding:14px 0;color:var(--muted);font-size:13px}}
    .audio-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} .audio-card{{border:1px solid var(--line);padding:20px}} audio{{width:100%;margin:20px 0}} .platform-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}} .platform-card{{padding:26px;border:1px solid var(--line);background:#f8f6f0}} .platform-card h3{{font-size:29px;line-height:1;margin:16px 0}} blockquote{{font-size:22px;line-height:1.15;border-left:7px solid var(--coral);margin:18px 0;padding-left:18px}} .platform-card ol{{padding-left:20px}} .platform-card li{{margin:10px 0}} .progression{{display:flex;gap:6px;flex-wrap:wrap;margin:18px 0}} .progression span{{border:1px solid var(--line);border-radius:99px;padding:6px 10px;font-size:11px}} dl{{display:grid;grid-template-columns:100px 1fr;gap:8px 14px;margin-top:20px;font-size:13px}} dt{{font-weight:800;text-transform:uppercase}} dd{{margin:0;color:var(--muted)}}
    .metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--ink);border:1px solid var(--ink)}} .metrics div{{background:var(--paper);padding:26px}} .metrics b{{display:block;font-size:40px}} table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:12px;text-align:left}} th{{text-transform:uppercase;font-size:11px}} .warning{{background:var(--ink);color:white;padding:26px;font-size:20px}} .links{{display:flex;flex-wrap:wrap;gap:8px}} .links a{{border:1px solid var(--line);padding:9px 12px;text-decoration:none}} footer{{padding:46px 0 80px;color:var(--muted)}}
    @media(max-width:900px){{.status,.spine,.metrics{{grid-template-columns:repeat(2,1fr)}}.media-grid,.platform-grid,.audio-grid,.section-head{{grid-template-columns:1fr}} nav div{{display:none}}}}
  </style>
</head>
<body>
  <div class="top"><nav class="wrap"><strong>ProofLaunch / Campaign Board 01</strong><div><a href="#strategy">Strategy</a><a href="#film">Film</a><a href="#copy">B2B 13</a><a href="#b2c">B2C 13</a><a href="#pk">PK state</a></div></nav></div>
  <header><div class="wrap">
    <div class="kicker">B2B zero-budget launch · clean-room challenger · human release required</div>
    <h1>The 40-Asset<br>Interview</h1>
    <p class="lede">Don’t ask an AI GTM employee to make 40 launch assets. Ask it which 39 it would refuse to ship.</p>
    <div class="status"><div><b>26/26</b><small>B2B + B2C platform drafts admitted</small></div><div><b>2×4K</b><small>landscape + vertical B2B masters</small></div><div><b>3</b><small>local Qwen3-TTS voice directions</small></div><div><b>0/130</b><small>named-product PK completed</small></div><div><b>0</b><small>publish / send / spend actions</small></div></div>
  </div></header>

  <main>
    <section id="strategy"><div class="wrap">
      <div class="section-head"><h2>One creative spine.<br>Thirteen native executions.</h2><p>The wedge is refusal quality, not asset volume. Every execution turns claim provenance into a useful operator action while preserving the same proof boundary.</p></div>
      <div class="spine"><article><div class="eyebrow">01 / Tension</div><strong>40 polished cards</strong><p>Volume looks impressive even when the underlying claim is unsupported.</p></article><article><div class="eyebrow">02 / Mechanism</div><strong>4 claim states</strong><p>FACT · INFERENCE · HYPOTHESIS · BLOCKED</p></article><article><div class="eyebrow">03 / Decision</div><strong>39 refused</strong><p>Unsupported output becomes useful rejection work rather than publishable collateral.</p></article><article><div class="eyebrow">04 / Release</div><strong>1 earns review</strong><p>A source-bound card reaches a named human. Nothing auto-publishes.</p></article></div>
    </div></section>

    <section id="film"><div class="wrap">
      <div class="section-head"><h2>Dual-aspect 4K proof film</h2><p>One 14.72-second, three-beat film is rendered for landscape and vertical surfaces with the dedicated local voice master and content-addressed receipts.</p></div>
      <div class="media-grid"><div><video controls preload="metadata" poster="{esc(rel(ROOT / variants['landscape_4k']['audit_frames'][0]['path']))}" src="{esc(rel(landscape))}"></video><div class="media-meta">3840×2160 · SHA-256 {esc(variants['landscape_4k']['video']['sha256'][:16])}…</div></div><div><video class="vertical" controls preload="metadata" poster="{esc(rel(ROOT / variants['vertical_4k']['audit_frames'][0]['path']))}" src="{esc(rel(vertical))}"></video><div class="media-meta">2160×3840 · SHA-256 {esc(variants['vertical_4k']['video']['sha256'][:16])}…</div></div></div>
    </div></section>

    <section><div class="wrap"><div class="section-head"><h2>Three voice directions</h2><p>The selected interrogator route is a mechanical director choice, not a claimed human-preference win. All masters remain available for source-hidden listening.</p></div><div class="audio-grid">{audio_cards}</div></div></section>

    <section><div class="wrap"><div class="section-head"><h2>Rights-clear key visual</h2><p>The same refusal system carries into a platform crop without borrowing named-product trade dress.</p></div><img loading="lazy" src="{esc(rel(IMAGE))}" alt="ProofLaunch rejection rule key visual"></div></section>

    <section id="carousel"><div class="wrap"><div class="section-head"><h2>Eight-slide editorial carousel</h2><p>A complete 4:5 narrative moves from category reversal to a reusable four-line interview. The contact sheet and PDF are hash-bound; human preference remains unobserved.</p></div><img loading="lazy" src="{esc(rel(ROOT / carousel['contact_sheet']['path']))}" alt="Eight-slide 40-Asset Interview carousel contact sheet"><div class="links" style="margin-top:16px"><a href="{esc(rel(ROOT / carousel['pdf']['path']))}">open carousel PDF</a><a href="{esc(rel(CAROUSEL))}">carousel receipt</a></div></div></section>

    <section id="copy"><div class="wrap"><div class="section-head"><h2>Platform-native copy room</h2><p>Each draft has a different information shape, participation mechanic and kill rule. Shared evidence spine; no copy-and-paste syndication.</p></div><div class="platform-grid">{platform_cards}</div></div></section>

    <section id="b2c"><div class="wrap"><div class="section-head"><h2>B2C contrast case:<br>The Anti-Streak Memory Ritual</h2><p>A different audience, category tension and participation contract: one private daily detail, no streak pressure, no required audience, and a weekly artifact the owner may reject. These are capability references, not published product claims.</p></div><div class="spine"><article><div class="eyebrow">01 / Tension</div><strong>Memory became performance</strong><p>Capture is easy; deciding what deserves an audience creates hidden work.</p></article><article><div class="eyebrow">02 / Constraint</div><strong>One ordinary detail</strong><p>No blank-page essay, no public reveal and no emotional transformation promise.</p></article><article><div class="eyebrow">03 / Ritual</div><strong>Seven private choices</strong><p>A missed day does not reset, punish or score the user.</p></article><article><div class="eyebrow">04 / Payoff</div><strong>One optional review</strong><p>Usefulness is judged by the owner; outcome remains unobserved until tested.</p></article></div><div class="platform-grid" style="margin-top:18px">{b2c_platform_cards}</div></div></section>

    <section><div class="wrap"><div class="section-head"><h2>GTM team encoded as reviewable work</h2><p>These are operating contracts, not headcount theater: every role binds work products, gates, human craft review and observed-effect requirements.</p></div><div class="metrics"><div><b>{esc(team['role_count'])}</b>roles</div><div><b>{esc(team['professional_skill_card_count'])}</b>skill cards</div><div><b>{esc(team['eval_check_count'])}</b>evaluation checks</div><div><b>{esc(team['kpi_binding_count'])}</b>KPI bindings</div></div></div></section>

    <section id="pk"><div class="wrap"><div class="section-head"><h2>Named-product PK state</h2><p>Every category has a complete challenger dossier. No named-product win is recorded until an authorized same-brief baseline and five independent source-hidden reviews exist.</p></div><table><thead><tr><th>Category</th><th>Targets</th><th>Completed</th><th>Wins</th><th>Current gate</th></tr></thead><tbody>{category_rows}</tbody></table><div class="warning">Truth boundary: 13/13 means mechanically admitted to human comparison. It does not mean 13 categories aligned, 130 products beaten, 4A quality proven, or market effect observed.</div></div></section>

    <section><div class="wrap"><div class="section-head"><h2>Open the evidence</h2><p>Every artifact below is local, inspectable and hash-bound. The reviewer kit contains empty source-hidden forms; no reviewer response is fabricated.</p></div><div class="links">{dossier_links}<a href="{esc(rel(REVIEW_KIT))}">five-reviewer kit (.zip)</a><a href="board-receipt.json">board receipt</a></div></div></section>
  </main>
  <footer><div class="wrap">Generated from existing ProofLaunch artifacts. No network call, model call, publication, external action, conversion or revenue claim is performed by this board.</div></footer>
</body>
</html>
"""

    index = OUTPUT / "index.html"
    index.write_text(page, encoding="utf-8")
    receipt = seal(
        {
            "schema": "ProofLaunchGTM40AssetCampaignBoardReceiptV1",
            "board": {"path": str(index.relative_to(ROOT)), "sha256": sha256(index), "bytes": index.stat().st_size},
            "creative_concept": video["creative_concept"],
            "surface_count": len(candidates),
            "b2c_surface_count": len(b2c_candidates),
            "total_platform_candidate_count": len(candidates) + len(b2c_candidates),
            "mechanically_admitted_category_count": dossiers["admitted_category_count"],
            "reference_product_row_count": portfolio["reference_product_row_count"],
            "completed_named_product_pk_count": portfolio["completed_product_pk_rows"],
            "candidate_win_count": portfolio["candidate_won_product_pk_rows"],
            "human_review_completed": False,
            "production_effect_observed": False,
            "external_action_count": 0,
            "source_bindings": source_bindings,
            "truth_boundary": "This board makes one campaign system directly reviewable. It does not prove human preference, named-product superiority, 4A quality, organic breakout, conversion or revenue.",
        }
    )
    receipt_path = OUTPUT / "board-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(index), "total_platform_candidate_count": len(candidates) + len(b2c_candidates), "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
