from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def test_context_loads_independent_comfy_and_recursive_pipeline_override(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drama.context import Context

    comfy_file = tmp_path / "comfyui.amd.yaml"
    comfy_file.write_text(
        "instances:\n"
        "  - base_url: http://127.0.0.1:18188\n"
        "timeout_sec: 3600\n",
        encoding="utf-8",
    )
    pipeline_file = tmp_path / "pipeline.amd.yaml"
    pipeline_file.write_text(
        "image:\n"
        "  width: 480\n"
        "  height: 832\n"
        "keyframe:\n"
        "  core_only: true\n"
        "  model_name: sdxl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FACTORY_COMFY_CONFIG_FILE", str(comfy_file))
    monkeypatch.setenv("FACTORY_PIPELINE_OVERRIDE_FILE", str(pipeline_file))

    context = Context(
        project_root=tmp_path / "project",
        config_dir=config_dir,
        dry_run=True,
    )

    assert len(context.comfy_workers) == 1
    assert context.comfy_workers[0].base == "http://127.0.0.1:18188"
    assert context.comfy_workers[0].timeout == 3600
    assert context.cfg("image", "width") == 480
    assert context.cfg("image", "height") == 832
    assert context.cfg("keyframe", "core_only") is True
    assert context.cfg("keyframe", "model_name") == "sdxl"
    assert context.cfg("keyframe", "qwen_steps") == 4
    assert context.cfg("output", "width") == 1080


@pytest.mark.parametrize(
    "environment_name",
    ("FACTORY_COMFY_CONFIG_FILE", "FACTORY_PIPELINE_OVERRIDE_FILE"),
)
def test_context_rejects_override_path_that_is_not_a_file(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
) -> None:
    from drama.context import Context

    monkeypatch.setenv(environment_name, str(tmp_path / "missing.yaml"))

    with pytest.raises(RuntimeError, match=environment_name):
        Context(
            project_root=tmp_path / "project",
            config_dir=config_dir,
            dry_run=True,
        )


@pytest.mark.parametrize(
    "environment_name",
    ("FACTORY_COMFY_CONFIG_FILE", "FACTORY_PIPELINE_OVERRIDE_FILE"),
)
def test_context_rejects_non_mapping_override_yaml(
    tmp_path: Path,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
) -> None:
    from drama.context import Context

    invalid = tmp_path / f"{environment_name}.yaml"
    invalid.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    monkeypatch.setenv(environment_name, str(invalid))

    with pytest.raises(RuntimeError, match=environment_name):
        Context(
            project_root=tmp_path / "project",
            config_dir=config_dir,
            dry_run=True,
        )


def test_amd_yaml_is_single_comfy_sdxl_core_only(
    repo_root: Path,
) -> None:
    comfy = yaml.safe_load(
        (repo_root / "config" / "comfyui.amd.yaml").read_text(
            encoding="utf-8"
        )
    )
    pipeline = yaml.safe_load(
        (repo_root / "config" / "pipeline.amd.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert comfy == {
        "instances": [{"base_url": "http://127.0.0.1:18188"}],
        "timeout_sec": 3600,
    }
    assert pipeline["image"] == {"width": 480, "height": 832}
    assert pipeline["video"] == {
        "gen_width": 480,
        "gen_height": 832,
        "max_shot_sec": 8,
        "max_frames": 129,
    }
    assert pipeline["workflows"] == {"keyframe": "keyframe_flux_api.json"}
    assert pipeline["keyframe"] == {
        "core_only": True,
        "model_name": "sdxl",
        "checkpoint": "sd_xl_base_1.0.safetensors",
        "use_qwen_edit": False,
        "use_qwen_t2i": False,
        "qwen_hq": False,
        "qwen_scene_ref": False,
        "use_instantid": False,
        "use_ipadapter": False,
        "use_scene_ref": False,
        "style_lora": "",
    }


def test_core_only_keyframe_ignores_anchors_and_custom_routes(
    dry_ctx,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drama.agents import KeyframeGenerator
    from drama.schemas import Character, CharacterBible, Shot

    dry_ctx.pipeline["keyframe"].update(
        {
            "core_only": True,
            "model_name": "sdxl",
            "style_lora": "must-not-load.safetensors",
            "use_qwen_edit": True,
            "use_qwen_t2i": True,
            "use_instantid": True,
            "use_scene_ref": True,
        }
    )
    calls: dict[str, object] = {"uploads": 0}

    class Comfy:
        base = "http://127.0.0.1:18188"

        def upload_image(self, _path: str) -> None:
            calls["uploads"] = int(calls["uploads"]) + 1

        def load_workflow(self, path: Path) -> dict:
            calls["workflow_path"] = path
            return {"9": {"class_type": "SaveImage", "inputs": {}}}

        def inject(self, workflow: dict, params: dict) -> dict:
            calls["params"] = params
            return workflow

        def run(self, _workflow: dict, _out_dir: Path, **_kwargs) -> list[Path]:
            return [tmp_path / "keyframe.png"]

    comfy = Comfy()

    def acquire(shard: int, **kwargs):
        calls["shard"] = shard
        calls["lease"] = kwargs
        return comfy

    monkeypatch.setattr(dry_ctx, "comfy", acquire)
    generator = KeyframeGenerator(
        dry_ctx,
        CharacterBible(
            novel_title="test",
            characters=[
                Character(
                    char_id="hero",
                    name="Hero",
                    ref_images=["/anchors/hero.png"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        generator,
        "_resolve_anchors",
        lambda _shot: pytest.fail("core-only must not resolve anchors"),
    )
    monkeypatch.setattr(
        generator,
        "_apply_style_lora",
        lambda *_args: pytest.fail("core-only must not add custom nodes"),
    )
    shot = Shot(
        shot_id="S001",
        episode_id="E001",
        chapter_id="C001",
        scene_id="scene-001",
        characters=["hero"],
        visual_prompt_en="cinematic portrait",
    )

    generator(shot, 0)

    assert calls["lease"] == {
        "model_name": "sdxl",
        "min_vram_mib": 12_000,
    }
    assert calls["workflow_path"] == generator.wf_plain
    assert calls["uploads"] == 0
    params = calls["params"]
    assert params["REF_IMAGE"] == ""
    assert params["REF_IMAGE2"] == ""
    assert params["CONTROL_IMAGE"] == ""
    assert shot.status == "keyframe_ok"
