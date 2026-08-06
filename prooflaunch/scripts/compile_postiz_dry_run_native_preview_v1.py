#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1"
SCHEDULE = ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v2/content-calendar.json"
RELEASE_COPY = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-release-copy-v1/release-copy.json"
LINKEDIN_MEDIA = [ROOT / f"artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2/slide-{index:02d}-1080x1350.png" for index in range(1, 6)]
INSTAGRAM_MEDIA = LINKEDIN_MEDIA
TIKTOK_MEDIA = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-video-v2/prooflaunch-delete-one-line-vertical-4k-v2.mp4"
STATIC = ("index.html", "preview.css", "approval.js")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sealed(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def slot(schedule: dict, slot_id: str) -> dict:
    return next(row for row in schedule["slots"] if row["slot_id"] == slot_id)


def media_placeholders(paths: list[Path], prefix: str) -> list[dict]:
    return [
        {
            "id": f"{{{{POSTIZ_{prefix}_MEDIA_ID_{index}}}}}",
            "path": f"{{{{POSTIZ_{prefix}_HTTPS_URL_{index}}}}}",
        }
        for index, _ in enumerate(paths, 1)
    ]


def request(
    *,
    source: dict,
    provider: str,
    content: str,
    preview_asset: Path | list[Path],
    settings: dict,
    media: list[dict],
    release_surface: dict,
    fact_contract: dict,
) -> dict:
    preview_assets = preview_asset if isinstance(preview_asset, list) else [preview_asset]
    return {
        "slot_id": source["slot_id"],
        "channel": source["channel"],
        "provider": provider,
        "scheduled_at_utc": source["scheduled_at_utc"],
        "approval_state": "pending_named_human_release_owner",
        "connector_mode": "local_dry_run_no_network",
        "media_upload_state": "blocked_until_postiz_upload_returns_https_id_and_path" if media else "not_required",
        "fact_contract": {
            "contract_id": fact_contract["contract_id"],
            "approved_claim_source_id": fact_contract["approved_claim_source_id"],
            "required_boundary_sentence": fact_contract["required_boundary_sentence"],
        },
        "last_mile_contract": {
            "audience": release_surface["audience"],
            "hook": release_surface["hook"],
            "single_action": release_surface["single_action"],
            "participation_seconds": release_surface["participation_seconds"],
            "native_mechanic": release_surface["native_mechanic"],
        },
        "preview_assets": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)} for path in preview_assets
        ],
        "postiz_request": {
            "method": "POST",
            "endpoint": "/public/v1/posts",
            "payload": {
                "type": "schedule",
                "date": source["scheduled_at_utc"],
                "shortLink": False,
                "tags": ["prooflaunch", "delete-one-line", "human-review-required"],
                "posts": [{
                    "integration": {"id": f"{{{{POSTIZ_{provider.upper().replace('-', '_')}_INTEGRATION_ID}}}}"},
                    "value": [{"content": content, "image": media}],
                    "settings": settings,
                }],
            },
        },
        "release_guard": {
            "manual_content_approval_required": True,
            "manual_timing_approval_required": True,
            "manual_media_upload_required": bool(media),
            "automatic_publish_enabled": False,
            "external_request_executed": False,
        },
    }


def validate_release_requests(requests: list[dict], fact_contract: dict) -> dict:
    boundary = fact_contract["required_boundary_sentence"]
    contents = []
    for row in requests:
        contract = row["last_mile_contract"]
        content = row["postiz_request"]["payload"]["posts"][0]["value"][0]["content"]
        contents.append(content)
        if content.splitlines()[0] != contract["hook"]:
            raise SystemExit(f"release hook is not the first line: {row['slot_id']}")
        if boundary not in content:
            raise SystemExit(f"release truth boundary missing: {row['slot_id']}")
        if not contract["single_action"]:
            raise SystemExit(f"release single action missing: {row['slot_id']}")
        if contract["participation_seconds"] > 30:
            raise SystemExit(f"release participation exceeds 30 seconds: {row['slot_id']}")
        if row["fact_contract"]["contract_id"] != fact_contract["contract_id"]:
            raise SystemExit(f"release fact contract mismatch: {row['slot_id']}")
        if row["release_guard"]["automatic_publish_enabled"] or row["release_guard"]["external_request_executed"]:
            raise SystemExit(f"dry-run execution boundary failed: {row['slot_id']}")
    return {
        "every_request_starts_with_selected_hook": True,
        "every_request_has_required_truth_boundary": True,
        "every_request_has_one_action": True,
        "every_request_participation_seconds_lte_30": True,
        "every_request_uses_one_fact_contract": True,
        "platform_copy_is_not_duplicated": len(contents) == len(set(contents)),
        "external_request_executed": False,
    }


