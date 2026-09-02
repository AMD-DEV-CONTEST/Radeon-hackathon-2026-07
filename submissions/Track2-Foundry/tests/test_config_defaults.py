"""Regression tests: dataset sizes come from the loaded config, not a
number hardcoded in the prompt. Tonight the agent proposed 900/100
while the config said otherwise."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import foundry.datagen as datagen_mod
from foundry.agent import Agent
from foundry.spec import TaskSpec
from foundry.tools import ToolBox

CFG = {
    "run": {"out_root": None, "seed": 17},  # out_root set per-test
    "teacher": {"base_url": "http://test/v1"},
    "datagen": {"n_train": 123, "n_holdout": 45, "max_attempts_factor": 3},
}


def test_agent_prompt_carries_config_sizes(tmp_path):
    cfg = {**CFG, "run": {**CFG["run"], "out_root": str(tmp_path)}}
    toolbox = ToolBox(cfg, "cfg.toml", teacher_ctl=None)
    agent = Agent(cfg, toolbox)
    system = agent.messages[0]["content"]
    assert "123" in system and "45" in system, "config sizes must be substituted"
    assert "[[N_TRAIN]]" not in system, "placeholder must not survive"
    assert "900" not in system


def test_generate_dataset_defaults_from_config(tmp_path, monkeypatch):
    cfg = {**CFG, "run": {**CFG["run"], "out_root": str(tmp_path)}}
    tb = ToolBox(cfg, "cfg.toml", teacher_ctl=None)
    tb.spec = TaskSpec.load(
        Path(__file__).resolve().parent.parent / "specs" / "triage.json")
    tb.run_dir = tmp_path

    seen = {}

    def fake_generate(cfg_arg, run_dir, spec, focus=None, augment=False,
                      progress_cb=None):
        seen["n_train"] = cfg_arg["datagen"]["n_train"]
        seen["n_holdout"] = cfg_arg["datagen"]["n_holdout"]
        return {"acceptance_rate": 1.0}

    monkeypatch.setattr(datagen_mod, "generate", fake_generate)
    tb.dispatch("generate_dataset", {})  # no explicit sizes
    assert seen == {"n_train": 123, "n_holdout": 45}


def test_explicit_sizes_still_win(tmp_path, monkeypatch):
    cfg = {**CFG, "run": {**CFG["run"], "out_root": str(tmp_path)}}
    tb = ToolBox(cfg, "cfg.toml", teacher_ctl=None)
    tb.spec = TaskSpec.load(
        Path(__file__).resolve().parent.parent / "specs" / "triage.json")
    tb.run_dir = tmp_path

    seen = {}

    def fake_generate(cfg_arg, run_dir, spec, focus=None, augment=False,
                      progress_cb=None):
        seen["n_train"] = cfg_arg["datagen"]["n_train"]
        return {"acceptance_rate": 1.0}

    monkeypatch.setattr(datagen_mod, "generate", fake_generate)
    tb.dispatch("generate_dataset", {"n_train": 54, "n_holdout": 12})
    assert seen["n_train"] == 54
