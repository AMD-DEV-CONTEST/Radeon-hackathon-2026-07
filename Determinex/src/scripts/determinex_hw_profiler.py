#!/usr/bin/env python3
"""
determinex_hw_profiler.py -- Pre-Flight Static Graph Profiler (Stage 2/3 engine)
=================================================================================
Surfaces a compute heatmap + hardware-boundary/memory-layout risk map for a
hand-ported, hardware-target kernel BEFORE optimization work starts, instead of
reconstructing the same facts by hand after 10 failed real-hardware attempts.

Origin: the hf-hackathon ET-SoC1 YOLO campaign lost to a competitor after
burning an entire session chasing a tensor-unit accuracy bug whose root cause
(tensor_load silently masking non-16-aligned per-tap addresses) was a single,
codifiable hardware fact. This module is that codification, generalized beyond
the one kernel it was first validated against.

Design (matches the corpus proposal, PREFLIGHT_STATIC_GRAPH_PROFILER_PROPOSAL_
2026_07_13): three stages, but only Stage 2 (hardware boundary intersection)
and Stage 3 (memory layout audit) are implemented here from real C/C++ kernel
source -- Stage 1's ideal form (ingest the original ONNX graph for a true
compute heatmap) is NOT built; the heatmap here is a call-site-level MAC count
computed directly from the ported C, which is a real but coarser proxy.

Two things are DATA, not code, so a new hardware target or kernel dialect
never requires touching this file:
  - "dialect" (scripts/hw_rules/<dialect>_calls.json, optional) -- the regex
    patterns describing how THIS kernel's conv-like macros/calls look in
    source, and how to turn their captured args into IC/OC/H/W/taps/etc.
  - "rule table" (scripts/hw_rules/<target>.json) -- the hardware constraint
    facts to check against extracted call sites (scripts/hw_rules/et_soc1.json
    ships the 5 facts this campaign paid for in real debugging hours).

A rule's arithmetic is still a Python function (the _CHECKS registry below) --
deliberately NOT an eval()'d expression string, so a rule table can never
smuggle in code execution. Only the rule's existence/metadata/severity is data.

CLI
---
    python scripts/determinex_hw_profiler.py <kernel_source.c> [--dialect et_soc1_yolo] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RULES_DIR = _HERE / "hw_rules"


# ---------------------------------------------------------------------------
# Dialects: how to recognize and parse this kernel's conv-like call sites.
# Bundled in-code (not JSON) because a dialect's regex/field-mapping IS logic,
# not a fact -- but it is one isolated, swappable block, not woven through the
# rest of the module. A new target adds one entry here.
# ---------------------------------------------------------------------------
_DIALECTS: dict[str, list[dict]] = {
    "et_soc1_yolo": [
        {
            "label": "CONV_1x1",
            "regex": r"CONV_1x1\([^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("IC", "H", "W", "OC", "act"),
            "taps": 1,
            "is_dw": False,
        },
        {
            "label": "CONV_3x3_P1_VPU",
            "regex": r"CONV_3x3_P1_VPU\([^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("IC", "H", "W", "OC", "act"),
            "taps": 9,
            "is_dw": False,
        },
        {
            "label": "CONV_3x3_S2_P1_VPU",
            "regex": r"CONV_3x3_S2_P1_VPU\([^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("IC", "H", "W", "OC", "OH", "OW", "act"),
            "taps": 9,
            "is_dw": False,
        },
        {
            "label": "CONV_DW3x3_S1_P1_VPU",
            "regex": r"CONV_DW3x3_S1_P1_VPU\([^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("C", "H", "W", "act"),
            "taps": 9,
            "is_dw": True,
        },
        {
            "label": "bare_conv2d_3x3_p1_vpu",
            "regex": r"conv2d_3x3_p1_fp32_mh_vpu\(hid,[^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("IC", "H", "W", "OC", "act"),
            "taps": 9,
            "is_dw": False,
        },
        {
            "label": "bare_conv2d_3x3_p1_tensor",
            "regex": r"conv2d_3x3_p1_fp32_mh_tensor\(hid,\s*base,[^;]*?,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\)",
            "fields": ("IC", "H", "W", "OC", "act"),
            "taps": 9,
            "is_dw": False,
        },
    ],
}

# Cheap file-level signature -> dialect name, for auto-detection from ingest.
# First match wins; a repo with no signature match gets no hardware profile.
_DIALECT_SIGNATURES: list[tuple[str, re.Pattern]] = [
    ("et_soc1_yolo", re.compile(r"\bCONV_3x3_P1_VPU\(|\bconv2d_3x3_p1_fp32_mh_tensor\(")),
]

# See detect_dialect_sources's comment: a hand-ported hardware kernel is
# realistically a handful to a few dozen files. Found live 2026-07-22 that
# a large polyglot repo can have thousands of REAL, gitignore-respecting
# tracked .c files (vendored/reference upstream archives, not anything
# hand-ported) -- past this count, reading+regex-scanning every one of them
# is real, unavoidable work for an input this profiler was never meant to
# run against, so skip rather than pay for it.
_MAX_DIALECT_SCAN_FILES = 200


def detect_dialect(root: Path) -> str | None:
    """Cheap heuristic: does this repo look like a known hardware-kernel dialect?"""
    found = detect_dialect_sources(root)
    return found[0] if found else None


def detect_dialect_sources(root: Path) -> tuple[str, list[Path]] | None:
    """Like detect_dialect, but also returns every source file matching that
    dialect's signature, so a caller can profile the whole kernel, not just
    the first file found."""
    # Deferred import (not module-level): determinex_ingest imports THIS
    # module (detect_dialect_sources/profile_repo, for its C/C++ hardware
    # profile step), so importing it back at module level here would be a
    # circular import. Reusing its _walk_files gets the same fix this
    # exact bug already got there for free: a raw, unfiltered
    # `root.rglob("*.c")` walked (and read_text'd -- full file CONTENTS,
    # not just a stat) every .c file anywhere under root, including this
    # repo's own .venv/scratch/corpus/node_modules/etc -- found live
    # 2026-07-22 as the SAME ingest() call's real remaining hang after the
    # walk-and-crash bugs in determinex_ingest.py itself were fixed:
    # census/build/harness detection went from 90+s to ~3s, but this
    # function (triggered whenever the census's top language is c/cpp) was
    # still walking the whole tree raw and hadn't been touched.
    from determinex_ingest import _walk_files

    c_files = [p for p in _walk_files(root) if p.suffix.lower() == ".c"]
    # A hand-ported hardware kernel (this profiler's actual target) is
    # realistically a handful to a few dozen files -- thousands of tracked
    # .c files means the repo is something else entirely (found live
    # 2026-07-22: 8,757 .c files / ~245MB, almost all vendored/reference
    # upstream C archives from this project's own ProgramBench corpus, not
    # anything hand-ported). Reading and regex-scanning the full text of
    # every one of those is real, unavoidable work for genuinely wrong
    # inputs -- skip the scan entirely rather than pay for it on a repo
    # this profiler was never meant to run against.
    if len(c_files) > _MAX_DIALECT_SCAN_FILES:
        return None
    matched: dict[str, list[Path]] = {}
    for p in c_files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for name, sig in _DIALECT_SIGNATURES:
            if sig.search(text):
                matched.setdefault(name, []).append(p)
    if not matched:
        return None
    # First-registered dialect with a match wins, for determinism.
    for name in _DIALECTS:
        if name in matched:
            return name, matched[name]
    return None


@dataclass
class CallSite:
    label: str
    macs: int
    IC: int
    OC: int
    H: int
    W: int
    OH: int
    OW: int
    taps: int
    is_dw: bool
    tensor_eligible: bool
    boundary_reason: str
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class HardwareProfile:
    hardware_target: str
    dialect: str
    total_macs: int
    n_call_sites: int
    n_tensor_eligible: int
    n_critical: int
    heatmap_top10: list[dict]
    critical_findings: list[str]
    warnings: list[str]
    checklist: list[str]


def extract_call_sites(text: str, dialect: str, t_tile: int) -> list[CallSite]:
    sites: list[CallSite] = []
    for spec in _DIALECTS[dialect]:
        rx = re.compile(spec["regex"])
        fields = spec["fields"]
        taps = spec["taps"]
        is_dw = spec["is_dw"]
        for m in rx.finditer(text):
            vals = {f: int(v) for f, v in zip(fields, m.groups())}
            ic_val = vals.get("IC", vals.get("C"))
            assert ic_val is not None, f"dialect spec '{spec['label']}' fields must include IC or C"
            IC: int = ic_val
            OC: int = vals.get("OC", IC)
            H = vals["H"]
            W = vals["W"]
            OH = vals.get("OH", H)
            OW = vals.get("OW", W)

            if is_dw:
                macs = IC * OH * OW * taps
            elif taps == 1:
                macs = IC * OC * OH * OW
            else:
                macs = IC * OC * OH * OW * taps

            if is_dw:
                tensor_eligible = False
                reason = "depthwise -- not a tensor-unit target on this hardware by design"
            else:
                ic_ok = IC % t_tile == 0
                oc_ok = OC % t_tile == 0
                hw_ok = (OH * OW) % t_tile == 0
                tensor_eligible = ic_ok and oc_ok and hw_ok
                reason = f"IC%{t_tile}={IC % t_tile} OC%{t_tile}={OC % t_tile} (OH*OW)%{t_tile}={(OH * OW) % t_tile}"

            sites.append(
                CallSite(
                    label=spec["label"],
                    macs=macs,
                    IC=IC,
                    OC=OC,
                    H=H,
                    W=W,
                    OH=OH,
                    OW=OW,
                    taps=taps,
                    is_dw=is_dw,
                    tensor_eligible=tensor_eligible,
                    boundary_reason=reason,
                )
            )
    sites.sort(key=lambda s: -s.macs)
    return sites


# ---------------------------------------------------------------------------
# Rule checks. Keyed by check_id, referenced from the JSON rule table. Each
# per-call_site check returns a finding string if it fires, else None. Each
# per-file check takes the raw text and returns a list of finding strings.
# ---------------------------------------------------------------------------
def _check_padded_row_alignment_multi_tap(site: CallSite, consts: dict) -> str | None:
    if not (site.tensor_eligible and site.taps > 1):
        return None
    t_tile = consts["T_TILE"]
    pad = 1
    pw = site.W + 2 * pad
    if pw % t_tile != 0:
        k = int(round(site.taps**0.5))
        return (
            f"padded row width PW={pw} (W={site.W}, pad={pad}) is NOT a multiple of "
            f"{t_tile} -- K={k} tap offsets kx>0 will silently misalign against the "
            f"hardware's {consts['TENSOR_LOAD_MASK_BYTES']}-byte addr/stride masking"
        )
    return None


def _check_store_output_tile_alignment(site: CallSite, consts: dict) -> str | None:
    if not site.tensor_eligible:
        return None
    t_tile = consts["T_TILE"]
    if site.OC % t_tile != 0 or (site.OH * site.OW) % t_tile != 0:
        return (
            f"output tile OC={site.OC} OH*OW={site.OH * site.OW} not provably a multiple "
            f"of {t_tile} -- tensor_store's own {consts['TENSOR_STORE_MASK_BYTES']}-byte "
            f"addr/stride mask (mask=~(16*{consts['TENSOR_STORE_MASK_COLS']}-1)) may silently "
            f"misalign the output write"
        )
    return None


def _check_scp_fregs_tile_capacity_ceiling(site: CallSite, consts: dict) -> str | None:
    if not site.tensor_eligible:
        return None
    # This kernel always tiles to exactly T_TILE; only fires if a call site
    # implies a tile dimension larger than the hardware's fixed, zero-slack sizing.
    if site.OC > consts["TFMA_MAX_AROWS"] and site.OC % consts["TFMA_MAX_AROWS"] != 0:
        return (
            f"OC={site.OC} is not a clean multiple of TFMA_MAX_AROWS={consts['TFMA_MAX_AROWS']} "
            f"-- a naive single-pass tile would overflow FREGS=NFREGS({consts['NFREGS']}), which "
            f"is an EXACT fit (arows x TFMA_REGS_PER_ROW) with zero slack"
        )
    return None


def _check_tenb_bank_offset_disjointness(text: str, consts: dict) -> list[str]:
    raw_sites = list(re.finditer(r"\btensor_load\s*\(", text))
    if not raw_sites:
        return []
    return [
        (
            f"{len(raw_sites)} raw tensor_load(...) call site(s) found outside macro wrappers -- "
            f"manually verify use_tenb is set consistently with the logical operand (weight=main "
            f"bank, activation=tenb bank at +{consts['SCP_TENB_OFFSET']} offset) for each; this "
            "cannot be verified automatically from the call site alone"
        )
    ]


def _check_file_load_sync_checklist(text: str, _consts: dict) -> list[str]:
    raw_sites = list(re.finditer(r"\bfile_load\s*\(", text))
    if not raw_sites:
        return []
    return [
        (
            f"{len(raw_sites)} file_load(...) call site(s) found -- confirm the launcher "
            "synchronizes (waits for completion of) every file_load before the corresponding "
            "kernelLaunch; this ordering guarantee lives in host/launcher code and is not "
            "statically checkable from kernel source alone"
        )
    ]


_CALL_SITE_CHECKS = {
    "padded_row_alignment_multi_tap": _check_padded_row_alignment_multi_tap,
    "store_output_tile_alignment": _check_store_output_tile_alignment,
    "scp_fregs_tile_capacity_ceiling": _check_scp_fregs_tile_capacity_ceiling,
}
_FILE_CHECKS = {
    "tenb_bank_offset_disjointness": _check_tenb_bank_offset_disjointness,
    "file_load_sync_checklist": _check_file_load_sync_checklist,
}


def load_rule_table(hardware_target: str) -> dict:
    path = _RULES_DIR / f"{hardware_target}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_rules(
    sites: list[CallSite], text: str, rule_table: dict
) -> tuple[list[str], list[str], list[str]]:
    consts = rule_table["constants"]
    critical: list[str] = []
    warnings: list[str] = []
    checklist: list[str] = []

    for rule in rule_table["rules"]:
        check_id = rule["check_id"]
        severity = rule["severity"]
        if rule["applies_to"] == "call_site":
            fn = _CALL_SITE_CHECKS.get(check_id)
            if fn is None:
                continue
            for site in sites:
                finding = fn(site, consts)
                if finding:
                    site.risk_flags.append(f"[{severity}] {rule['title']}: {finding}")
                    line = (
                        f"{site.label} IC={site.IC} OC={site.OC} H={site.H} W={site.W} -> {finding}"
                    )
                    if severity == "critical":
                        critical.append(line)
                    elif severity == "warning":
                        warnings.append(line)
                    else:
                        checklist.append(line)
        elif rule["applies_to"] == "file":
            fn = _FILE_CHECKS.get(check_id)
            if fn is None:
                continue
            for finding in fn(text, consts):
                line = f"{rule['title']}: {finding}"
                if severity == "critical":
                    critical.append(line)
                elif severity == "warning":
                    warnings.append(line)
                else:
                    checklist.append(line)

    return critical, warnings, checklist


def profile(source_path: Path, dialect: str, hardware_target: str = "et_soc1") -> HardwareProfile:
    text = source_path.read_text(encoding="utf-8", errors="replace")
    return _profile_text(text, dialect, hardware_target)


def profile_repo(
    dialect: str, sources: list[Path], hardware_target: str = "et_soc1"
) -> HardwareProfile:
    """Profile every source file matching a detected dialect and aggregate
    the results into one report -- what determinex_ingest wires up, since a
    kernel's conv-like call sites are rarely confined to a single file."""
    combined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sources)
    return _profile_text(combined, dialect, hardware_target)


