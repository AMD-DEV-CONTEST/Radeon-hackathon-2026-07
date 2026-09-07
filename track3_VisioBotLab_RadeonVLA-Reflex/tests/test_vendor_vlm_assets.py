import json

from radeonvla.vendor_vlm_assets import VLM_ASSET_FILES, vendor_assets


def test_vendor_assets_copies_resolved_files_and_manifest(tmp_path) -> None:
    source = tmp_path / "source"
    policy = tmp_path / "policy"
    source.mkdir()
    policy.mkdir()
    for index, name in enumerate(VLM_ASSET_FILES):
        (source / name).write_text(f"asset-{index}\n", encoding="utf-8")

    destination = vendor_assets(source, policy, repo_id="org/model", revision="abc123")

    manifest = json.loads((destination / "radeonvla_vlm_assets.json").read_text(encoding="utf-8"))
    assert manifest["repo_id"] == "org/model"
    assert manifest["revision"] == "abc123"
    assert set(manifest["files"]) == set(VLM_ASSET_FILES)
    assert (destination / "tokenizer.json").read_text(encoding="utf-8").startswith("asset-")
