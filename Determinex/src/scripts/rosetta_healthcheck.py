#!/usr/bin/env python3
"""scripts/rosetta_healthcheck.py — Rosetta subsystem readiness check.

Walks every layer of the Determinex Rosetta stack and reports one of:
    ACTIVE
    UNAVAILABLE WITH REASON
    NOT IMPLEMENTED BY DESIGN

for each. Never silently downgrades. Output is both a human-readable table
and a JSON document at --json <path>.

Layers checked:
    Layer 1     DSL control plane                         (always ACTIVE if package imports)
    Layer 2A    Rosetta text-space approximation         (text_bridge importable + initializable)
    Layer 2B    Soft-prefix injection                    (llama-cpp-python + GGUF availability)
    Layer 2C    Latent memory / hidden-state RAG          (KVStore initializable)
    Layer 3     KV-cache broadcast                       (always NOT IMPLEMENTED BY DESIGN)

Plus stack invariants:
    - rosetta_v1.pt exists where expected
    - registered models' GGUF files resolve
    - registered model aliases all map to registered arch keys
    - RosettaStone.supported_arches (if available) covers our registry's arches
    - hidden_dim matches between registry and any loadable RosettaStone

Usage:
    python scripts/rosetta_healthcheck.py
    python scripts/rosetta_healthcheck.py --json logs/rosetta_healthcheck_latest.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Status object
# ---------------------------------------------------------------------------

ACTIVE = "ACTIVE"
UNAVAIL = "UNAVAILABLE WITH REASON"
DESIGN_ONLY = "NOT IMPLEMENTED BY DESIGN"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_dsl_control_plane() -> CheckResult:
    """Layer 1: the DSL control plane is the text-format protocol between agents.
    Considered ACTIVE if the package and a representative module import."""
    try:
        import rosetta  # noqa: F401

        # scripts/hive/* houses the DSL parser; touch it
        from scripts.hive import constants as _c  # noqa: F401

        return CheckResult(
            name="Layer 1 — DSL control plane",
            status=ACTIVE,
            detail="rosetta package + scripts/hive constants import",
        )
    except Exception as e:
        return CheckResult(
            name="Layer 1 — DSL control plane",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_layer2a_text_bridge() -> CheckResult:
    """Layer 2A: text-space approximation — scripts/rosetta_text_bridge.py.

    Considered ACTIVE if the module imports and reports a working init class.
    """
    try:
        # Module is at scripts/rosetta_text_bridge.py — import via its module path
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "rosetta_text_bridge_mod",
            str(REPO_ROOT / "scripts" / "rosetta_text_bridge.py"),
        )
        if spec is None or spec.loader is None:
            return CheckResult(
                name="Layer 2A — text-space bridge",
                status=UNAVAIL,
                detail="scripts/rosetta_text_bridge.py not loadable",
            )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Look for a Bridge-shaped attribute
        candidates = [n for n in dir(mod) if "Bridge" in n or "TextBridge" in n]
        if not candidates:
            return CheckResult(
                name="Layer 2A — text-space bridge",
                status=UNAVAIL,
                detail="text bridge module imported but no *Bridge class found",
            )
        return CheckResult(
            name="Layer 2A — text-space bridge",
            status=ACTIVE,
            detail=f"importable; bridge classes: {candidates}",
        )
    except Exception as e:
        return CheckResult(
            name="Layer 2A — text-space bridge",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_layer2b_softprefix() -> CheckResult:
    """Layer 2B: soft-prefix injection — needs llama-cpp-python with embedding=True
    and a target GGUF file accessible. We only verify the *requirements* here,
    not that real generation works (that's the softprefix smoke test).
    """
    extra = {}
    # llama-cpp-python
    try:
        import llama_cpp  # noqa: F401

        extra["llama_cpp"] = True
    except ImportError:
        return CheckResult(
            name="Layer 2B — soft-prefix injection",
            status=UNAVAIL,
            detail="llama-cpp-python not installed",
            extra={"llama_cpp": False},
        )
    # At least one model in the registry has a resolvable GGUF
    try:
        from rosetta.model_registry import current_family

        family = current_family()
        with_gguf = {role: m.name for role, m in family.items() if m.gguf_path}
        extra["models_with_gguf"] = with_gguf
        if not with_gguf:
            return CheckResult(
                name="Layer 2B — soft-prefix injection",
                status=UNAVAIL,
                detail="llama_cpp present but no registered model has a resolvable gguf_path on disk",
                extra=extra,
            )
        return CheckResult(
            name="Layer 2B — soft-prefix injection",
            status=ACTIVE,
            detail=f"llama_cpp installed; {len(with_gguf)} model(s) have a resolvable GGUF: {list(with_gguf.values())}",
            extra=extra,
        )
    except Exception as e:
        return CheckResult(
            name="Layer 2B — soft-prefix injection",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
            extra=extra,
        )


def check_layer2c_latent_memory() -> CheckResult:
    """Layer 2C: latent memory / hidden-state RAG."""
    try:
        # Use a transient db so we don't disturb anything
        import tempfile

        from rosetta.latent_memory import LatentMemory

        with tempfile.TemporaryDirectory() as td:
            lm = LatentMemory(db_path=Path(td) / "_healthcheck.db")
            try:
                st = lm.status()
                return CheckResult(
                    name="Layer 2C — latent memory",
                    status=st.get("status", UNAVAIL),
                    detail=st.get("note", ""),
                    extra={"entries": st.get("entries", 0)},
                )
            finally:
                lm.close()
    except Exception as e:
        return CheckResult(
            name="Layer 2C — latent memory",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_layer3_kv_broadcast() -> CheckResult:
    """Layer 3: KV-cache broadcast. Always reports NOT IMPLEMENTED BY DESIGN."""
    try:
        from rosetta.kv_broadcast import status

        st = status()
        return CheckResult(
            name="Layer 3 — KV-cache broadcast",
            status=st.get("status", DESIGN_ONLY),
            detail=st.get("reason", ""),
            extra={"interface": st.get("interface", []), "methods": st.get("methods", [])},
        )
    except Exception as e:
        return CheckResult(
            name="Layer 3 — KV-cache broadcast",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_rosetta_weights() -> CheckResult:
    """Verify rosetta_v1.pt exists where bridges expect it.

    Two common locations are checked: ~/.determinex/rosetta/rosetta_v1.pt and the
    repo's rosetta/ dir.
    """
    candidates = [
        Path.home() / ".determinex" / "rosetta" / "rosetta_v1.pt",
        REPO_ROOT / "rosetta" / "rosetta_v1.pt",
        REPO_ROOT / "outputs" / "rosetta" / "best" / "rosetta_v1.pt",
        REPO_ROOT / "outputs" / "rosetta" / "best.pt",
    ]
    found = [str(p) for p in candidates if p.exists()]
    if found:
        return CheckResult(
            name="rosetta_v1.pt weights",
            status=ACTIVE,
            detail=f"found at: {found[0]}",
            extra={"all_locations": found, "checked": [str(p) for p in candidates]},
        )
    return CheckResult(
        name="rosetta_v1.pt weights",
        status=UNAVAIL,
        detail="rosetta_v1.pt not found in any expected location",
        extra={"checked": [str(p) for p in candidates]},
    )


def check_model_arch_alignment() -> CheckResult:
    """Every registered model must map to a registered arch key with matching dim."""
    try:
        from rosetta.model_registry import (
            ARCHES,
            MODELS,
            get_arch,
            supported_arches,
        )

        problems: list[str] = []
        for name, m in MODELS.items():
            if m.rosetta_arch not in ARCHES:
                problems.append(f"{name}: rosetta_arch {m.rosetta_arch!r} not registered")
                continue
            arch = get_arch(m.rosetta_arch)
            if m.hidden_dim != arch.hidden_dim:
                problems.append(
                    f"{name}: hidden_dim={m.hidden_dim} != arch {m.rosetta_arch}.hidden_dim={arch.hidden_dim}"
                )
        if problems:
            return CheckResult(
                name="model ↔ arch alignment",
                status=UNAVAIL,
                detail="; ".join(problems),
                extra={"arches": supported_arches()},
            )
        return CheckResult(
            name="model ↔ arch alignment",
            status=ACTIVE,
            detail=f"all {len(MODELS)} models align with their registered arches",
            extra={"arches": supported_arches()},
        )
    except Exception as e:
        return CheckResult(
            name="model ↔ arch alignment",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_rosetta_stone_supported_arches() -> CheckResult:
    """If RosettaStone is importable, confirm its supported_arches covers our roles.

    Tolerates missing torch / missing weights — that's not this check's job,
    that's check_rosetta_weights + check_layer2b_softprefix.
    """
    try:
        from rosetta.model_registry import ARCHES, current_family

        # Don't import torch in this process unless needed
        try:
            from rosetta.train_rosetta import RosettaStone
        except ImportError as e:
            return CheckResult(
                name="RosettaStone.supported_arches",
                status=UNAVAIL,
                detail=f"train_rosetta import failed: {e}",
            )
        # Some builds expose a class attribute, some a classmethod. Try both.
        sup: set | None = None
        if hasattr(RosettaStone, "supported_arches"):
            sa = RosettaStone.supported_arches
            try:
                sup = set(sa() if callable(sa) else sa)
            except TypeError:
                sup = None
        if sup is None and hasattr(RosettaStone, "FAMILY_DIMS"):
            sup = set(RosettaStone.FAMILY_DIMS.keys())
        # If we still can't tell, report unknown
        if sup is None:
            return CheckResult(
                name="RosettaStone.supported_arches",
                status=UNAVAIL,
                detail="RosettaStone exposes neither supported_arches() nor FAMILY_DIMS",
            )
        # Compare to our registered C1/C3/C7 family
        family_arches = {m.rosetta_arch for m in current_family().values()}
        # Match also by upstream family label (qwen2 covers qwen2_1b5 etc.)
        missing = []
        for arch in family_arches:
            arch_spec = ARCHES.get(arch)
            family = arch_spec.family if arch_spec is not None else arch.split("_", 1)[0]
            legacy_family = {"qwen2": "qwen", "mistral": "mistral", "llama3": "llama"}.get(
                family, family
            )
            if arch not in sup and family not in sup and legacy_family not in sup:
                missing.append(arch)
        if missing:
            return CheckResult(
                name="RosettaStone.supported_arches",
                status=UNAVAIL,
                detail=f"current family uses arches not in RosettaStone: {missing}",
                extra={"stone_arches": sorted(sup), "family_arches": sorted(family_arches)},
            )
        return CheckResult(
            name="RosettaStone.supported_arches",
            status=ACTIVE,
            detail="RosettaStone covers all current-family arches",
            extra={"stone_arches": sorted(sup), "family_arches": sorted(family_arches)},
        )
    except Exception as e:
        return CheckResult(
            name="RosettaStone.supported_arches",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


def check_dimension_routing_self() -> CheckResult:
    """Verify the dimension validator catches the historical failure mode:
    qwen2_7b expects 3584, hand it a 1536-dim tensor, RosettaDimensionMismatch fires."""
    try:
        from rosetta.model_registry import (
            RosettaDimensionMismatch,
            require_model,
            validate_hidden_dim,
        )

        class _Shape:
            def __init__(self, *shape):
                self.shape = shape

        arch = require_model("architect")  # qwen2_7b, dim=3584
        try:
            validate_hidden_dim(arch, _Shape(1, 1536), target_model="engineer")
        except RosettaDimensionMismatch as e:
            return CheckResult(
                name="dimension routing (1536→qwen2_7b must fail)",
                status=ACTIVE,
                detail="RosettaDimensionMismatch fired correctly on size collision",
                extra=e.to_dict(),
            )
        return CheckResult(
            name="dimension routing (1536→qwen2_7b must fail)",
            status=UNAVAIL,
            detail="dimension validator did NOT raise — it should have",
        )
    except Exception as e:
        return CheckResult(
            name="dimension routing self-test",
            status=UNAVAIL,
            detail=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_dsl_control_plane,
    check_layer2a_text_bridge,
    check_layer2b_softprefix,
    check_layer2c_latent_memory,
    check_layer3_kv_broadcast,
    check_rosetta_weights,
    check_model_arch_alignment,
    check_rosetta_stone_supported_arches,
    check_dimension_routing_self,
]


def run_all() -> list[CheckResult]:
    out = []
    for fn in ALL_CHECKS:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            r = CheckResult(name=fn.__name__, status=UNAVAIL, detail=f"check crashed: {e}")
        # Attach elapsed for debugging
        r.extra.setdefault("elapsed_ms", int(1000 * (time.time() - t0)))
        out.append(r)
    return out


def render_table(results: list[CheckResult]) -> str:
    name_w = max(len(r.name) for r in results)
    status_w = max(len(ACTIVE), len(UNAVAIL), len(DESIGN_ONLY))
    lines = []
    lines.append(f"{'CHECK'.ljust(name_w)}  {'STATUS'.ljust(status_w)}  DETAIL")
    lines.append(f"{'-' * name_w}  {'-' * status_w}  {'-' * 60}")
    for r in results:
        marker = "✓" if r.status == ACTIVE else ("∅" if r.status == DESIGN_ONLY else "✗")
        detail = (r.detail or "")[:120]
        lines.append(f"{r.name.ljust(name_w)}  {r.status.ljust(status_w)}  {marker} {detail}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex Rosetta subsystem healthcheck")
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        help="write JSON report to this path (e.g. logs/rosetta_healthcheck_latest.json)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero if any layer is UNAVAILABLE (default: only crash exits nonzero)",
    )
    args = ap.parse_args()

    results = run_all()

    print(render_table(results))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": time.time(),
            "checks": [r.to_dict() for r in results],
            "summary": {
                "active": sum(1 for r in results if r.status == ACTIVE),
                "unavailable": sum(1 for r in results if r.status == UNAVAIL),
                "design_only": sum(1 for r in results if r.status == DESIGN_ONLY),
                "total": len(results),
            },
        }
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print()
        print(f"wrote {args.json}")

    if args.strict:
        unavail = sum(1 for r in results if r.status == UNAVAIL)
        return 0 if unavail == 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
