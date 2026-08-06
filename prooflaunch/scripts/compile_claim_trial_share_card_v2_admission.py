#!/usr/bin/env python3
from __future__ import annotations

import base64
import html
import json
from copy import deepcopy
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_challenger_dossier import validate_challenger_admission
from prooflaunch_remix.gtm_unified_offline_review import seal


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
V1 = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v2"
CARD_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2"
CATEGORY_ID = "image_generation_editing"


def artifact(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "extension": path.suffix.casefold(),
        "media_type": "image/png" if path.suffix.casefold() == ".png" else "application/json",
    }


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    v1 = json.loads(V1.read_text(encoding="utf-8"))
    card = CARD_ROOT / "prooflaunch-performance-review-1080x1350.png"
    receipt = CARD_ROOT / "receipt.json"
    if not card.is_file() or not receipt.is_file():
        raise SystemExit("compile the V2 share card before challenger admission")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    dossier_path = OUTPUT / f"{CATEGORY_ID}.html"
    category_contract = next(row for row in ledger["categories"] if row["category_id"] == CATEGORY_ID)
    source_artifacts = [artifact(card), artifact(receipt)]
    image_uri = "data:image/png;base64," + base64.b64encode(card.read_bytes()).decode("ascii")
    embedded = html.escape(json.dumps({
        "schema": "ProofLaunchNamedProductChallengerDossierV2",
        "category_id": CATEGORY_ID,
        "same_brief_task": category_contract["same_brief_task"],
        "effect_pk_question": category_contract["effect_pk_question"],
        "quality_axes": category_contract["quality_axes"],
        "source_artifacts": source_artifacts,
        "source_artifact_count": len(source_artifacts),
        "provider_identity_exposed": False,
        "candidate_role_exposed": False,
        "automatic_action_authority": False,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Source-hidden image challenger V2</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#0b0a08;color:#f4eddc;font:15px/1.5 system-ui,sans-serif}}main{{max-width:1220px;margin:auto;padding:28px}}header,section{{border:1px solid #4b4a45;padding:22px;margin-bottom:18px}}h1{{font-size:44px;line-height:1;margin:.35em 0}}p{{max-width:900px}}img{{display:block;width:min(100%,1080px);margin:auto}}code{{word-break:break-all;color:#caff00}}details pre{{white-space:pre-wrap;overflow:auto}}</style></head><body><main><header><b>SOURCE-HIDDEN SAME-BRIEF CHALLENGER · REVISION 2</b><h1>{html.escape(category_contract['same_brief_task'])}</h1><p><strong>Decision question:</strong> {html.escape(category_contract['effect_pk_question'])}</p><p><strong>Quality axes:</strong> {html.escape(' · '.join(category_contract['quality_axes']))}</p><p>This revision replaces a compliance-slide treatment with an original performance-review scene while retaining deterministic typography and the same evidence boundary.</p><details><summary>Machine-readable binding</summary><pre>{embedded}</pre></details></header><section><p><code>sha256:{sha256_file(card)}</code></p><img src="{image_uri}" alt="source-hidden 4 by 5 candidate"></section></main></body></html>'''
    atomic_write_text(dossier_path, document)

    report = deepcopy(v1)
    report.pop("content_sha256", None)
    report["schema"] = "ProofLaunchNamedProductChallengerAdmissionV1"
    report["challenger_revision"] = 2
    report["revision_reason"] = "replace image compliance-slide treatment with a human-tension performance-review key visual before any human votes"
    report["parent_manifest_sha256"] = v1["content_sha256"]
    category = next(row for row in report["categories"] if row["category_id"] == CATEGORY_ID)
    category.update({
        "dossier": {
            "project_relative_path": dossier_path.relative_to(ROOT).as_posix(),
            "bytes": dossier_path.stat().st_size,
            "sha256": sha256_file(dossier_path),
            "media_type": "text/html",
        },
        "source_artifact_count": len(source_artifacts),
        "source_artifacts": source_artifacts,
        "dossier_compiled": True,
        "same_brief_material_complete": True,
        "named_product_pk_preparation_admitted": True,
        "blocking_gap_count": 0,
        "blocking_gaps": [],
        "repair_action": "admit_revision_2_for_source_hidden_named_product_pairing",
    })
    report = seal(report)
    validate_challenger_admission(report, ledger=ledger, project_root=ROOT)
    atomic_write_text(OUTPUT / "manifest.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "content_sha256": report["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
