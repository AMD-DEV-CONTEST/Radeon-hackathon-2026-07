"""Unit tests for the autotune L1/L2 layer (no GPU required).

We exercise hardware detection fallback, SkillPack scanning, the planner's
degrade ladder, and the hermes_s2-style fingerprint guard — all with mocked
profiles / temp pack dirs, so this runs on a plain dev box.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from screwshell.autotune.hardware import HardwareProfile, detect, QUANT_VRAM_GB
from screwshell.autotune.skillpack import SkillPack, scan_skillpacks, build_skill_map
from screwshell.autotune.planner import plan, CANONICAL_SKILLS


def _write_pack(root: Path, name: str, skill: str, vram: float,
                fingerprint: str = "Qwen/Qwen3.6-27B", kind: str = "lora",
                skills: list | None = None) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({
        "name": name, "kind": kind, "skill": skill,
        "skills": skills or [skill],
        "base_fingerprint": fingerprint, "vram_gb": vram,
        "domain_tags": [skill], "route_keywords": [skill],
        "smoke_test": {"prompt": "x", "expect_contains": ["y"]},
    }), encoding="utf-8")
    (d / "adapter.gguf").touch()  # real packs ship the weight file


def test_detect_no_gpu_returns_unknown():
    prof = detect()
    assert prof.vendor in ("amd", "nvidia", "unknown")


def test_scan_and_plan_full(tmp_path):
    for n, s, v, sk in [("btl3", "tool", 0.8, ["tool", "code"]),
                         ("cybersec", "security", 0.8, ["security"]),
                         ("rag_n7", "doc", 0.8, ["doc"]),
                         ("teichai", "agent", 0.8, ["agent"])]:
        _write_pack(tmp_path, n, s, v, skills=sk)
    packs = scan_skillpacks(tmp_path)
    assert set(packs) == {"btl3", "cybersec", "rag_n7", "teichai"}
    prof = HardwareProfile(vendor="amd", name="W7900", vram_total_gb=48.0)
    res = plan(prof, packs)
    assert res.degrade_level == "full"
    assert set(res.covered_skills) >= {"tool", "security", "doc", "agent"}
    assert "base_only" not in res.report
    # quant recommended should fit 18.9GB base + 4*0.8GB LoRA in 46GB usable
    assert res.quant is not None


def test_plan_degrades_on_small_gpu(tmp_path):
    _write_pack(tmp_path, "cybersec", "security", 0.8)
    prof = HardwareProfile(vendor="unknown", name="tiny", vram_total_gb=8.0)
    res = plan(prof, scan_skillpacks(tmp_path))
    assert res.degrade_level == "base_only"
    assert res.selected == []


def test_build_skill_map_rejects_fingerprint_mismatch(tmp_path):
    _write_pack(tmp_path, "hermes_like", "agent", 0.8,
                fingerprint="samscrack/Qwen3.6-27B-Opus-CoT-Stage1")
    packs = scan_skillpacks(tmp_path)
    sm = build_skill_map(packs, deployed_base="Qwen/Qwen3.6-27B")
    assert "agent" not in sm          # mismatched pack dropped (hermes_s2 guard)
    assert sm.get("base") is None     # base always maps to pure base


def test_scan_skips_folders_without_manifest(tmp_path):
    (tmp_path / "not-a-pack").mkdir()
    (tmp_path / "not-a-pack" / "adapter.gguf").write_text("x")
    assert scan_skillpacks(tmp_path) == {}


def test_example_skillpacks_scan_in_repo():
    repo_packs = Path(__file__).resolve().parents[1] / "screwshell" / "autotune" / "skillpacks"
    packs = scan_skillpacks(repo_packs)
    # the four shipped example packs
    assert {"btl3", "cybersec", "rag_n7", "teichai_plan"} <= set(packs)
    sm = build_skill_map(packs, deployed_base="Qwen/Qwen3.6-27B")
    assert sm["security"] == "cybersec"
    assert sm["doc"] == "rag_n7"
    assert sm["tool"] == "btl3"
    assert sm["agent"] == "teichai_plan"


# ----------------------------- #4 tuner / doctor -----------------------------

def test_tuner_base_only_enforces_铁律(tmp_path):
    from screwshell.autotune.tuner import resolve
    prof = HardwareProfile(vendor="unknown", name="tiny", vram_total_gb=8.0)
    res = plan(prof, scan_skillpacks(_write_fixture(tmp_path)))
    assert res.degrade_level == "base_only"
    spec = resolve(res, prof)
    assert spec.lora_pack_names == []          # 阵容铁律：不挂载任何 LoRA
    assert "纯基座" in spec.notes[0]


def test_tuner_full_keeps_all_selected(tmp_path):
    from screwshell.autotune.tuner import resolve
    prof = HardwareProfile(vendor="amd", name="W7900", vram_total_gb=48.0)
    res = plan(prof, scan_skillpacks(_write_fixture(tmp_path)))
    spec = resolve(res, prof)
    assert set(spec.lora_pack_names) == set(res.selected)
    # ctx now derived from real VRAM (≥131072 on a 48GB W7900), not 8192 cap
    assert spec.ctx_tokens >= 131072


def test_doctor_flags_missing_model_and_fingerprint(tmp_path):
    from screwshell.autotune.doctor import preflight
    packs = scan_skillpacks(_write_fixture(tmp_path, bad_fp=True))
    # selected will only contain the good pack; pass the bad one explicitly
    rep = preflight("/no/such/model.gguf", "", ["btl3", "hermes_like"],
                    packs, "Qwen/Qwen3.6-27B", port=8080,
                    profile=HardwareProfile.unknown())
    assert rep.ok is False
    levels = {i.msg: i.level for i in rep.items}
    assert any("底模文件缺失" in m for m in levels)
    # fingerprint mismatch is a blocking error
    assert any("hermes_s2" in m and levels[m] == "error" for m in levels)


# ----------------------------- #5 CLI assembly -----------------------------

def test_cli_json_runs_and_exits(tmp_path, capsys, monkeypatch):
    from screwshell.autotune import __main__ as cli
    fx = _write_fixture(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "autotune", "--packs-dir", str(fx),
        "--deploy-base", "Qwen/Qwen3.6-27B", "--model", "", "--json"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0               # no blocking errors (model omitted)
    out = json.loads(capsys.readouterr().out)
    assert out["plan"]["degrade_level"] in {"full", "reduced", "base_only"}
    assert "preflight_ok" in out and "spec" in out


def _write_fixture(tmp_path, bad_fp: bool = False):
    """Build a small 4-pack fixture dir; optionally inject a bad-fp pack."""
    for n, s, sk in [("btl3", "tool", ["tool", "code"]),
                     ("cybersec", "security", ["security"]),
                     ("rag_n7", "doc", ["doc"]),
                     ("teichai", "agent", ["agent"])]:
        _write_pack(tmp_path, n, s, 0.8, skills=sk)
    if bad_fp:
        _write_pack(tmp_path, "hermes_like", "agent", 0.8,
                    fingerprint="samscrack/Qwen3.6-27B-Opus-CoT-Stage1",
                    skills=["agent"])
    return tmp_path


# ----------------------------- #6 L3 governor -----------------------------

from screwshell.autotune.governor import (
    Governor, GovernorConfig, RuntimeMetrics, SwapStep, select_mode,
    cluster_steps, LlamaServerLifecycle,
)


def test_select_mode_roomy_vs_tight():
    assert select_mode(avail_vram_gb=48.0, roster_load_gb=20.0) == "roomy"
    assert select_mode(avail_vram_gb=16.0, roster_load_gb=20.0) == "tight"


def test_cluster_steps_groups_same_expert():
    steps = [
        SwapStep("s1", "A", []),
        SwapStep("s2", "A", ["s1"]),
        SwapStep("s3", "B", []),
        SwapStep("s4", "B", ["s3"]),
    ]
    plan = cluster_steps(steps)
    assert plan.feasible
    # s1,s2 are both A and should stay adjacent; same for s3,s4.
    assert plan.order.index("s2") == plan.order.index("s1") + 1
    assert plan.order.index("s4") == plan.order.index("s3") + 1
    assert plan.swaps == 1                      # A->B only
    assert plan.clusters == [["s1", "s2"], ["s3", "s4"]]


def test_cluster_steps_respects_deps_across_experts():
    steps = [
        SwapStep("s1", "A", []),
        SwapStep("s2", "B", ["s1"]),           # B depends on A
        SwapStep("s3", "A", ["s2"]),
    ]
    plan = cluster_steps(steps)
    assert plan.feasible
    assert plan.order == ["s1", "s2", "s3"]    # deps force this exact order
    assert plan.swaps == 2                      # A->B->A


def test_gear_low_tok_drops_ctx():
    g = Governor(initial_ctx=8192)
    for _ in range(2):
        assert g.observe(RuntimeMetrics(tokens_per_s=5.0)) == []
    acts = g.observe(RuntimeMetrics(tokens_per_s=5.0))   # 3rd -> drop gear
    assert any(a.kind == "set_ctx" and a.payload["ctx"] == 6144 for a in acts)


def test_gear_empty_rate_disables_thinking():
    g = Governor()
    acts = g.observe(RuntimeMetrics(empty_rate=0.5, thinking_on=True))
    assert any(a.kind == "set_thinking" and a.payload["thinking"] is False
               for a in acts)


def test_gear_vram_enables_kv_quant():
    g = Governor()
    acts = g.observe(RuntimeMetrics(vram_pct=95.0))
    assert any(a.kind == "set_kv_quant" and a.payload["kv_quant"] == "q8_0"
               for a in acts)


def test_swap_cap_alert():
    g = Governor()
    g._swap_count = g.cfg.max_swaps_per_task     # at the cap
    g.note_swap()                                # now over
    alert = g.swap_cap_exceeded()
    assert alert is not None and alert.kind == "alert"


def test_lifecycle_start_stop_mock(monkeypatch):
    import screwshell.autotune.governor as G

    class FakePopen:
        pid = 12345

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(G, "_port_free", lambda p, h="127.0.0.1": True)
    monkeypatch.setattr(G, "_health_ok", lambda u, t=2.0: True)
    monkeypatch.setattr(G.subprocess, "Popen", lambda *a, **k: FakePopen())

    class _Resp:
        def read(self):
            return b"{}"

    monkeypatch.setattr(G.urllib.request, "urlopen", lambda *a, **k: _Resp())

    lc = LlamaServerLifecycle("fake --lora {lora}", port=8099)
    to_serve = lc.start("btl3/adapter.gguf")
    assert lc.current_lora == "btl3/adapter.gguf"
    assert isinstance(to_serve, float)
    lc.stop()                                   # must not raise

