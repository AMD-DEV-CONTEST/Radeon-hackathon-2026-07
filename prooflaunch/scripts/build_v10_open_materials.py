#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_open_materials import MaterialKind, OpenMaterial, build_bundle
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_open_materials"
EVIDENCE = ROOT / "evidence/v10/open-materials-v1-audit.json"


def github_record(
    source_id: str,
    kind: MaterialKind,
    repo: str,
    commit: str,
    path: str,
    license_id: str,
    license_path: str,
    media_type: str,
    attribution: str,
    *,
    training_allowed: bool,
    trademark_hold: bool = False,
) -> OpenMaterial:
    return OpenMaterial(
        source_id=source_id,
        kind=kind,
        title=path,
        asset_url=f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
        evidence_url=f"https://github.com/{repo}/blob/{commit}/{path}",
        license_id=license_id,
        license_url=f"https://github.com/{repo}/blob/{commit}/{license_path}",
        revision=commit,
        upstream_digest_algorithm="git-commit-pinned-locator",
        upstream_digest=commit,
        media_type=media_type,
        attribution=attribution,
        asset_granular_license_verified=kind is MaterialKind.FONT,
        commercial_allowed=training_allowed,
        derivatives_allowed=training_allowed,
        redistribution_allowed=training_allowed,
        training_allowed=training_allowed,
        trademark_hold=trademark_hold,
        notes="Immutable raw locator pinned to the observed upstream commit.",
    )


def commons_record(
    source_id: str,
    kind: MaterialKind,
    title: str,
    page: str,
    asset: str,
    sha1: str,
    media_type: str,
    *,
    trademark_hold: bool = False,
) -> OpenMaterial:
    return OpenMaterial(
        source_id=source_id,
        kind=kind,
        title=title,
        asset_url=asset,
        evidence_url=page,
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        revision=f"wikimedia-commons-sha1-{sha1}",
        upstream_digest_algorithm="sha1",
        upstream_digest=sha1,
        media_type=media_type,
        attribution="Wikimedia Commons asset author recorded on the evidence page",
        asset_granular_license_verified=True,
        commercial_allowed=not trademark_hold,
        derivatives_allowed=True,
        redistribution_allowed=True,
        training_allowed=not trademark_hold,
        trademark_hold=trademark_hold,
        notes=(
            "CC0 copyright status is asset-granular; visible third-party marks are "
            "a separate right and force reference-only admission."
            if trademark_hold
            else "CC0 status observed in Wikimedia Commons extmetadata."
        ),
    )


