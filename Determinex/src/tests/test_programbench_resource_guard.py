from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import programbench_resource_guard as guard  # noqa: E402


def test_hyperfine_is_quarantined_by_default(monkeypatch):
    monkeypatch.delenv("DETERMINEX_PB_ALLOW_RESOURCE_RISK", raising=False)
    policy = guard.policy_for_eval(
        instance_id="sharkdp__hyperfine.327d5f4",
        scaffold_root="T:/determinex-programbench/determinex_pb_hyperfine_v1",
        filter_re="sharkdp",
    )
    assert policy.resource_sensitive is True
    assert policy.quarantined is True
    assert policy.workers == 1
    assert policy.branch_workers == 1
    assert policy.docker_cpus == 1


def test_hyperfine_can_run_only_with_explicit_risk_ack(monkeypatch):
    monkeypatch.setenv("DETERMINEX_PB_ALLOW_RESOURCE_RISK", "1")
    policy = guard.policy_for_eval(instance_id="sharkdp__hyperfine.327d5f4")
    assert policy.resource_sensitive is True
    assert policy.quarantined is False
    assert policy.workers == 1
    assert policy.branch_workers == 1
    assert policy.docker_cpus == 1


def test_normal_eval_command_has_required_resource_flags(monkeypatch):
    monkeypatch.delenv("DETERMINEX_PB_ALLOW_RESOURCE_RISK", raising=False)
    cmd, policy = guard.build_eval_cmd(
        scaffold_root="T:/determinex-programbench/determinex_pb_nomino_v1",
        filter_re="yaa110",
        instance_id="yaa110__nomino.f892499",
        requested_workers=8,
    )
    assert policy.quarantined is False
    assert policy.workers == 1
    assert "--branch-workers" in cmd
    assert "--docker-cpus" in cmd
    guard.assert_no_unguarded_eval_command(cmd)


def test_run_root_containing_hyperfine_is_quarantined(tmp_path, monkeypatch):
    monkeypatch.delenv("DETERMINEX_PB_ALLOW_RESOURCE_RISK", raising=False)
    root = tmp_path / "run"
    (root / "sharkdp__hyperfine.327d5f4").mkdir(parents=True)
    policy = guard.policy_for_eval(scaffold_root=root)
    assert policy.resource_sensitive is True
    assert policy.quarantined is True


def test_env_caps_workers_to_one_eval_lane(monkeypatch):
    monkeypatch.setenv("DETERMINEX_PB_MAX_WORKERS", "2")
    monkeypatch.setenv("DETERMINEX_PB_BRANCH_WORKERS", "1")
    monkeypatch.setenv("DETERMINEX_PB_DOCKER_CPUS", "2")
    policy = guard.policy_for_eval(
        instance_id="yaa110__nomino.f892499",
        requested_workers=16,
    )
    assert policy.workers == 1
    assert policy.branch_workers == 1
    assert policy.docker_cpus == 1


def test_unguarded_command_assertion_catches_raw_programbench_eval():
    with pytest.raises(AssertionError):
        guard.assert_no_unguarded_eval_command(
            ["uv", "run", "programbench", "eval", "T:/foo", "--force"]
        )
