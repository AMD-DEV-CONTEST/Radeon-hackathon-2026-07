"""P4 — config-version snapshot (BUILD_OBSERVATORY_V3 §2.9, D3, T9/T10).

Pure-function tests: snapshot building, stable version id, rollback command
generation (T10: system gives a command, human/runtime executes �?never
auto-applies), and that /props shape variation degrades gracefully.
"""
from __future__ import annotations

from screwshell.ui import app as ui_app
from screwshell.ui.analysis import build_config_snapshot, rollback_command


def _props(n_ctx=4096, flash=False, model="/m/model"):
    return {"default_generation_settings": {
                "n_ctx": n_ctx, "n_gpu_layers": 40, "flash_attn": flash,
                "model": model, "seed": -1},
            "model_path": model}


def test_snapshot_builds_and_is_stable():
    s1 = build_config_snapshot(_props(), ts=1.0)
    s2 = build_config_snapshot(_props(), ts=2.0)
    assert s1["vid"] == s2["vid"]  # identical config -> same version id
    assert s1["settings"]["n_ctx"] == 4096
    assert s1["settings"]["flash_attn"] is False


def test_snapshot_detects_change():
    a = build_config_snapshot(_props(n_ctx=4096), ts=1.0)
    b = build_config_snapshot(_props(n_ctx=8192), ts=2.0)
    assert a["vid"] != b["vid"]


def test_rollback_command_is_copy_paste_not_autoexec():
    snap = build_config_snapshot(_props(n_ctx=8192, flash=True), ts=1.0)
    cmd = rollback_command(snap)
    assert "rollback to" in cmd
    assert "python -m screwshell.gateway.relay" in cmd
    assert "--ctx-size 8192" in cmd
    assert "--flash-attn" in cmd


def test_normalize_handles_missing_keys_gracefully():
    # /props without default_generation_settings must not crash / fabricate
    s = build_config_snapshot({"some_other": "x"}, ts=1.0)
    assert isinstance(s["settings"], dict)
    assert s["settings"] == {}


def test_snapshot_includes_effective_mode_annotation():
    # §5 T9 — Wave 2a added the `effective` field: every setting is annotated
    # with whether it is a hot-update ("hot") or restart-time ("restart") flag.
    props = {"default_generation_settings": {
                 "n_ctx": 131072, "flash_attn": True,
                 "cache_type_k": "f16", "model": "/m/model"},
             "model_path": "/m/model"}
    snap = build_config_snapshot(props, ts=1.0)
    assert "effective" in snap
    eff = snap["effective"]
    # restart-time flags
    assert eff["n_ctx"] == "restart"
    assert eff["flash_attn"] == "restart"
    assert eff["cache_type_k"] == "restart"
    # every key in settings has a corresponding effective annotation
    assert set(eff.keys()) == set(snap["settings"].keys())


def test_ingest_dedupes_identical_props():
    saved = list(ui_app._CONFIG_VERSIONS)
    ui_app._CONFIG_VERSIONS.clear()
    try:
        ui_app._obs_state["props"] = _props()
        ui_app._maybe_record_config_version()
        ui_app._maybe_record_config_version()  # unchanged -> no new version
        assert len(ui_app._CONFIG_VERSIONS) == 1
        ui_app._obs_state["props"] = _props(n_ctx=8192)
        ui_app._maybe_record_config_version()
        assert len(ui_app._CONFIG_VERSIONS) == 2
    finally:
        ui_app._CONFIG_VERSIONS.clear()
        ui_app._CONFIG_VERSIONS.extend(saved)
        ui_app._obs_state["props"] = None
