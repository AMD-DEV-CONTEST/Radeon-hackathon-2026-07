"""On a constrained GPU, keeping the monitor resident hangs the session instead of speeding it up.

FOUND 2026-07-31 by running the first-E2E workflow, not by reading code. Step 1 completed, step 2's
Compiler Oracle passed, and then the session sat in the Monitor call for 19 minutes: identical CPU
time across two samples 15 minutes apart, no child process, no container, no error, no timeout. It
would have sat there indefinitely.

Cause: `_ollama_extra` decided keep-alive with `if role in keep_hot ... elif role == "monitor"`, and
tier 0 -- the ~6GB rig the `elif` was written about, with the VRAM arithmetic spelled out in its own
comment -- listed "monitor" in keep_hot. So on the one machine that needed the eviction, the branch
performing it was unreachable, and the observer stayed pinned beside the builder. Both in 6 GB means
the observer's prefill runs on the CPU.

Measured on the 6.0 GB card this suite runs on:

    observer requested while the builder is pinned, keep_alive=-1   ->  >19 min, no response
    observer requested while the builder is pinned, keep_alive=0    ->  39s, 100% GPU

The policy is now keyed on `max_loaded`, so a profile that says "one model at a time" gets that
honoured no matter which roles a later edit adds to keep_hot -- a list edit cannot silently restore
the hang. `hive.executor` held a byte-for-byte copy of this function and now imports it, because a
copy would have kept the old behaviour on whichever call sites resolve through the executor.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hive import api_client as A  # noqa: E402
from hive import executor as E  # noqa: E402
from hive import hardware as H  # noqa: E402

OLLAMA = "ollama/determinex-observer-v6-dsl"


def _flat(text: str) -> str:
    """Collapse whitespace runs so a source grep survives the formatter.

    These guards match exact source text. `ruff format` changed the exact whitespace they
    keyed on -- three spaces before a comment became two, two after a comma became one, a
    one-line argument pair got split across two -- and every one of them went silently
    vacuous, reporting "found in no files", which is also what they print when the thing they
    guard has been DELETED. A guard whose blind mode is indistinguishable from the condition
    it guards against is not guarding.

    Comparing flattened text keeps the check identical -- same tokens, same order -- while
    dropping a dependency on spacing that a formatter is entitled to change at any time.
    """
    return re.sub(r"\s+", " ", text)


def _profile(tier: int) -> H.HardwareProfile:
    """A profile carrying the real lifecycle policy for a tier."""
    return H.HardwareProfile(
        tier=tier, vram_gb=6.0, ram_gb=32.0, gpu_count=1, lifecycle=H._lifecycle_for_tier(tier)
    )


class TestTheMonitorIsEvictedWhenOnlyOneModelFits:
    def test_tier_0_evicts_the_monitor(self):
        """The regression. Tier 0 returned -1 here, and a session hung for 19 minutes."""
        assert A._ollama_extra(OLLAMA, "monitor", _profile(0)) == {"keep_alive": 0}

    def test_capacity_beats_keep_hot_membership(self):
        """A profile saying one-model-at-a-time must evict the monitor even if a later edit
        puts "monitor" back into keep_hot. This is the exact contradiction that caused the hang."""
        contradictory = H.HardwareProfile(
            tier=0,
            vram_gb=6.0,
            ram_gb=32.0,
            gpu_count=1,
            lifecycle=H.ModelLifecyclePolicy(
                keep_hot=["builder", "monitor"], max_loaded=1, swap_strategy="role_priority"
            ),
        )
        assert A._ollama_extra(OLLAMA, "monitor", contradictory) == {"keep_alive": 0}, (
            "keep_hot must not be able to pin the monitor on a rig that holds one model"
        )

    def test_the_builder_still_stays_hot_on_tier_0(self):
        """The fix must not throw away the reason keep_hot exists."""
        assert A._ollama_extra(OLLAMA, "builder", _profile(0)) == {"keep_alive": -1}
        assert "builder" in _profile(0).lifecycle.keep_hot

    def test_roomier_tiers_may_keep_the_monitor_hot(self):
        for tier in (1, 2):
            policy = _profile(tier).lifecycle
            assert policy.max_loaded > 1, f"tier {tier} should hold more than one model"
            assert A._ollama_extra(OLLAMA, "monitor", _profile(tier)) == {"keep_alive": -1}, (
                f"tier {tier} has room; evicting the monitor there would just cost reloads"
            )

    def test_oracle_and_architect_keep_the_handoff_window(self):
        """generate_dag hands oracle -> architect; a 0 here would reload qwen7b mid-handoff."""
        for role in ("oracle", "architect"):
            assert A._ollama_extra(OLLAMA, role, _profile(0)) == {"keep_alive": 300}

    def test_an_unknown_role_gets_the_default_not_a_pin(self):
        assert A._ollama_extra(OLLAMA, "some-new-role", _profile(0)) == {"keep_alive": 300}

    def test_api_models_are_untouched(self):
        assert A._ollama_extra("anthropic/claude-sonnet-4-6", "monitor", _profile(0)) == {}

    def test_no_profile_falls_back_without_pinning_the_monitor(self):
        """The fallback path must not be the one that hangs."""
        assert A._ollama_extra(OLLAMA, "monitor", None) == {"keep_alive": 0}
        assert A._ollama_extra(OLLAMA, "builder", None) == {"keep_alive": -1}


class TestTierZeroStatesItsRealCapacity:
    def test_tier_0_holds_one_model(self):
        """max_loaded is load-bearing now -- the eviction decision reads it. Raising it back to 2
        without revisiting the 6 GB arithmetic reintroduces the hang."""
        assert _profile(0).lifecycle.max_loaded == 1, (
            "tier 0 is a ~6GB card; builder 1.8GB + observer 3.5GB + KV cache does not fit, and "
            "claiming it does is what pinned both models and stalled a session for 19 minutes"
        )

    def test_capacity_rises_with_tier(self):
        assert (
            _profile(0).lifecycle.max_loaded
            < _profile(1).lifecycle.max_loaded
            <= _profile(2).lifecycle.max_loaded
        )


class TestThereIsOnlyOneImplementation:
    def test_the_executor_uses_the_canonical_function(self):
        assert E._ollama_extra is A._ollama_extra, (
            "hive.executor had a byte-for-byte copy of this policy. Two copies means the same "
            "session can evict the observer down one path and pin it down the other."
        )

    @pytest.mark.parametrize("role", ["builder", "monitor", "oracle", "architect", "unknown"])
    @pytest.mark.parametrize("tier", [-1, 0, 1, 2])
    def test_both_modules_agree_everywhere(self, role, tier):
        profile = _profile(tier)
        assert A._ollama_extra(OLLAMA, role, profile) == E._ollama_extra(OLLAMA, role, profile)

    def test_no_second_copy_has_reappeared(self):
        """A textual guard: the body of the policy must exist in exactly one module."""
        needle = _flat("keep_alive = -1   # builder: never evict")
        hits = [
            p.name
            for p in (REPO_ROOT / "scripts" / "hive").glob("*.py")
            if needle in _flat(p.read_text(encoding="utf-8", errors="replace"))
        ]
        assert hits == ["api_client.py"], f"the keep-alive policy is duplicated in {hits}"


def test_the_real_machine_does_not_pin_the_monitor():
    """End-to-end against the actual detected hardware, whatever it is."""
    hw = H.get_hw_profile()
    extra = A._ollama_extra(OLLAMA, "monitor", hw)
    if hw.lifecycle.max_loaded <= 1:
        assert extra == {"keep_alive": 0}, (
            f"this host holds {hw.lifecycle.max_loaded} model(s) and is pinning the monitor anyway"
        )
    else:
        assert extra in ({"keep_alive": -1}, {"keep_alive": 0})
