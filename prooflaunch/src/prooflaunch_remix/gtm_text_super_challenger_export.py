from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text, sha256_file
from .gtm_text_named_pk_challenger import verify_row_portfolio


EXPORT_SCHEMA = "ProofLaunchTextSuperChallengerExportV1"


class TextSuperChallengerExportError(ValueError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _asset_text(asset: Mapping[str, Any]) -> str:
    ordered = []
    for key, value in asset.items():
        if key == "release_state":
            continue
        if isinstance(value, list):
            rendered = " · ".join(str(item) for item in value)
        else:
            rendered = str(value)
        ordered.append(f"{key.replace('_', ' ').title()}: {rendered}")
    return "\n\n".join(ordered)


def _review_html(candidate: Mapping[str, Any]) -> str:
    core = candidate["strategic_core"]
    cards = []
    labels = {
        "linkedin": "LinkedIn field note",
        "partner_community": "Partner-community teardown",
        "landing_hero": "Landing hero",
        "lifecycle_email": "Lifecycle email",
    }
    for asset_id, label in labels.items():
        body = html.escape(_asset_text(candidate["assets"][asset_id]))
        cards.append(f'<section><p class="kicker">{html.escape(label)}</p><pre>{body}</pre></section>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source-hidden four-asset GTM challenger</title><style>:root{{--bg:#080b12;--panel:#111725;--ink:#f3f6ff;--muted:#aeb8ce;--line:#303b54;--acid:#b6ff5f}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:42px 24px 72px}}header,section{{background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:28px;margin:0 0 22px}}h1{{max-width:820px;font-size:clamp(38px,6vw,76px);line-height:.96;letter-spacing:-.055em;margin:.2em 0}}h2{{font-size:24px}}.kicker{{color:var(--acid);font-size:13px;font-weight:850;letter-spacing:.14em;text-transform:uppercase}}.boundary{{color:var(--muted);border-left:4px solid var(--acid);padding-left:14px}}pre{{white-space:pre-wrap;font:15px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;color:#eef2fb}}dl{{display:grid;grid-template-columns:minmax(180px,.35fr) 1fr;gap:12px 20px}}dt{{color:var(--muted)}}dd{{margin:0}}</style></head><body><main>
<header><p class="kicker">Identity-hidden · same-brief candidate</p><h1>{html.escape(str(core['campaign_name']))}</h1><p>{html.escape(str(core['organizing_idea']))}</p><p class="boundary">Judge the work itself. This packet hides model, author and opponent identity; it contains no preference result, publication, market effect or superiority claim.</p></header>
<section><p class="kicker">Strategic spine</p><dl><dt>Human tension</dt><dd>{html.escape(str(core['human_tension']))}</dd><dt>Category enemy</dt><dd>{html.escape(str(core['category_enemy']))}</dd><dt>Mechanism</dt><dd>{html.escape(str(core['mechanism']))}</dd><dt>Participation loop</dt><dd>{html.escape(str(core['participation_loop']))}</dd><dt>Falsifier</dt><dd>{html.escape(str(core['falsifier']))}</dd></dl></section>
{''.join(cards)}</main></body></html>'''


def export_text_super_challenger(*, portfolio: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    verify_row_portfolio(portfolio)
    output = output_root.resolve()
    if output.exists() and any(output.iterdir()):
        raise TextSuperChallengerExportError("text challenger output must be empty")
    output.mkdir(parents=True, mode=0o700)
    candidate = portfolio["candidate"]
    claim = candidate["frozen_brief"]["approved_claim"]
    assets = candidate["assets"]
    creative_brief = {
        "schema": "ProofLaunchSourceHiddenCreativeBriefV1",
        "campaign_name": candidate["strategic_core"]["campaign_name"],
        "audience": candidate["frozen_brief"]["audience"],
        "objection": candidate["frozen_brief"]["objection"],
        "offer": candidate["frozen_brief"]["offer"],
        "voice": candidate["frozen_brief"]["voice"],
        "approved_claim": claim,
        "strategic_core": candidate["strategic_core"],
        "release_state": "draft_pending_named_human_review",
    }
    channel_copy = {
        "schema": "ProofLaunchSourceHiddenChannelCopyV1",
        "primary": assets["linkedin"],
        "secondary": assets["partner_community"],
        "approved_claim": claim,
        "release_state": "draft_pending_named_human_review",
    }
    landing = {
        "schema": "ProofLaunchSourceHiddenLandingHeroV1",
        "hero": assets["landing_hero"],
        "citation": {"approved_claim": claim, "candidate_sha256": candidate["content_sha256"]},
        "release_state": "draft_pending_named_human_review",
    }
    email = {
        "schema": "ProofLaunchSourceHiddenLifecycleEmailV1",
        "subject": assets["lifecycle_email"]["subject"],
        "preview": assets["lifecycle_email"]["preview"],
        "body_blocks": assets["lifecycle_email"]["body"].split("\n\n"),
        "cta": assets["lifecycle_email"]["cta"],
        "suppression": assets["lifecycle_email"]["suppression"],
        "citation": {"approved_claim": claim, "candidate_sha256": candidate["content_sha256"]},
        "release_state": "draft_pending_named_human_review",
    }
    payloads = {
        "creative-brief.json": creative_brief,
        "channel-copy.json": channel_copy,
        "landing-page-draft.json": landing,
        "lifecycle-email-draft.json": email,
    }
    for name, payload in payloads.items():
        _write_json(output / name, payload)
    atomic_write_text(output / "source-hidden-review-dossier.html", _review_html(candidate))
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(output.iterdir()) if path.is_file()
    }
    manifest = {
        "schema": EXPORT_SCHEMA,
        "candidate_sha256": candidate["content_sha256"],
        "source_portfolio_sha256": portfolio["content_sha256"],
        "asset_count": 4,
        "named_product_target_count": 10,
        "files": files,
        "provider_identity_exposed_in_review_dossier": False,
        "opponent_identity_exposed_in_review_dossier": False,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "release_eligible": False,
        "external_action_executed": False,
        "truth_boundary": "A source-hidden four-asset candidate is reviewable. No named baseline, human verdict, PK win, 4A proof, publication or market effect is present.",
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


__all__ = ["EXPORT_SCHEMA", "TextSuperChallengerExportError", "export_text_super_challenger"]
