"""Does Determinex see the accelerator it is actually running on?

WHY THIS EXISTS
---------------
`hardware.profile_hardware` probed `nvidia-smi` and nothing else. On an AMD or Apple machine that
probe fails, so it fell through to `tier -1` = "CPU-only": a 24 GB Radeon or a 64 GB M3 Max was
invisible. The consequences are not cosmetic --

    tier -1  ->  max_local_models() == 0
                 max_parallel_steps == 1
                 lifecycle keep_hot == []          (nothing stays resident)

-- so the strongest available hardware was driven as the weakest possible host, while sitting on more
memory than the tier-2 threshold. AMD is the specific case that matters for a ROCm target.

WHAT IS AND IS NOT VERIFIED HERE
--------------------------------
NVIDIA is verified against the real machine this suite runs on. AMD, Intel Arc and Apple are verified
by **simulating the vendor tools' output**, because no such hardware is available here. That is a real
limitation and is stated rather than papered over: these tests prove the parsing, the unit scaling and
the tier arithmetic, NOT that `amd-smi` on a real MI300 prints what is simulated below. The formats
come from the documented CSV shapes.

The unit scaling is the part most likely to be silently wrong, so it is tested explicitly: `amd-smi`
reports MB while `rocm-smi --showmeminfo vram --csv` reports BYTES. Reading bytes as MB would put a
24 GB card in tier 0 and read as a merely-conservative choice rather than a bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hive import hardware as H  # noqa: E402


def _fake_run(responses: dict[str, tuple[int, str]]):
    """subprocess.run stub keyed on the executable name."""

    def run(argv, *_a, **_k):
        exe = Path(str(argv[0])).name.lower().removesuffix(".exe")
        rc, out = responses.get(exe, (1, ""))
        if rc == -1:
            raise FileNotFoundError(exe)
        return subprocess.CompletedProcess(argv, rc, out, "")

    return run


# ── NVIDIA: verified against the real host ───────────────────────────────────────────────────────


def test_this_machine_is_detected_and_is_not_reported_as_cpu_only():
    """Not a mock. If this box has an accelerator, Determinex must see it."""
    vendor, torch_device, vram_gb, count = H.detect_accelerator()
    if vendor == "cpu":
        pytest.skip("no accelerator on this host; nothing to assert about detection")
    assert vram_gb > 0 and count >= 1
    assert torch_device in {"cuda", "xpu", "mps"}
    profile = H.profile_hardware()
    assert profile.accelerator == vendor
    assert profile.torch_device == torch_device
    assert profile.tier > -1, (
        f"{vendor} with {vram_gb:.1f} GB was still classified CPU-only (tier -1), which zeroes "
        f"max_local_models() and keeps nothing resident"
    )


# ── AMD: simulated vendor output ─────────────────────────────────────────────────────────────────


def test_amd_is_detected_via_rocm_smi_and_bytes_are_not_read_as_megabytes(monkeypatch):
    """`rocm-smi --showmeminfo vram --csv` reports BYTES. 24 GB must land in tier 2."""
    rocm_csv = (
        "device,VRAM Total Memory (B),VRAM Total Used Memory (B)\ncard0, 25757220864, 1048576\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),  # absent, as on an AMD box
                "amd-smi": (-1, ""),  # older ROCm
                "rocm-smi": (0, rocm_csv),
            }
        ),
    )
    vendor, torch_device, vram_gb, count = H.detect_accelerator()
    assert vendor == "amd", f"expected amd, got {vendor}"
    assert torch_device == "cuda", (
        "a ROCm build of torch keeps the 'cuda' device name; reporting 'rocm' here would hand "
        "callers a device string PyTorch does not accept"
    )
    assert 23.0 < vram_gb < 25.0, f"24 GB card parsed as {vram_gb:.1f} GB — unit scaling is wrong"
    assert count == 1


def test_amd_multi_gpu_reports_the_largest_card_and_the_count(monkeypatch):
    rocm_csv = "device,VRAM Total Memory (B)\ncard0, 17163091968\ncard1, 25757220864\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (-1, ""),
                "rocm-smi": (0, rocm_csv),
            }
        ),
    )
    _vendor, _dev, vram_gb, count = H.detect_accelerator()
    assert count == 2
    assert 23.0 < vram_gb < 25.0, "should report the largest card, as the NVIDIA path does"


def test_amd_smi_megabytes_are_scaled_correctly(monkeypatch):
    """The newer tool reports MB, not bytes — the opposite scaling mistake."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (0, "gpu,vram_size\n0,24560\n"),
            }
        ),
    )
    vendor, _dev, vram_gb, count = H.detect_accelerator()
    assert vendor == "amd"
    assert 23.0 < vram_gb < 25.0, f"24560 MB parsed as {vram_gb:.1f} GB"
    assert count == 1