def main() -> None:
    dependencies = [SCHEDULE, RELEASE_COPY, TIKTOK_MEDIA, *LINKEDIN_MEDIA, *(OUTPUT / name for name in STATIC)]
    for path in dependencies:
        if not path.is_file():
            raise SystemExit(f"missing Postiz dry-run dependency: {path}")
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    release_copy = json.loads(RELEASE_COPY.read_text(encoding="utf-8"))
    fact_contract = release_copy["contract"]
    linkedin = release_copy["platforms"]["linkedin"]
    tiktok = release_copy["platforms"]["tiktok"]
    instagram = release_copy["platforms"]["instagram"]
    null_result = release_copy["platforms"]["null_result_receipt"]
    preview_html = (OUTPUT / "index.html").read_text(encoding="utf-8")
    for surface in (linkedin, tiktok, instagram, null_result):
        if surface["hook"] not in preview_html:
            raise SystemExit(f"visible Postiz preview drifted from selected hook: {surface['hook']}")
    if fact_contract["required_boundary_sentence"] not in preview_html:
        raise SystemExit("visible Postiz preview hides the required truth boundary")
    requests = [
        request(
            source=slot(schedule, "dol-02-linkedin-founder-confession"),
            provider="linkedin",
            content=linkedin["caption"],
            preview_asset=LINKEDIN_MEDIA,
            media=media_placeholders(LINKEDIN_MEDIA, "LINKEDIN"),
            settings={"__type": "linkedin", "post_as_images_carousel": True, "carousel_name": "Delete One Line — Witness Check"},
            release_surface=linkedin,
            fact_contract=fact_contract,
        ),
        request(
            source=slot(schedule, "dol-04-short-video-visible-deletion"),
            provider="tiktok",
            content=tiktok["caption"],
            preview_asset=TIKTOK_MEDIA,
            media=media_placeholders([TIKTOK_MEDIA], "TIKTOK"),
            settings={
                "__type": "tiktok",
                "title": tiktok["title"],
                "privacy_level": "SELF_ONLY",
                "duet": False,
                "stitch": False,
                "comment": False,
                "autoAddMusic": "no",
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
                "video_made_with_ai": True,
                "content_posting_method": "UPLOAD",
            },
            release_surface=tiktok,
            fact_contract=fact_contract,
        ),
        request(
            source=slot(schedule, "dol-05-instagram-redaction-object"),
            provider="instagram",
            content=instagram["caption"],
            preview_asset=INSTAGRAM_MEDIA,
            media=media_placeholders(INSTAGRAM_MEDIA, "INSTAGRAM"),
            settings={"__type": "instagram", "post_type": "post", "is_trial_reel": False, "collaborators": []},
            release_surface=instagram,
            fact_contract=fact_contract,
        ),
        request(
            source=slot(schedule, "dol-07-linkedin-stop-repair-continue"),
            provider="linkedin",
            content=null_result["caption"],
            preview_asset=LINKEDIN_MEDIA[4],
            media=[],
            settings={"__type": "linkedin", "post_as_images_carousel": False},
            release_surface=null_result,
            fact_contract=fact_contract,
        ),
    ]
    quality_checks = validate_release_requests(requests, fact_contract)
    if not all(value for key, value in quality_checks.items() if key != "external_request_executed"):
        raise SystemExit(f"Postiz last-mile quality gate failed: {quality_checks}")
    unsupported = [
        {"slot_id": row["slot_id"], "channel": row["channel"], "reason": "No explicit authorized Postiz integration mapping in the frozen schedule."}
        for row in schedule["slots"] if row["slot_id"] not in {request_row["slot_id"] for request_row in requests}
    ]
    payload = sealed({
        "schema": "ProofLaunchPostizDryRunExportV1",
        "adapter": {
            "project": "gitroomhq/postiz-app",
            "license": "AGPL-3.0",
            "public_api_endpoint": "/public/v1/posts",
            "official_docs": [
                "https://docs.postiz.com/public-api/posts/create",
                "https://docs.postiz.com/public-api/providers/linkedin",
                "https://docs.postiz.com/public-api/providers/tiktok",
                "https://docs.postiz.com/public-api/providers/instagram",
            ],
            "observed_at": "2026-08-03",
        },
        "campaign_id": schedule["campaign_id"],
        "release_copy_campaign_id": release_copy["campaign_id"],
        "release_fact_contract_id": fact_contract["contract_id"],
        "timezone": schedule["timezone"],
        "source_schedule_slot_count": schedule["slot_count"],
        "postiz_dry_run_request_count": len(requests),
        "unsupported_slot_count": len(unsupported),
        "requests": requests,
        "unsupported_slots": unsupported,
        "external_request_count": 0,
        "credential_material_present": False,
        "automatic_publish_enabled": False,
        "human_approval_required": True,
        "last_mile_quality_checks": quality_checks,
        "truth_boundary": "These are executable-shape Postiz API request bodies and platform-native local previews. No credential, media upload, API call, external draft, schedule, publication, human preference, breakout, conversion, revenue or named-product win exists.",
    })
    atomic_write_text(OUTPUT / "postiz-dry-run-requests.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(
        OUTPUT / "postiz-dry-run-requests.js",
        "window.PROOFLAUNCH_POSTIZ_DRY_RUN = " + json.dumps(payload, ensure_ascii=False, sort_keys=True) + ";\n",
    )
    bindings = [SCHEDULE, RELEASE_COPY, TIKTOK_MEDIA, *LINKEDIN_MEDIA, OUTPUT / "postiz-dry-run-requests.json", OUTPUT / "postiz-dry-run-requests.js", *(OUTPUT / name for name in STATIC)]
    receipt = sealed({
        "schema": "ProofLaunchPostizNativePreviewReceiptV1",
        "artifact_id": "postiz-dry-run-native-preview-v1",
        "postiz_dry_run_request_count": len(requests),
        "native_preview_count": len(requests),
        "pending_human_approval_count": len(requests),
        "unsupported_slot_count": len(unsupported),
        "external_request_count": 0,
        "completed_named_product_pk_count": 0,
        "named_product_win_count": 0,
        "bindings": [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in bindings],
        "truth_boundary": payload["truth_boundary"],
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "request_count": len(requests), "pending_approval_count": len(requests), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