def _profile_text(text: str, dialect: str, hardware_target: str) -> HardwareProfile:
    rule_table = load_rule_table(hardware_target)
    t_tile = rule_table["constants"]["T_TILE"]

    sites = extract_call_sites(text, dialect, t_tile)
    critical, warnings, checklist = evaluate_rules(sites, text, rule_table)

    total_macs = sum(s.macs for s in sites)
    heatmap_top10 = [
        {
            "label": s.label,
            "IC": s.IC,
            "OC": s.OC,
            "H": s.H,
            "W": s.W,
            "OH": s.OH,
            "OW": s.OW,
            "taps": s.taps,
            "macs": s.macs,
            "pct": round(100.0 * s.macs / total_macs, 2) if total_macs else 0.0,
        }
        for s in sites[:10]
    ]

    return HardwareProfile(
        hardware_target=hardware_target,
        dialect=dialect,
        total_macs=total_macs,
        n_call_sites=len(sites),
        n_tensor_eligible=sum(1 for s in sites if s.tensor_eligible),
        n_critical=len(critical),
        heatmap_top10=heatmap_top10,
        critical_findings=critical,
        warnings=warnings,
        checklist=checklist,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-Flight Static Graph Profiler")
    ap.add_argument("source", type=Path)
    ap.add_argument("--dialect", default="et_soc1_yolo")
    ap.add_argument("--hardware-target", default="et_soc1")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    hp = profile(args.source, args.dialect, args.hardware_target)
    if args.json:
        print(json.dumps(asdict(hp), indent=2))
        return 0

    print(
        f"=== Pre-Flight Static Graph Profiler: {args.source} ({hp.dialect} / {hp.hardware_target}) ==="
    )
    print(
        f"  {hp.n_call_sites} call sites, {hp.n_tensor_eligible} tensor-eligible, "
        f"total MACs={hp.total_macs:,}\n"
    )
    print("--- Stage 1 (proxy): compute heatmap, top 10 ---")
    for row in hp.heatmap_top10:
        print(
            f"  {row['label']:28s} IC={row['IC']:<4} OC={row['OC']:<4} H={row['H']:<4} "
            f"W={row['W']:<4} taps={row['taps']:<2} MACs={row['macs']:>12,} ({row['pct']:5.1f}%)"
        )
    print(f"\n--- Stage 2/3: hardware boundary + memory-layout risk ({hp.n_critical} CRITICAL) ---")
    for line in hp.critical_findings:
        print(f"  [CRITICAL] {line}")
    for line in hp.warnings:
        print(f"  [warning]  {line}")
    for line in hp.checklist:
        print(f"  [checklist] {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