def test_an_amd_rig_reaches_tier_2_and_keeps_models_resident(monkeypatch):
    """The whole point: the tier must follow the memory, so the lifecycle policy stops starving."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (-1, ""),
                "rocm-smi": (0, "device,VRAM Total Memory (B)\ncard0, 25757220864\n"),
            }
        ),
    )
    monkeypatch.setattr(H.ThermalProfile, "measure", staticmethod(lambda: H.ThermalProfile()))
    profile = H.profile_hardware()
    assert profile.accelerator == "amd"
    assert profile.tier == 2, f"24 GB AMD landed in tier {profile.tier}, not 2"
    assert profile.max_local_models() > 0
    assert profile.lifecycle.keep_hot, "tier 2 must keep models resident; an empty list is tier -1"
    assert "AMD" in profile.accelerator_label and "ROCm" in profile.accelerator_label


# ── Apple Silicon ────────────────────────────────────────────────────────────────────────────────


def test_apple_silicon_reports_a_share_of_unified_memory(monkeypatch):
    """Unified memory is not a separate pool. Claiming all of it would put an 8 GB Mac in tier 0 and
    start swapping under a 3B model, so a fraction is reported."""
    monkeypatch.setattr(H.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(H.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (-1, ""),
                "rocm-smi": (-1, ""),
                "sysctl": (0, str(64 * 1024**3)),  # 64 GB M-series
            }
        ),
    )
    vendor, torch_device, vram_gb, count = H.detect_accelerator()
    assert vendor == "apple"
    assert torch_device == "mps", "Metal is reached through torch's 'mps' device, not 'cuda'"
    assert 40 < vram_gb < 64, f"expected a fraction of 64 GB, got {vram_gb:.1f}"
    assert count == 1


def test_intel_mac_is_not_reported_as_apple_silicon(monkeypatch):
    """`mps` does not exist on an Intel Mac; handing it to torch would raise."""
    monkeypatch.setattr(H.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(H.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (-1, ""),
                "rocm-smi": (-1, ""),
                "sysctl": (0, str(32 * 1024**3)),
            }
        ),
    )
    vendor, torch_device, _vram, _count = H.detect_accelerator()
    assert vendor == "cpu" and torch_device == "cpu"


# ── No accelerator ───────────────────────────────────────────────────────────────────────────────


def test_a_machine_with_no_accelerator_falls_back_to_cpu_honestly(monkeypatch):
    monkeypatch.setattr(H.platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "run", _fake_run({}))  # every tool absent
    vendor, torch_device, vram_gb, count = H.detect_accelerator()
    assert (vendor, torch_device, vram_gb, count) == ("cpu", "cpu", 0.0, 0)


class TestAcceleratorlessCapacityComesFromRam:
    """A host with no discrete GPU is not a host with no capacity.

    Found 2026-07-31: `tier` was derived from `vram_gb` alone, so EVERY machine without a
    discrete GPU landed on tier -1 -- `max_local_models()` 0, `keep_hot` empty -- and a 128 GB
    workstation was scored identically to an 8 GB laptop. `ram_gb` was already measured and then
    used for nothing.

    Wrong on its own terms, because Ollama and llama.cpp run models out of system RAM, which is
    exactly how a CPU-only Determinex install works. And `keep_hot=[]` was backwards: a model
    reload costs MORE on a CPU host, so the machine that most needed the builder kept resident
    was the one told to keep nothing.
    """

    @staticmethod
    def _cpu_host(monkeypatch, ram_gb: float):
        monkeypatch.setattr(H, "detect_accelerator", lambda: ("cpu", "cpu", 0.0, 0))
        monkeypatch.setattr(H, "_detect_ram_gb", lambda: ram_gb)
        return H.profile_hardware()

    @pytest.mark.parametrize(
        "ram_gb,expected_tier",
        [
            (8.0, -1),  # 8 - 8 reserve = 0 usable: genuinely cannot host a model
            (12.0, 0),  # 4 usable: the 1.5B builder fits
            (16.0, 0),  # 8 usable
            (24.0, 1),  # 16 usable
            (32.0, 1),
            (64.0, 1),  # capped at 1 -- see below
            (128.0, 1),
        ],
    )
    def test_tier_follows_system_ram_when_there_is_no_accelerator(
        self, monkeypatch, ram_gb, expected_tier
    ):
        assert self._cpu_host(monkeypatch, ram_gb).tier == expected_tier

    def test_a_big_cpu_host_can_actually_hold_models_and_keeps_the_builder_hot(self, monkeypatch):
        """The defect in one assertion: this used to be 0 models and nothing resident."""
        hw = self._cpu_host(monkeypatch, 32.0)
        assert hw.max_local_models() > 0
        assert "builder" in hw.lifecycle.keep_hot

    def test_an_eight_gig_host_is_still_honestly_tier_minus_one(self, monkeypatch):
        """The fix must not become "everything is fine everywhere"."""
        hw = self._cpu_host(monkeypatch, 8.0)
        assert hw.tier == -1
        assert hw.max_local_models() == 0

    def test_cpu_capacity_is_capped_below_the_multi_gpu_tier(self, monkeypatch):
        """Tier 2 means one branch per GPU. A CPU host has no GPUs to branch across."""
        assert self._cpu_host(monkeypatch, 512.0).tier == 1

    def test_a_cpu_host_never_runs_parallel_steps_however_much_ram_it_has(self, monkeypatch):
        """Having RAM does not make concurrent branches safe on one shared CPU."""
        for ram in (16.0, 64.0, 512.0):
            assert self._cpu_host(monkeypatch, ram).max_parallel_steps == 1

    def test_the_reserve_is_actually_withheld(self, monkeypatch):
        """A host right at a threshold must fall below it once the reserve is taken out."""
        # 11.5 GB is the tier-1 threshold. 11.5 + 8 reserve = 19.5 GB of RAM is the first host
        # that should reach it; one gigabyte less must not.
        assert self._cpu_host(monkeypatch, 19.5).tier == 1
        assert self._cpu_host(monkeypatch, 18.5).tier == 0

    def test_the_basis_for_the_tier_is_recorded_not_left_to_inference(self, monkeypatch):
        assert self._cpu_host(monkeypatch, 32.0).capacity_basis == "system_ram"
        assert self._cpu_host(monkeypatch, 0.0).capacity_basis == "none"

    def test_the_label_states_the_ram_it_is_relying_on(self, monkeypatch):
        label = self._cpu_host(monkeypatch, 32.0).accelerator_label
        assert "32.0 GB system RAM" in label, label

    @pytest.mark.parametrize(
        "vendor,device,vram,count,expected_tier,expected_parallel",
        [
            ("nvidia", "cuda", 24.0, 1, 2, 2),
            ("nvidia", "cuda", 6.0, 1, 0, 1),
            ("amd", "cuda", 24.0, 1, 2, 2),
            ("intel", "xpu", 16.0, 1, 1, 2),
            ("apple", "mps", 48.0, 1, 2, 2),
            ("nvidia", "cuda", 24.0, 2, 2, 2),
        ],
    )
    def test_accelerator_hosts_are_untouched_by_the_ram_path(
        self, monkeypatch, vendor, device, vram, count, expected_tier, expected_parallel
    ):
        """The RAM fallback must not perturb any machine that has an accelerator."""
        monkeypatch.setattr(H, "detect_accelerator", lambda: (vendor, device, vram, count))
        monkeypatch.setattr(H, "_detect_ram_gb", lambda: 32.0)
        hw = H.profile_hardware()
        assert hw.tier == expected_tier
        assert hw.max_parallel_steps == expected_parallel
        assert hw.capacity_basis == "vram"

    def test_one_threshold_table_serves_both_memory_pools(self):
        """VRAM and system RAM must not drift to different cutoffs."""
        for gb, tier in ((23.5, 2), (11.5, 1), (3.5, 0), (3.49, -1)):
            assert H._tier_for_memory(gb) == tier


class TestWindowsOnArmIsNamedWithoutClaimingAnNpu:
    """Snapdragon X has an Adreno GPU and a Hexagon NPU, and Determinex uses neither.

    There is no PyTorch backend for them on Windows ARM64 and Ollama runs the ARM64 CPU path. So
    the honest handling is the RAM path above plus a display-only note -- naming the platform so a
    user can see it WAS recognised, without a probe that implies an accelerator we never call.
    """

    def test_a_snapdragon_host_is_named(self, monkeypatch):
        monkeypatch.setattr(H.platform, "machine", lambda: "ARM64")
        monkeypatch.setattr(H.platform, "processor", lambda: "Snapdragon(R) X Elite - X1E80100")
        assert "Snapdragon" in H._platform_note()

    def test_a_generic_arm64_host_is_named_arm64(self, monkeypatch):
        monkeypatch.setattr(H.platform, "machine", lambda: "aarch64")
        monkeypatch.setattr(H.platform, "processor", lambda: "")
        assert H._platform_note() == "ARM64"

    def test_x86_gets_no_note(self, monkeypatch):
        monkeypatch.setattr(H.platform, "machine", lambda: "AMD64")
        monkeypatch.setattr(H.platform, "processor", lambda: "Intel64 Family 6")
        assert H._platform_note() == ""

    def test_the_note_never_becomes_a_torch_device_or_a_vendor(self, monkeypatch):
        """The whole point: naming the platform must not claim an accelerator."""
        monkeypatch.setattr(H, "detect_accelerator", lambda: ("cpu", "cpu", 0.0, 0))
        monkeypatch.setattr(H, "_detect_ram_gb", lambda: 32.0)
        monkeypatch.setattr(H.platform, "machine", lambda: "ARM64")
        monkeypatch.setattr(H.platform, "processor", lambda: "Snapdragon(R) X Elite")
        hw = H.profile_hardware()
        assert hw.accelerator == "cpu"
        assert hw.torch_device == "cpu"
        assert hw.gpu_count == 0
        assert hw.vram_gb == 0.0
        assert "Snapdragon" in hw.accelerator_label
        # And no NPU/GPU claim anywhere in what a user reads.
        assert "NPU" not in hw.accelerator_label
        assert "Hexagon" not in hw.accelerator_label
        assert "Adreno" not in hw.accelerator_label

    def test_the_note_is_display_only_and_absent_when_an_accelerator_answered(self, monkeypatch):
        monkeypatch.setattr(H, "detect_accelerator", lambda: ("nvidia", "cuda", 24.0, 1))
        monkeypatch.setattr(H, "_detect_ram_gb", lambda: 32.0)
        monkeypatch.setattr(H.platform, "machine", lambda: "ARM64")
        assert H.profile_hardware().platform_note == ""


def test_a_vendor_tool_that_crashes_does_not_abort_detection(monkeypatch):
    """A broken nvidia-smi on an AMD box must not stop the AMD probe from running."""

    def run(argv, *_a, **_k):
        exe = Path(str(argv[0])).name.lower().removesuffix(".exe")
        if exe == "nvidia-smi":
            raise OSError("driver mismatch")
        if exe == "rocm-smi":
            return subprocess.CompletedProcess(
                argv, 0, "device,VRAM Total Memory (B)\ncard0, 17163091968\n", ""
            )
        raise FileNotFoundError(exe)

    monkeypatch.setattr(subprocess, "run", run)
    vendor, _dev, vram_gb, _count = H.detect_accelerator()
    assert vendor == "amd" and vram_gb > 15


# ── Tier arithmetic ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "advertised_gb,reported_gib,expected_tier",
    [
        (24, 24564 / 1024, 2),  # RTX 4090 / 24 GB Radeon -- reports 23.99 GiB
        (48, 49140 / 1024, 2),
        (12, 12288 / 1024, 1),  # 12 GB card -- reports 12.0
        (12, 12030 / 1024, 1),  # ... and one that reports slightly under
        (8, 8192 / 1024, 0),
        (4, 4096 / 1024, 0),
        (4, 3900 / 1024, 0),  # a 4 GB card reporting under
        (2, 2048 / 1024, -1),
    ],
)
def test_an_advertised_card_size_lands_in_the_tier_it_should(
    advertised_gb, reported_gib, expected_tier, monkeypatch
):
    """Cards report slightly less than they are sold as, and the thresholds used to be literal.

    `vram_gb >= 24` meant a 24 GB card (24564 MiB = 23.99 GiB) was tier 1, not tier 2 -- halving
    max_parallel_steps and dropping `oracle` and `architect` out of keep_hot on the strongest rigs.
    This affected NVIDIA exactly as much as AMD; it only surfaced while adding AMD detection.
    """
    monkeypatch.setattr(H, "detect_accelerator", lambda: ("nvidia", "cuda", reported_gib, 1))
    monkeypatch.setattr(H.ThermalProfile, "measure", staticmethod(lambda: H.ThermalProfile()))
    profile = H.profile_hardware()
    assert profile.tier == expected_tier, (
        f"a {advertised_gb} GB card reporting {reported_gib:.2f} GiB landed in tier {profile.tier}, "
        f"expected {expected_tier}"
    )


def test_the_top_tier_actually_keeps_the_extra_roles_resident():
    """Guards what the tier is FOR. If tier 2's policy ever matched tier 1's, the fix above would be
    cosmetic.

    Reads the policy objects directly. This used to `inspect.getsource(profile_hardware)` and grep
    for the literal `"oracle", "architect"`, because the tier map was a dict inside that function
    and there was no other way to reach it. It broke on 2026-07-31 when the map moved to
    `_lifecycle_for_tier` -- the policy was unchanged and correct, and the test failed anyway, which
    is what a check on a symbol's source location buys you. Now it asserts the thing it cares about.
    """
    tier1 = H._lifecycle_for_tier(1)
    tier2 = H._lifecycle_for_tier(2)
    assert set(tier1.keep_hot) == {"builder", "monitor"}
    assert {"oracle", "architect"} <= set(tier2.keep_hot), (
        "tier 2's lifecycle policy no longer keeps oracle and architect hot, so reaching tier 2 "
        "buys nothing"
    )
    assert set(tier1.keep_hot) < set(tier2.keep_hot), "tier 2 must keep strictly more resident"
    assert tier2.max_loaded >= tier1.max_loaded


# ── RAM ──────────────────────────────────────────────────────────────────────────────────────────


def test_total_ram_is_actually_readable_on_this_machine():
    """Reported 0.0 GB on a working box until 2026-07-30.

    The Windows path shelled out to `wmic ComputerSystem get TotalPhysicalMemory`. WMIC is deprecated
    and ABSENT from Windows 11 24H2+, so the call failed, a bare `except Exception: pass` swallowed it,
    and the profile carried `ram_gb=0.0` -- indistinguishable from a machine with no memory. It now
    uses kernel32's GlobalMemoryStatusEx, which needs no external binary.
    """
    ram_gb = H._detect_ram_gb()
    assert ram_gb > 0.5, (
        f"total RAM read as {ram_gb} GB. A real host has more than that, so the probe is failing "
        f"silently rather than measuring."
    )
    assert ram_gb < 4096, f"{ram_gb} GB is not a plausible reading; check the unit scaling"


def test_the_ram_probe_does_not_depend_on_wmic():
    """WMIC does not exist on current Windows. Depending on it is how this broke."""
    import ast
    import inspect

    # Only a LIVE reference counts. The function's own docstring names wmic to explain why it is
    # gone, and an occurrence check flagged that as the defect -- the same self-trip that has hit
    # several guards in this repo, so this parses instead of greps.
    tree = ast.parse(inspect.getsource(H._detect_ram_gb).lstrip())
    func = tree.body[0]
    # The docstring is the FIRST statement of the body. Identified by position, not by text --
    # ast.get_docstring() re-indents, so comparing strings does not match the raw literal.
    doc_node = None
    body = getattr(func, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        doc_node = body[0].value
    live = [
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node is not doc_node
        and "wmic" in node.value.lower()
    ]
    assert not live, (
        f"the RAM probe references wmic in live code: {live}. It is absent from Windows 11 24H2+ and "
        f"the failure is silent (ram_gb=0.0)."
    )


def test_a_ram_probe_failure_reports_zero_rather_than_crashing_the_profile():
    """0.0 is the honest 'could not read' value here, and callers treat it as unknown. The bug was
    never the zero -- it was that a REACHABLE probe was returning it."""
    import builtins

    real_open = builtins.open

    def boom(*_a, **_k):
        raise OSError("no /proc")

    try:
        builtins.open = boom  # type: ignore[assignment]
        # On Windows this path is not taken, so just assert the function is total.
        value = H._detect_ram_gb()
        assert isinstance(value, float) and value >= 0.0
    finally:
        builtins.open = real_open  # type: ignore[assignment]


# ── Intel Arc / XPU ──────────────────────────────────────────────────────────────────────────────


def test_intel_arc_is_detected_and_uses_its_own_torch_device(monkeypatch):
    """Intel is NOT a cuda alias the way ROCm is.

    A ROCm build of torch keeps the `cuda` device name, so AMD reports "cuda". Intel is a separate
    device: handing "cuda" to a caller on Arc would fail. That is why the device string is carried
    per-vendor in `_ACCELERATORS` rather than inferred from the vendor name.
    """
    xpu_csv = "Device ID,Device Name,Memory Physical Size\n0,Intel(R) Arc(TM) A770 Graphics,16384\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "nvidia-smi": (-1, ""),
                "amd-smi": (-1, ""),
                "rocm-smi": (-1, ""),
                "xpu-smi": (0, xpu_csv),
            }
        ),
    )
    vendor, torch_device, vram_gb, count = H.detect_accelerator()
    assert vendor == "intel", f"expected intel, got {vendor}"
    assert torch_device == "xpu", (
        "Intel must report the 'xpu' device; 'cuda' would be rejected by torch on Arc"
    )
    assert 15.0 < vram_gb < 17.0, f"16 GB Arc parsed as {vram_gb:.1f} GB (MiB scaling)"
    assert count == 1


def test_intel_is_probed_after_the_discrete_vendors_but_before_cpu_fallback(monkeypatch):
    """Ordering matters only in that a real accelerator must beat the CPU fallback. An Arc box with no
    NVIDIA/AMD tooling must not report CPU-only, which is the whole class of bug here."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "xpu-smi": (0, "Device ID,Memory Physical Size\n0,16384\n"),
            }
        ),
    )
    monkeypatch.setattr(H.ThermalProfile, "measure", staticmethod(lambda: H.ThermalProfile()))
    profile = H.profile_hardware()
    assert profile.accelerator == "intel"
    assert profile.tier == 1, f"16 GB should be mid-range (tier 1), got {profile.tier}"
    assert profile.tier > -1, "an Arc card must not be reported as CPU-only"
    assert "Intel" in profile.accelerator_label


def test_every_accelerator_entry_declares_a_device_torch_accepts():
    """A vendor added later with a made-up device string would fail at the call site, not here."""
    valid = {"cuda", "xpu", "mps"}
    for vendor, torch_device, probe in H._ACCELERATORS:
        assert torch_device in valid, (
            f"{vendor} declares torch device {torch_device!r}, which PyTorch does not accept "
            f"(expected one of {sorted(valid)})"
        )
        assert callable(probe), f"{vendor} has a non-callable probe"