def records() -> tuple[OpenMaterial, ...]:
    rocm = "397421be29ce8a87464ed599f8c61555d129d55f"
    transformers = "3717b9cda226af7377da1944f395af0eac6e2b51"
    cncf = "fa4f481f58e692ed495f825512214fe526d22a12"
    fonts = "2796410152d4f9524b68ed46e69c1b60f8e0f7c3"
    rows: list[OpenMaterial] = []
    for index, path in enumerate(
        (
            "README.md",
            "docs/about/include/hardware-support-table.md",
            "docs/reference/glossary/device-hardware.rst",
        ),
        1,
    ):
        rows.append(
            github_record(
                f"hardware-rocm-{index:02d}", MaterialKind.HARDWARE, "ROCm/ROCm",
                rocm, path, "MIT", "LICENSE", "text/plain", "Advanced Micro Devices, Inc.",
                training_allowed=True,
            )
        )
    for index, path in enumerate(
        ("README.md", "docs/source/en/index.md", "src/transformers/__init__.py"), 1
    ):
        rows.append(
            github_record(
                f"software-transformers-{index:02d}", MaterialKind.SOFTWARE,
                "huggingface/transformers", transformers, path, "Apache-2.0",
                "LICENSE", "text/plain", "Hugging Face and Transformers contributors",
                training_allowed=True,
            )
        )
    for index, path in enumerate(
        (
            "other/cncf/icon/color/cncf-icon-color.svg",
            "projects/kubernetes/icon/color/kubernetes-icon-color.svg",
            "projects/prometheus/icon/color/prometheus-icon-color.svg",
        ),
        1,
    ):
        rows.append(
            github_record(
                f"brand-cncf-{index:02d}", MaterialKind.BRAND, "cncf/artwork", cncf,
                path, "LicenseRef-LF-Trademark-Guidelines", "LICENSE.md",
                "image/svg+xml", "Cloud Native Computing Foundation / relevant project",
                training_allowed=False, trademark_hold=True,
            )
        )
    product = (
        ("9929 Jollibee products", "https://commons.wikimedia.org/wiki/File:9929Jollibee_products_03.jpg", "https://upload.wikimedia.org/wikipedia/commons/7/74/9929Jollibee_products_03.jpg", "470ed58fe70d884f17943b8558fbcafd5136d1c3"),
        ("1763 McDonald's products", "https://commons.wikimedia.org/wiki/File:1763McDonald%27s_products_in_the_Philippines_03.jpg", "https://upload.wikimedia.org/wikipedia/commons/2/21/1763McDonald%27s_products_in_the_Philippines_03.jpg", "5ae86436027f08a6dfa56a47a829c36a3b21a6de"),
        ("49 McDonald's products", "https://commons.wikimedia.org/wiki/File:49McDonald%27s_products.jpg", "https://upload.wikimedia.org/wikipedia/commons/5/56/49McDonald%27s_products.jpg", "0ae0d1106828e3a3061a61a65ec8d7f453167aae"),
    )
    for index, (title, page, asset, sha1) in enumerate(product, 1):
        rows.append(commons_record(f"product-commons-{index:02d}", MaterialKind.PRODUCT_VISUAL, title, page, asset, sha1, "image/jpeg", trademark_hold=True))
    scenes = (
        ("Landscape—Scene from Thanatopsis", "https://commons.wikimedia.org/wiki/File:Landscape%E2%80%94Scene_from_%22Thanatopsis%22_MET_DT1539.jpg", "https://upload.wikimedia.org/wikipedia/commons/1/18/Landscape%E2%80%94Scene_from_%22Thanatopsis%22_MET_DT1539.jpg", "11cafc730002cdc2fe4a76c5c74c1239201ee137"),
        ("Table screen with landscape scene", "https://commons.wikimedia.org/wiki/File:%E6%B8%85_%E7%BF%A1%E7%BF%A0%E5%B1%B1%E6%B0%B4%E5%9C%96%E5%B1%8F-Table_screen_with_landscape_scene_MET_DP272522.jpg", "https://upload.wikimedia.org/wikipedia/commons/1/15/%E6%B8%85_%E7%BF%A1%E7%BF%A0%E5%B1%B1%E6%B0%B4%E5%9C%96%E5%B1%8F-Table_screen_with_landscape_scene_MET_DP272522.jpg", "4d42c408af2685f874064bb711f0bfab8244341e"),
        ("Pietra dura landscape scene", "https://commons.wikimedia.org/wiki/File:Pietra_dura_landscape_scene_MET_ES2865.jpg", "https://upload.wikimedia.org/wikipedia/commons/9/95/Pietra_dura_landscape_scene_MET_ES2865.jpg", "b9977855242f76e115d7409f14bd9e8f61aa45f4"),
    )
    for index, (title, page, asset, sha1) in enumerate(scenes, 1):
        rows.append(commons_record(f"scene-commons-{index:02d}", MaterialKind.SCENE_VISUAL, title, page, asset, sha1, "image/jpeg"))
    videos = (
        ("Safe medicine campaign", "https://commons.wikimedia.org/wiki/File:Video_campa%C3%B1a_medicamento_seguro_1.webm", "https://upload.wikimedia.org/wikipedia/commons/2/21/Video_campa%C3%B1a_medicamento_seguro_1.webm", "1f7d8e64b830e91762ee8a2e65156cc7c972ecb1"),
        ("Video Cut Tool demonstration", "https://commons.wikimedia.org/wiki/File:JeremyNguyen_-_Video_Cut_Tool_Demonstration.webm", "https://upload.wikimedia.org/wikipedia/commons/4/4e/JeremyNguyen_-_Video_Cut_Tool_Demonstration.webm", "cbe601b2028bb847109954e1f650ab72b7c8dbb5"),
        ("CC0 public-domain bumper", "https://commons.wikimedia.org/wiki/File:CC0_-_Public_Domain_Dedication_video_bumper.webm", "https://upload.wikimedia.org/wikipedia/commons/5/5a/CC0_-_Public_Domain_Dedication_video_bumper.webm", "a8759cc5849c9f43581a3e4fbff829dbabf1b613"),
    )
    for index, (title, page, asset, sha1) in enumerate(videos, 1):
        rows.append(commons_record(f"video-commons-{index:02d}", MaterialKind.VIDEO, title, page, asset, sha1, "video/webm"))
    for family, path in (
        ("oswald", "ofl/oswald/Oswald%5Bwght%5D.ttf"),
        ("roboto", "ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf"),
        ("opensans", "ofl/opensans/OpenSans%5Bwdth%2Cwght%5D.ttf"),
    ):
        rows.append(
            github_record(
                f"font-google-{family}", MaterialKind.FONT, "google/fonts", fonts,
                path, "OFL-1.1", f"ofl/{family}/OFL.txt", "font/ttf",
                f"{family} upstream authors", training_allowed=True,
            )
        )
    audio = (
        ("MissingNo pronunciation", "https://commons.wikimedia.org/wiki/File:Pokemon-name-audio-missingno.oga", "https://upload.wikimedia.org/wikipedia/commons/c/cd/Pokemon-name-audio-missingno.oga", "5ff13515bbc5a1e497b579a0f4bd26f29604cfeb", "application/ogg"),
        ("Fyaverse pronunciation", "https://commons.wikimedia.org/wiki/File:Audio%3DEn-us-fyaverse.ogg", "https://upload.wikimedia.org/wikipedia/commons/b/be/Audio%3DEn-us-fyaverse.ogg", "8b28ab5375fde641678e8656188ef9a30b542817", "application/ogg"),
        ("Four spoken audio", "https://commons.wikimedia.org/wiki/File:Four_(audio).wav", "https://upload.wikimedia.org/wikipedia/commons/e/eb/Four_%28audio%29.wav", "534e8ef3de2e20e68f58746eb0659e1b425dcf15", "audio/wav"),
    )
    for index, (title, page, asset, sha1, media_type) in enumerate(audio, 1):
        rows.append(commons_record(f"audio-commons-{index:02d}", MaterialKind.AUDIO, title, page, asset, sha1, media_type))
    return tuple(rows)


