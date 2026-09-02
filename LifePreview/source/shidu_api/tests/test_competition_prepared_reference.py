from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from shidu_api.competition_prepared_reference import (
    CompetitionPreparedReferenceError,
    CompetitionPreparedReferenceStore,
    validate_competition_prepared_reference,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
_PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _payload(persistent_root: Path) -> dict[str, object]:
    image = persistent_root / "artifacts" / "reference.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"one immutable reference image")
    checkpoint = persistent_root / "runner" / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps({"status": "prepared"}, separators=(",", ":")),
        encoding="utf-8",
    )
    visual_prompt = "A single front three-quarter portrait of Su Shi."
    h3_prompt = "Use this image as the identity anchor for a three-second shot."
    prompt_identity = {
        "schemaVersion": "amd.competition-prompt-reference-authority.v1",
        "referenceProfile": "competition-prompt-single-view-v1",
        "sourceMode": "prompt_synthesized",
        "requiredImages": 1,
        "view": "front_three_quarter",
        "characterName": "苏轼",
        "ageStage": "middle-aged",
        "historicalContext": "Historically grounded Song-dynasty context.",
        "bookIdentitySha256": "0" * 64,
        "directionSha256": "1" * 64,
        "trialScriptSha256": "2" * 64,
        "researchSha256": "3" * 64,
        "evidencePackSha256": "4" * 64,
        "safetyReleaseDecisionSha256": "5" * 64,
        "visualPrompt": visual_prompt,
        "promptSha256": hashlib.sha256(visual_prompt.encode("utf-8")).hexdigest(),
        "h3Prompt": h3_prompt,
        "h3PromptSha256": hashlib.sha256(h3_prompt.encode("utf-8")).hexdigest(),
        "seed": 20260806,
        "workflowSha256": "b" * 64,
        "generationInvocationCount": 1,
        "technicalRetryLimit": 1,
    }
    prompt_authority = {
        **prompt_identity,
        "authoritySha256": hashlib.sha256(
            json.dumps(
                prompt_identity,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    return {
        "schemaVersion": "amd.competition-prepared-reference.v1",
        "status": "prepared",
        "requestId": str(_REQUEST_ID),
        "projectId": str(_PROJECT_ID),
        "bookId": "33333333-3333-4333-8333-333333333333",
        "directionRevisionId": "44444444-4444-4444-8444-444444444444",
        "trialScriptRevisionId": "55555555-5555-4555-8555-555555555555",
        "characterName": "苏轼",
        "referenceProfile": "competition-prompt-single-view-v1",
        "sourceMode": "prompt_synthesized",
        "requiredImages": 1,
        "promptAuthority": prompt_authority,
        "reference": {
            "viewName": "front_three_quarter",
            "path": str(image),
            "sha256": _sha256(image),
            "mimeType": "image/png",
            "width": 512,
            "height": 768,
            "byteSize": image.stat().st_size,
            "promptId": "comfy-prompt-001",
            "compiledWorkflowSha256": "c" * 64,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
        },
        "runner": {
            "checkpointPath": str(checkpoint),
            "checkpointSha256": _sha256(checkpoint),
            "cutoverComplete": True,
        },
    }


def test_publish_is_canonical_append_only_and_idempotent(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    payload = _payload(persistent_root)

    published = store.publish(payload)
    authority_sha = str(payload["promptAuthority"]["authoritySha256"])  # type: ignore[index]
    path = store.path_for(authority_sha)
    original_body = path.read_bytes()
    original_mtime = path.stat().st_mtime_ns

    assert published["manifestSha256"] == hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert original_body == json.dumps(
        published,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert store.load(authority_sha) == published
    assert store.publish(dict(payload)) == published
    assert path.read_bytes() == original_body
    assert path.stat().st_mtime_ns == original_mtime


def test_publish_rejects_a_conflicting_value_for_the_same_prompt_authority(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    payload = _payload(persistent_root)
    store.publish(payload)
    conflict = dict(payload)
    conflict["requestId"] = "77777777-7777-4777-8777-777777777777"

    with pytest.raises(CompetitionPreparedReferenceError, match="conflicts"):
        store.publish(conflict)


@pytest.mark.parametrize("target", ["image", "checkpoint"])
def test_load_revalidates_referenced_file_sha256(
    tmp_path: Path,
    target: str,
) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    payload = _payload(persistent_root)
    published = store.publish(payload)
    path = (
        Path(str(published["reference"]["path"]))  # type: ignore[index]
        if target == "image"
        else Path(str(published["runner"]["checkpointPath"]))  # type: ignore[index]
    )
    path.write_bytes(b"changed after publish")

    with pytest.raises(CompetitionPreparedReferenceError, match="changed"):
        store.load(str(published["promptAuthority"]["authoritySha256"]))  # type: ignore[index]


def test_load_rejects_manifest_tampering(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    published = store.publish(_payload(persistent_root))
    authority_sha = str(published["promptAuthority"]["authoritySha256"])  # type: ignore[index]
    path = store.path_for(authority_sha)
    tampered = dict(published)
    tampered["requestId"] = "77777777-7777-4777-8777-777777777777"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(CompetitionPreparedReferenceError, match="manifest SHA-256"):
        store.load(authority_sha)


def test_schema_is_exact_and_prompt_digest_is_bound(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    payload = _payload(persistent_root)
    payload["unexpected"] = True

    with pytest.raises(CompetitionPreparedReferenceError, match="fields"):
        store.publish(payload)

    payload = _payload(persistent_root)
    payload["promptAuthority"]["promptSha256"] = "d" * 64  # type: ignore[index]
    with pytest.raises(CompetitionPreparedReferenceError, match="prompt SHA-256"):
        store.publish(payload)


def test_helper_returns_the_validated_manifest_unchanged(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    published = store.publish(_payload(persistent_root))

    validated = validate_competition_prepared_reference(
        published,
        persistent_root=persistent_root,
    )

    assert validated is published


def test_load_by_request_id_uses_append_only_index_and_checks_project(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    published = store.publish(_payload(persistent_root))
    index_path = store.request_index_path_for(_REQUEST_ID)

    assert index_path.is_file()
    assert store.load_by_request_id(
        _REQUEST_ID,
        expected_project_id=_PROJECT_ID,
    ) == published
    with pytest.raises(CompetitionPreparedReferenceError, match="another project"):
        store.load_by_request_id(
            _REQUEST_ID,
            expected_project_id=UUID("66666666-6666-4666-8666-666666666666"),
        )


def test_request_index_is_strictly_revalidated(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    store.publish(_payload(persistent_root))
    index_path = store.request_index_path_for(_REQUEST_ID)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["authoritySha256"] = "f" * 64
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(CompetitionPreparedReferenceError, match="index SHA-256"):
        store.load_by_request_id(_REQUEST_ID)


def test_store_and_referenced_files_must_stay_under_real_persistent_storage(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "persistent"
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="inside persistent storage"):
        CompetitionPreparedReferenceStore(
            root=outside / "prepared-references",
            persistent_root=persistent_root,
        )

    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )
    payload = _payload(persistent_root)
    outside_image = outside / "reference.png"
    outside_image.write_bytes(b"outside")
    payload["reference"]["path"] = str(outside_image)  # type: ignore[index]
    payload["reference"]["sha256"] = _sha256(outside_image)  # type: ignore[index]
    payload["reference"]["byteSize"] = outside_image.stat().st_size  # type: ignore[index]

    with pytest.raises(CompetitionPreparedReferenceError, match="persistent storage"):
        store.publish(payload)


def test_symlinked_reference_is_rejected(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    payload = _payload(persistent_root)
    image = Path(str(payload["reference"]["path"]))  # type: ignore[index]
    link = image.with_name("reference-link.png")
    try:
        os.symlink(image, link)
    except OSError:
        pytest.skip("symlinks are unavailable in this test environment")
    payload["reference"]["path"] = str(link)  # type: ignore[index]
    store = CompetitionPreparedReferenceStore(
        root=persistent_root / "prepared-references",
        persistent_root=persistent_root,
    )

    with pytest.raises(CompetitionPreparedReferenceError, match="symlink"):
        store.publish(payload)
