from __future__ import annotations

import hashlib
import hmac
import io
import json
import random
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .files import atomic_write_text, sha256_file


PUBLIC_NAME = "campaign-pack-blind-review-public.json"
PRIVATE_NAME = "campaign-pack-blind-review-private.json"
AGGREGATE_NAME = "campaign-pack-blind-review-aggregate.json"
REVIEW_ATTESTATION = (
    "I independently reviewed the identity-hidden campaign packs; I did not use "
    "candidate, provider, model, private-mapping, or other-reviewer information."
)
DIMENSIONS = (
    "concept_originality",
    "information_hierarchy",
    "evidence_credibility",
    "cross_format_extensibility",
    "action_motivation",
)
_DIMENSION_RUBRIC = {
    "concept_originality": "A distinctive campaign idea rather than a generic technology or growth visual.",
    "information_hierarchy": "The eye reaches brand, promise, proof, and action in a clear intentional order.",
    "evidence_credibility": "Proof feels specific, legible, restrained, and trustworthy rather than decorative.",
    "cross_format_extensibility": "The idea remains coherent across hero, social, and landing formats without looking mechanically cropped.",
    "action_motivation": "The system creates an earned reason to inspect, challenge, or act without unsupported hype.",
}
_TASK_ID = re.compile(r"^campaign-pack-[0-9a-f]{20}-reviewer-[1-5]$")
_ASSET_ALIAS = re.compile(r"^asset-[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CampaignPackBlindReviewError(ValueError):
    pass


class CampaignPackBlindReviewAuthorizationError(CampaignPackBlindReviewError):
    pass


class CampaignPackBlindReviewConflictError(CampaignPackBlindReviewError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_ascii(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = _sha256(payload)
    return sealed


def _offline_review_html(task: Mapping[str, Any]) -> str:
    task_json = json.dumps(
        task,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    dimension_rows = "\n".join(
        f"""<fieldset><legend>{dimension.replace('_', ' ').title()}</legend>
<label><input required type="radio" name="dimension_{dimension}" value="left"> LEFT</label>
<label><input required type="radio" name="dimension_{dimension}" value="right"> RIGHT</label>
<label><input required type="radio" name="dimension_{dimension}" value="tie"> TIE</label></fieldset>"""
        for dimension in DIMENSIONS
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Identity-hidden campaign review</title>
<style>
:root{{color-scheme:light;--ink:#101828;--line:#cbd5e1;--muted:#475467;--accent:#155eef}}
*{{box-sizing:border-box}}body{{margin:0;background:#f8fafc;color:var(--ink);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:24px}}header,form{{background:white;border:1px solid var(--line);padding:20px}}
.systems{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}}section{{min-width:0;border:1px solid var(--line);padding:14px}}
figure{{margin:0 0 18px}}img{{display:block;width:100%;height:auto;border:1px solid var(--line)}}figcaption{{color:var(--muted);font-size:.82rem;margin-top:5px}}
fieldset{{margin:14px 0;border:1px solid var(--line)}}textarea,input[type=text]{{display:block;width:100%;padding:10px;margin-top:6px}}textarea{{min-height:110px}}
button{{border:0;background:var(--accent);color:white;padding:12px 18px;font-weight:700;cursor:pointer}}.boundary{{border-left:4px solid var(--accent);padding-left:12px;color:var(--muted)}}
@media(max-width:760px){{.systems{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><p><strong>ProofLaunch · independent human evidence</strong></p><h1>Identity-hidden campaign-system review</h1>
<p class="boundary">Review LEFT and RIGHT across all three formats. Candidate, provider, model, mapping, and other-reviewer identities are intentionally absent. This kit contains no invitation token and cannot publish or activate anything.</p>
<p>Task <code>{task['review_task_id']}</code> · pair SHA-256 <code>{task['pair_sha256']}</code></p></header>
<div id="systems" class="systems"></div>
<form id="review-form">
<label>Stable reviewer pseudonym<input required name="reviewer_pseudonym" type="text" minlength="3" maxlength="120"></label>
<fieldset><legend>Overall stronger production campaign system</legend>
<label><input required type="radio" name="overall_winner" value="left"> LEFT</label>
<label><input required type="radio" name="overall_winner" value="right"> RIGHT</label></fieldset>
{dimension_rows}
<fieldset><legend>Blocking production defect</legend>
<label><input required type="radio" name="blocking_defect_side" value="none"> NONE</label>
<label><input required type="radio" name="blocking_defect_side" value="left"> LEFT</label>
<label><input required type="radio" name="blocking_defect_side" value="right"> RIGHT</label>
<label><input required type="radio" name="blocking_defect_side" value="both"> BOTH</label></fieldset>
<label>Located blocking-defect reason (required unless NONE)<textarea name="blocking_defect_reason" maxlength="1200"></textarea></label>
<label>Independent rationale (24–2000 characters)<textarea required name="notes" minlength="24" maxlength="2000"></textarea></label>
<label><input required name="human_attestation" type="checkbox"> I independently reviewed this identity-hidden pair without candidate, provider, model, private-mapping, or other-reviewer information.</label>
<p><button type="submit">Download immutable review JSON</button></p>
<p id="status" aria-live="polite">Nothing has been submitted or transmitted.</p></form>
<script id="task-json" type="application/json">{task_json}</script>
<script>
const task=JSON.parse(document.getElementById("task-json").textContent);
const labels={{hero_4k:"4K hero",social_4x5:"4:5 social",landing_1080p:"1080p landing"}};
for(const side of ["left","right"]){{const section=document.createElement("section");section.innerHTML=`<h2>${{side.toUpperCase()}}</h2>`;for(const asset of task.pair.sides[side].assets){{const figure=document.createElement("figure"),img=document.createElement("img"),caption=document.createElement("figcaption");img.src=`assets/${{asset.asset_alias}}.png`;img.alt=`${{side}} ${{labels[asset.role]||asset.role}}`;caption.textContent=`${{labels[asset.role]||asset.role}} · ${{asset.width}}×${{asset.height}} · sha256:${{asset.sha256.slice(0,12)}}…`;figure.append(img,caption);section.append(figure)}}document.getElementById("systems").append(section)}}
const stable=(value)=>Array.isArray(value)?`[${{value.map(stable).join(",")}}]`:value&&typeof value==="object"?`{{${{Object.keys(value).sort().map((key)=>`${{JSON.stringify(key)}}:${{stable(value[key])}}`).join(",")}}}}`:JSON.stringify(value);
const hex=(buffer)=>Array.from(new Uint8Array(buffer),byte=>byte.toString(16).padStart(2,"0")).join("");
document.getElementById("review-form").addEventListener("submit",async(event)=>{{event.preventDefault();const data=new FormData(event.currentTarget);const defect=String(data.get("blocking_defect_side")||"");const reason=String(data.get("blocking_defect_reason")||"").trim();const notes=String(data.get("notes")||"").trim();if(notes.length<24||(defect!=="none"&&reason.length<16)){{document.getElementById("status").textContent="Complete the 24-character rationale and any located blocking-defect explanation.";return}}const review={{schema:"ProofLaunchCampaignPackVisualHumanReviewV1",review_task_id:task.review_task_id,pair_id:task.pair_id,pair_sha256:task.pair_sha256,reviewer_slot:task.reviewer_slot,reviewer_pseudonym:String(data.get("reviewer_pseudonym")||"").trim(),human_attestation:{json.dumps(REVIEW_ATTESTATION)},overall_winner:String(data.get("overall_winner")||""),dimension_winners:{{{','.join(json.dumps(dimension) + ':String(data.get(' + json.dumps('dimension_' + dimension) + ')||"")' for dimension in DIMENSIONS)}}},blocking_defect_side:defect,blocking_defect_reason:reason,notes,reviewed_at:new Date().toISOString()}};review.review_content_sha256=hex(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(review))));const blob=new Blob([JSON.stringify(review,null,2)+"\\n"],{{type:"application/json"}}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`campaign-pack-review-slot-${{task.reviewer_slot}}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);document.getElementById("status").textContent=`Review JSON downloaded · sha256:${{review.review_content_sha256}} · no network transmission occurred.`}});
</script></main></body></html>"""


def _write_deterministic_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    body: bytes,
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, body)


def _verify_seal(payload: Mapping[str, Any], *, label: str) -> None:
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or supplied != _sha256(unsigned):
        raise CampaignPackBlindReviewError(f"{label} content digest is invalid")


def _load_campaign_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CampaignPackBlindReviewError("campaign manifest must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "ProofLaunchLocalCampaignPackV1":
        raise CampaignPackBlindReviewError("campaign manifest schema is unsupported")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _sha256_ascii(unsigned):
        raise CampaignPackBlindReviewError("campaign manifest content digest is invalid")
    if payload.get("quality_gates", {}).get("mechanical_campaign_pack_ready") is not True:
        raise CampaignPackBlindReviewError("campaign pack is not mechanically ready")
    return payload


def compile_campaign_pack_blind_review_bundle(
    project_root: str | Path,
    output_root: str | Path,
    *,
    seed: int = 20260802,
    candidate_manifest_paths: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    project = Path(project_root).expanduser().resolve(strict=True)
    output = Path(output_root).expanduser().resolve()
    try:
        output.relative_to(project)
    except ValueError as error:
        raise CampaignPackBlindReviewError("review bundle must remain inside the project") from error
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise CampaignPackBlindReviewError("review bundle root cannot be a symlink")

    if candidate_manifest_paths is None:
        candidate_specs = (
            (
                "campaign-pack-v5",
                project / "evidence/v10/local-campaign-pack-v1/delivery-v5/campaign-pack-manifest.json",
            ),
            (
                "campaign-pack-v6",
                project / "evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json",
            ),
        )
    else:
        if len(candidate_manifest_paths) != 2:
            raise CampaignPackBlindReviewError(
                "campaign blind review requires exactly two candidate manifests"
            )
        resolved_manifests = [
            Path(path).expanduser().resolve(strict=True)
            for path in candidate_manifest_paths
        ]
        for path in resolved_manifests:
            try:
                path.relative_to(project)
            except ValueError as error:
                raise CampaignPackBlindReviewError(
                    "campaign candidate manifest escaped the project"
                ) from error
        candidate_specs = tuple(
            (f"campaign-pack-{path.parent.name}", path)
            for path in resolved_manifests
        )
        if len({candidate_id for candidate_id, _ in candidate_specs}) != 2:
            raise CampaignPackBlindReviewError(
                "campaign candidate identities must be distinct"
            )
    candidates: dict[str, dict[str, Any]] = {}
    asset_roles = {
        "hero_4k": "prooflaunch-hero-4k.png",
        "social_4x5": "prooflaunch-social-1080x1350.png",
        "landing_1080p": "prooflaunch-landing-1920x1080.png",
    }
    for candidate_id, manifest_path in candidate_specs:
        manifest = _load_campaign_manifest(manifest_path)
        manifest_assets = {
            str(row["path"]): row
            for row in manifest.get("artifacts", [])
            if isinstance(row, Mapping)
        }
        assets: dict[str, dict[str, Any]] = {}
        for role, filename in asset_roles.items():
            row = manifest_assets.get(filename)
            if not isinstance(row, Mapping):
                raise CampaignPackBlindReviewError(f"{candidate_id} is missing {role}")
            path = (manifest_path.parent / filename).resolve(strict=True)
            try:
                path.relative_to(project)
            except ValueError as error:
                raise CampaignPackBlindReviewError("campaign asset escaped the project") from error
            digest = sha256_file(path)
            if digest != row.get("sha256") or row.get("media_type") != "image/png":
                raise CampaignPackBlindReviewError(f"{candidate_id} {role} failed its digest/media gate")
            assets[role] = {
                "project_relative_path": str(path.relative_to(project)),
                "sha256": digest,
                "media_type": "image/png",
                "bytes": path.stat().st_size,
                "width": row.get("width"),
                "height": row.get("height"),
            }
        candidates[candidate_id] = {
            "manifest_path": str(manifest_path.relative_to(project)),
            "manifest_content_sha256": manifest["content_sha256"],
            "campaign_id": manifest["campaign"]["campaign_id"],
            "assets": assets,
        }

    rng = random.Random(seed)
    first_candidate_left_slots = set(rng.sample(range(1, 6), 3))
    public_tasks: list[dict[str, Any]] = []
    task_side_mapping: dict[str, dict[str, str]] = {}
    asset_bindings: dict[str, dict[str, Any]] = {}
    ids = tuple(candidates)
    for slot in range(1, 6):
        left_id, right_id = (ids[0], ids[1]) if slot in first_candidate_left_slots else (ids[1], ids[0])
        sides: dict[str, Any] = {}
        for side, candidate_id in (("left", left_id), ("right", right_id)):
            public_assets: list[dict[str, Any]] = []
            for role in asset_roles:
                source = candidates[candidate_id]["assets"][role]
                alias = "asset-" + hashlib.sha256(
                    f"{seed}:{slot}:{side}:{role}:{source['sha256']}".encode("utf-8")
                ).hexdigest()[:24]
                binding = {
                    "candidate_id": candidate_id,
                    "role": role,
                    **source,
                }
                asset_bindings[alias] = binding
                public_assets.append(
                    {
                        "asset_alias": alias,
                        "role": role,
                        "url": f"/v1/campaign-pack-blind-review/assets/{alias}",
                        "media_type": "image/png",
                        "sha256": source["sha256"],
                        "width": source["width"],
                        "height": source["height"],
                    }
                )
            sides[side] = {"assets": public_assets}
        pair = {
            "comparison_context": "One governed GTM campaign system shown in three delivery formats per side.",
            "sides": sides,
        }
        pair_sha256 = _sha256(pair)
        pair_id = f"campaign-pack-pair-{pair_sha256[:20]}"
        task_id = f"campaign-pack-{pair_sha256[:20]}-reviewer-{slot}"
        public_tasks.append(
            {
                "review_task_id": task_id,
                "pair_id": pair_id,
                "pair_sha256": pair_sha256,
                "reviewer_slot": slot,
                "pair": pair,
            }
        )
        task_side_mapping[task_id] = {"left": left_id, "right": right_id}

    private_core = {
        "randomization_seed": seed,
        "candidate_count": 2,
        "candidates": candidates,
        "task_side_mapping": task_side_mapping,
        "asset_bindings": asset_bindings,
    }
    private_commitment = _sha256(private_core)
    public_payload = {
        "schema": "ProofLaunchCampaignPackVisualBlindReviewPublicV1",
        "evaluation_id": "campaign-pack-challenger-visual-review-v1",
        "baseline": "previous mechanically ready campaign pack",
        "candidate_identity_exposed": False,
        "provider_identity_exposed": False,
        "model_identity_exposed": False,
        "private_mapping_exposed": False,
        "candidate_count": 2,
        "reviewer_slot_count": 5,
        "task_count": 5,
        "expected_review_count": 5,
        "private_mapping_commitment_sha256": private_commitment,
        "rubric": {
            "overall": "Choose LEFT or RIGHT as the stronger production campaign system; no tie is allowed for the overall decision.",
            "dimension_choices": ["left", "right", "tie"],
            "dimensions": [
                {"dimension": name, "definition": _DIMENSION_RUBRIC[name]}
                for name in DIMENSIONS
            ],
            "blocking_defect_choices": ["none", "left", "right", "both"],
            "blocking_defect_definition": "A factual, evidence, legibility, brand, safety, or production defect severe enough to block release.",
        },
        "predeclared_promotion_gate": {
            "minimum_overall_votes": 4,
            "minimum_total_reviews": 5,
            "recommended_candidate_blocking_defects": 0,
            "candidate_may_lose_dimension": False,
            "recommendation_only": True,
            "automatic_runtime_switch_enabled": False,
            "automatic_publish_enabled": False,
        },
        "review_tasks": public_tasks,
        "truth_boundary": (
            "A complete result measures preference for one campaign pair among five invited humans. "
            "It does not establish 4A/Top-1 standing, causal lift, revenue, production admission, "
            "Radeon execution, or permission to publish."
        ),
    }
    public_packet = _seal(public_payload)
    private_packet = _seal(
        {
            "schema": "ProofLaunchCampaignPackVisualBlindReviewPrivateV1",
            "public_packet_sha256": public_packet["content_sha256"],
            "private_mapping_commitment_sha256": private_commitment,
            "private_core": private_core,
        }
    )
    public_path = output / PUBLIC_NAME
    private_path = output / PRIVATE_NAME
    atomic_write_text(public_path, json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(private_path, json.dumps(private_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    public_path.chmod(0o644)
    private_path.chmod(0o600)
    return {
        "public_path": str(public_path),
        "private_path": str(private_path),
        "public_packet_sha256": public_packet["content_sha256"],
        "private_packet_sha256": private_packet["content_sha256"],
        "task_count": len(public_tasks),
        "expected_review_count": len(public_tasks),
    }


class CampaignPackBlindReviewService:
    def __init__(
        self,
        bundle_root: str | Path,
        *,
        project_root: str | Path,
        reviewer_tokens: Mapping[int, str] | None = None,
    ) -> None:
        self.root = Path(bundle_root).expanduser().resolve(strict=True)
        self.project_root = Path(project_root).expanduser().resolve(strict=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise CampaignPackBlindReviewError("campaign review root must be a real directory")
        self.public_path = self.root / PUBLIC_NAME
        self.private_path = self.root / PRIVATE_NAME
        if any(path.is_symlink() or not path.is_file() for path in (self.public_path, self.private_path)):
            raise CampaignPackBlindReviewError("campaign review bundle is incomplete")
        if self.private_path.stat().st_mode & 0o077:
            raise CampaignPackBlindReviewError("private campaign mapping must have mode 0600")
        self.public_packet = json.loads(self.public_path.read_text(encoding="utf-8"))
        self._private_packet = json.loads(self.private_path.read_text(encoding="utf-8"))
        self._verify_bundle()
        self._tasks = {
            str(task["review_task_id"]): task
            for task in self.public_packet["review_tasks"]
        }
        self._private_core = self._private_packet["private_core"]
        self.review_root = self.root / "human-reviews"
        self.review_root.mkdir(mode=0o700, exist_ok=True)
        self.review_root.chmod(0o700)
        self.aggregate_path = self.root / AGGREGATE_NAME
        supplied = reviewer_tokens or {}
        self._token_hashes = {
            int(slot): hashlib.sha256(str(token).encode("utf-8")).hexdigest()
            for slot, token in supplied.items()
            if int(slot) in range(1, 6) and len(str(token)) >= 24
        }
        self._lock = threading.RLock()

    def _verify_bundle(self) -> None:
        if self.public_packet.get("schema") != "ProofLaunchCampaignPackVisualBlindReviewPublicV1":
            raise CampaignPackBlindReviewError("public campaign review schema is unsupported")
        if self._private_packet.get("schema") != "ProofLaunchCampaignPackVisualBlindReviewPrivateV1":
            raise CampaignPackBlindReviewError("private campaign review schema is unsupported")
        _verify_seal(self.public_packet, label="public campaign review")
        _verify_seal(self._private_packet, label="private campaign review")
        core = self._private_packet.get("private_core")
        if not isinstance(core, Mapping):
            raise CampaignPackBlindReviewError("private campaign mapping is malformed")
        commitment = _sha256(core)
        if not (
            commitment == self.public_packet.get("private_mapping_commitment_sha256")
            == self._private_packet.get("private_mapping_commitment_sha256")
            and self._private_packet.get("public_packet_sha256")
            == self.public_packet.get("content_sha256")
        ):
            raise CampaignPackBlindReviewError("public/private campaign review binding is invalid")
        tasks = self.public_packet.get("review_tasks")
        if not isinstance(tasks, list) or len(tasks) != 5:
            raise CampaignPackBlindReviewError("campaign review requires five tasks")
        if {int(task.get("reviewer_slot", 0)) for task in tasks} != set(range(1, 6)):
            raise CampaignPackBlindReviewError("campaign review must assign one task per slot")
        for task in tasks:
            task_id = str(task.get("review_task_id", ""))
            if not _TASK_ID.fullmatch(task_id) or task.get("pair_sha256") != _sha256(task.get("pair")):
                raise CampaignPackBlindReviewError("campaign review task binding is invalid")
        if set(core.get("task_side_mapping", {})) != {str(task["review_task_id"]) for task in tasks}:
            raise CampaignPackBlindReviewError("private task mapping does not cover public tasks")
        for alias, binding in core.get("asset_bindings", {}).items():
            if not _ASSET_ALIAS.fullmatch(str(alias)) or not isinstance(binding, Mapping):
                raise CampaignPackBlindReviewError("private asset binding is malformed")
            path = (self.project_root / str(binding.get("project_relative_path", ""))).resolve(strict=True)
            try:
                path.relative_to(self.project_root)
            except ValueError as error:
                raise CampaignPackBlindReviewError("campaign asset escaped project root") from error
            if path.is_symlink() or not path.is_file() or sha256_file(path) != binding.get("sha256"):
                raise CampaignPackBlindReviewError("campaign review asset failed integrity validation")

    def _authorize(self, slot: int, token: str) -> None:
        expected = self._token_hashes.get(slot)
        observed = hashlib.sha256(token.encode("utf-8")).hexdigest() if isinstance(token, str) else ""
        if expected is None or not hmac.compare_digest(expected, observed):
            raise CampaignPackBlindReviewAuthorizationError("reviewer invitation is invalid for this slot")

    def _review_path(self, task_id: str) -> Path:
        if task_id not in self._tasks or not _TASK_ID.fullmatch(task_id):
            raise CampaignPackBlindReviewError("campaign review task identity is invalid")
        return self.review_root / f"{task_id}.json"

    def _load_reviews(self) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        for path in sorted(self.review_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise CampaignPackBlindReviewError("campaign review store contains an unsafe entry")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._validate_review(payload)
            if path != self._review_path(str(payload["review_task_id"])):
                raise CampaignPackBlindReviewError("persisted campaign review path is not task-bound")
            reviews.append(payload)
        return reviews

    def _validate_review(self, review: Mapping[str, Any]) -> None:
        required = {
            "schema", "review_task_id", "pair_id", "pair_sha256", "reviewer_slot",
            "reviewer_pseudonym", "human_attestation", "overall_winner",
            "dimension_winners", "blocking_defect_side", "blocking_defect_reason",
            "notes", "reviewed_at", "review_content_sha256",
        }
        if set(review) != required or review.get("schema") != "ProofLaunchCampaignPackVisualHumanReviewV1":
            raise CampaignPackBlindReviewError("campaign review schema or fields are invalid")
        task = self._tasks.get(str(review.get("review_task_id", "")))
        if task is None or not (
            review.get("pair_id") == task.get("pair_id")
            and review.get("pair_sha256") == task.get("pair_sha256")
            and review.get("reviewer_slot") == task.get("reviewer_slot")
        ):
            raise CampaignPackBlindReviewError("campaign review is not bound to its task")
        if review.get("human_attestation") != REVIEW_ATTESTATION:
            raise CampaignPackBlindReviewError("campaign review attestation is invalid")
        if review.get("overall_winner") not in {"left", "right"}:
            raise CampaignPackBlindReviewError("overall campaign winner must be left or right")
        dimensions = review.get("dimension_winners")
        if not isinstance(dimensions, Mapping) or set(dimensions) != set(DIMENSIONS) or any(
            value not in {"left", "right", "tie"} for value in dimensions.values()
        ):
            raise CampaignPackBlindReviewError("campaign dimension choices are invalid")
        defect = review.get("blocking_defect_side")
        reason = review.get("blocking_defect_reason")
        if defect not in {"none", "left", "right", "both"} or not isinstance(reason, str) or len(reason) > 1200:
            raise CampaignPackBlindReviewError("campaign blocking-defect fields are invalid")
        if defect != "none" and len(reason.strip()) < 16:
            raise CampaignPackBlindReviewError("a blocking defect requires a located explanation")
        pseudonym = review.get("reviewer_pseudonym")
        notes = review.get("notes")
        if not isinstance(pseudonym, str) or not 3 <= len(pseudonym.strip()) <= 120:
            raise CampaignPackBlindReviewError("reviewer pseudonym is invalid")
        if not isinstance(notes, str) or not 24 <= len(notes.strip()) <= 2000:
            raise CampaignPackBlindReviewError("campaign review notes must contain 24 to 2000 characters")
        try:
            timestamp = datetime.fromisoformat(str(review.get("reviewed_at", "")).replace("Z", "+00:00"))
        except ValueError as error:
            raise CampaignPackBlindReviewError("campaign review timestamp is invalid") from error
        if timestamp.tzinfo is None:
            raise CampaignPackBlindReviewError("campaign review timestamp must include a timezone")
        unsigned = dict(review)
        supplied = unsigned.pop("review_content_sha256", None)
        if not isinstance(supplied, str) or supplied != _sha256(unsigned):
            raise CampaignPackBlindReviewError("campaign review digest is invalid")

    def tasks_for_slot(self, slot: int, *, reviewer_token: str) -> dict[str, Any]:
        if slot not in range(1, 6):
            raise CampaignPackBlindReviewError("reviewer slot must be in [1, 5]")
        self._authorize(slot, reviewer_token)
        with self._lock:
            completed = {str(row["review_task_id"]) for row in self._load_reviews()}
            tasks = [
                {**task, "submitted": str(task["review_task_id"]) in completed}
                for task in self.public_packet["review_tasks"]
                if int(task["reviewer_slot"]) == slot
            ]
            return {
                "schema": "ProofLaunchCampaignPackVisualBlindReviewAssignmentV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "reviewer_slot": slot,
                "task_count": len(tasks),
                "tasks": tasks,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
                "private_mapping_exposed": False,
            }

    def offline_kit_for_slot(
        self,
        slot: int,
        *,
        reviewer_token: str,
    ) -> tuple[bytes, str, str]:
        """Build an identity-hidden, token-free offline review kit for one slot."""

        assignment = self.tasks_for_slot(slot, reviewer_token=reviewer_token)
        tasks = assignment.get("tasks")
        if not isinstance(tasks, list) or len(tasks) != 1:
            raise CampaignPackBlindReviewError(
                "campaign reviewer slot must resolve to exactly one task"
            )
        task = json.loads(json.dumps(tasks[0], ensure_ascii=False))
        member_bodies: dict[str, bytes] = {}
        task_body = json.dumps(
            task,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        member_bodies["review-task.json"] = task_body
        member_bodies["review.html"] = _offline_review_html(task).encode("utf-8")
        asset_records: list[dict[str, Any]] = []
        for side in ("left", "right"):
            for asset in task["pair"]["sides"][side]["assets"]:
                alias = str(asset["asset_alias"])
                path, media_type, digest = self.asset_for_alias(alias)
                if media_type != "image/png":
                    raise CampaignPackBlindReviewError(
                        "offline campaign review accepts PNG assets only"
                    )
                member_name = f"assets/{alias}.png"
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != digest:
                    raise CampaignPackBlindReviewError(
                        "campaign review asset changed during offline export"
                    )
                member_bodies[member_name] = body
                asset_records.append(
                    {
                        "member": member_name,
                        "side": side,
                        "role": asset["role"],
                        "sha256": digest,
                        "bytes": len(body),
                    }
                )
        manifest = _seal(
            {
                "schema": "ProofLaunchCampaignPackOfflineReviewKitV1",
                "reviewer_slot": slot,
                "review_task_id": task["review_task_id"],
                "pair_id": task["pair_id"],
                "pair_sha256": task["pair_sha256"],
                "public_packet_sha256": self.public_packet["content_sha256"],
                "assets": sorted(asset_records, key=lambda row: str(row["member"])),
                "files": {
                    name: {
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "bytes": len(body),
                    }
                    for name, body in sorted(member_bodies.items())
                },
                "invitation_token_included": False,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
                "private_mapping_exposed": False,
                "network_submission_enabled": False,
                "automatic_publish_enabled": False,
                "truth_boundary": (
                    "This offline kit supports one independent identity-hidden "
                    "review and exports a hash-bound JSON file. It does not transmit, "
                    "submit, deblind, publish, or prove 4A or production effect."
                ),
            }
        )
        member_bodies["manifest.json"] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, body in sorted(member_bodies.items()):
                _write_deterministic_zip_member(archive, name, body)
        body = stream.getvalue()
        digest = hashlib.sha256(body).hexdigest()
        return body, digest, f"campaign-pack-review-slot-{slot}.zip"

    def asset_for_alias(self, alias: str) -> tuple[Path, str, str]:
        if not _ASSET_ALIAS.fullmatch(alias):
            raise KeyError(alias)
        binding = self._private_core["asset_bindings"].get(alias)
        if not isinstance(binding, Mapping):
            raise KeyError(alias)
        path = (self.project_root / str(binding["project_relative_path"])).resolve(strict=True)
        try:
            path.relative_to(self.project_root)
        except ValueError as error:
            raise CampaignPackBlindReviewError("campaign asset escaped project root") from error
        digest = sha256_file(path)
        if path.is_symlink() or digest != binding.get("sha256"):
            raise CampaignPackBlindReviewError("campaign review asset changed after sealing")
        return path, str(binding["media_type"]), digest

    def submit(self, request: Mapping[str, Any], *, reviewer_token: str) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise CampaignPackBlindReviewError("campaign review must be an object")
        slot = request.get("reviewer_slot")
        if type(slot) is not int or slot not in range(1, 6):
            raise CampaignPackBlindReviewError("reviewer slot must be in [1, 5]")
        self._authorize(slot, reviewer_token)
        review = dict(request)
        self._validate_review(review)
        path = self._review_path(str(review["review_task_id"]))
        with self._lock:
            reviews = self._load_reviews()
            for existing in reviews:
                if int(existing["reviewer_slot"]) == slot and existing["reviewer_pseudonym"] != review["reviewer_pseudonym"]:
                    raise CampaignPackBlindReviewConflictError("reviewer pseudonym drifted within its slot")
                if int(existing["reviewer_slot"]) != slot and existing["reviewer_pseudonym"] == review["reviewer_pseudonym"]:
                    raise CampaignPackBlindReviewConflictError("one reviewer pseudonym cannot occupy multiple slots")
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if _canonical(existing) != _canonical(review):
                    raise CampaignPackBlindReviewConflictError("campaign review task is immutable")
                idempotent = True
            else:
                atomic_write_text(path, json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                path.chmod(0o600)
                idempotent = False
            status = self.status()
            if status["review_complete"]:
                self.aggregate()
            return {
                "schema": "ProofLaunchCampaignPackVisualReviewAcknowledgementV1",
                "review_task_id": review["review_task_id"],
                "review_content_sha256": review["review_content_sha256"],
                "idempotent": idempotent,
                **status,
            }

    def _compute_aggregate(self, reviews: list[dict[str, Any]]) -> dict[str, Any]:
        candidate_ids = tuple(self._private_core["candidates"])
        overall = {candidate_id: 0 for candidate_id in candidate_ids}
        dimensions = {
            dimension: {candidate_ids[0]: 0, candidate_ids[1]: 0, "tie": 0}
            for dimension in DIMENSIONS
        }
        blocking = {candidate_id: 0 for candidate_id in candidate_ids}
        review_bindings: list[dict[str, Any]] = []
        for review in reviews:
            task_id = str(review["review_task_id"])
            mapping = self._private_core["task_side_mapping"][task_id]
            overall_candidate = mapping[str(review["overall_winner"])]
            overall[overall_candidate] += 1
            for dimension, choice in review["dimension_winners"].items():
                dimensions[dimension]["tie" if choice == "tie" else mapping[choice]] += 1
            defect = str(review["blocking_defect_side"])
            if defect in {"left", "both"}:
                blocking[mapping["left"]] += 1
            if defect in {"right", "both"}:
                blocking[mapping["right"]] += 1
            review_bindings.append(
                {
                    "review_task_id": task_id,
                    "review_content_sha256": review["review_content_sha256"],
                    "reviewer_slot": review["reviewer_slot"],
                }
            )
        ordered = sorted(candidate_ids, key=lambda candidate_id: (-overall[candidate_id], candidate_id))
        leader, challenger = ordered
        dimension_losses = [
            dimension
            for dimension in DIMENSIONS
            if dimensions[dimension][leader] < dimensions[dimension][challenger]
        ]
        eligible = (
            overall[leader] >= 4
            and blocking[leader] == 0
            and not dimension_losses
        )
        payload = {
            "schema": "ProofLaunchCampaignPackVisualBlindReviewAggregateV1",
            "public_packet_sha256": self.public_packet["content_sha256"],
            "private_packet_sha256": self._private_packet["content_sha256"],
            "review_complete": True,
            "review_count": len(reviews),
            "distinct_reviewer_count": len({row["reviewer_pseudonym"] for row in reviews}),
            "overall_votes": overall,
            "dimension_votes": dimensions,
            "blocking_defect_counts": blocking,
            "overall_leader_candidate_id": leader,
            "leader_dimension_losses": dimension_losses,
            "promotion_recommendation_eligible": eligible,
            "recommended_candidate_id": leader if eligible else None,
            "review_bindings": sorted(review_bindings, key=lambda row: int(row["reviewer_slot"])),
            "human_preference_observed": True,
            "automatic_runtime_switch_enabled": False,
            "automatic_publish_enabled": False,
            "product_admission_passed": False,
            "four_a_preference_proven": False,
            "production_effect_proven": False,
            "truth_boundary": self.public_packet["truth_boundary"],
        }
        return _seal(payload)

    def aggregate(self) -> dict[str, Any]:
        with self._lock:
            reviews = self._load_reviews()
            if len(reviews) != 5 or {int(row["reviewer_slot"]) for row in reviews} != set(range(1, 6)):
                raise CampaignPackBlindReviewConflictError("campaign aggregate is unavailable until all five invited reviews are complete")
            aggregate = self._compute_aggregate(reviews)
            if self.aggregate_path.exists():
                existing = json.loads(self.aggregate_path.read_text(encoding="utf-8"))
                if _canonical(existing) != _canonical(aggregate):
                    raise CampaignPackBlindReviewConflictError("campaign aggregate drifted after sealing")
            else:
                atomic_write_text(self.aggregate_path, json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                self.aggregate_path.chmod(0o600)
            return aggregate

    def status(self) -> dict[str, Any]:
        with self._lock:
            reviews = self._load_reviews()
            per_slot = {
                str(slot): sum(1 for row in reviews if int(row["reviewer_slot"]) == slot)
                for slot in range(1, 6)
            }
            complete = len(reviews) == 5 and all(value == 1 for value in per_slot.values())
            aggregate = self._compute_aggregate(reviews) if complete else None
            return {
                "schema": "ProofLaunchCampaignPackVisualBlindReviewStatusV1",
                "public_packet_sha256": self.public_packet["content_sha256"],
                "expected_review_count": 5,
                "submitted_review_count": len(reviews),
                "remaining_review_count": 5 - len(reviews),
                "per_reviewer_slot_submitted": per_slot,
                "configured_reviewer_slot_count": len(self._token_hashes),
                "review_complete": complete,
                "promotion_recommendation_eligible": bool(aggregate and aggregate["promotion_recommendation_eligible"]),
                "recommended_candidate_id": aggregate["recommended_candidate_id"] if aggregate else None,
                "aggregate_content_sha256": aggregate["content_sha256"] if aggregate else None,
                "human_preference_observed": complete,
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
                "private_mapping_exposed": False,
                "offline_review_kit_available": True,
                "offline_review_kit_invitation_bound": True,
                "offline_review_kit_contains_invitation_token": False,
                "offline_review_kit_network_submission_enabled": False,
                "automatic_runtime_switch_enabled": False,
                "automatic_publish_enabled": False,
                "product_admission_passed": False,
                "four_a_preference_proven": False,
                "production_effect_proven": False,
            }


__all__ = [
    "AGGREGATE_NAME",
    "CampaignPackBlindReviewAuthorizationError",
    "CampaignPackBlindReviewConflictError",
    "CampaignPackBlindReviewError",
    "CampaignPackBlindReviewService",
    "DIMENSIONS",
    "PRIVATE_NAME",
    "PUBLIC_NAME",
    "REVIEW_ATTESTATION",
    "compile_campaign_pack_blind_review_bundle",
]