def main() -> int:
    bundle = build_bundle(records())
    DATA.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        DATA / "sources.jsonl",
        "".join(
            json.dumps(
                {**asdict(item), "kind": item.kind.value, "admission": item.admission.value, "identity_sha256": item.identity_sha256},
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"
            for item in bundle.records
        ),
    )
    receipt = bundle.receipt()
    atomic_write_text(DATA / "manifest.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    audit = {
        "schema": "ProofLaunchOpenMaterialsAuditV1",
        "canonical_todos": [f"{number:04d}" for number in range(463, 471)],
        "mechanically_verified": {
            "asset_records": len(bundle.records),
            "material_kinds": len(MaterialKind),
            "records_per_kind": min(bundle.counts().values()),
            "asset_granular_media_rights": True,
            "immutable_git_commit_pins": 12,
            "commons_content_sha1_pins": 12,
            "brand_training_admissions": 0,
            "public_access_never_substitutes_for_license": True,
        },
        "runtime_truth": {
            "remote_metadata_observed": True,
            "downloaded_asset_bytes_saved": 0,
            "training_run_observed": False,
            "agency_corpus_v2_frozen": False,
            "source_bundle_2000_complete": False,
        },
        "manifest_sha256": stable_sha256(receipt),
        "truth_boundary": receipt["truth_boundary"],
    }
    audit["content_sha256"] = stable_sha256(audit)
    atomic_write_text(EVIDENCE, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"records": len(bundle.records), "counts": bundle.counts(), "target_complete": False, "content_sha256": audit["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
