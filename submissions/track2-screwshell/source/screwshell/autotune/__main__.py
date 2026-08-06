"""One-shot autotune CLI: detect -> scan -> plan -> doctor -> tuner -> report.

This is the `python -m screwshell.autotune` entry point. It produces a
human-readable deployment report (and optional JSON) so a non-technical user
knows which tier their GPU can run and which expert lineup to load.

Usage
-----
  python -m screwshell.autotune \
      --packs-dir screwshell/autotune/skillpacks \
      --model /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
      --loras-dir /persistent/loras \
      --deploy-base Qwen/Qwen3.6-27B --port 8080

Run it on the deploy host (where rocm-smi lives). Exit code is non-zero if the
preflight (doctor) found a blocking error.
"""
from __future__ import annotations

import argparse
import json
import sys

from screwshell.autotune import detect, scan_skillpacks, plan
from screwshell.autotune.doctor import preflight
from screwshell.autotune.tuner import resolve
from screwshell.autotune.hardware import QUANT_VRAM_GB
from screwshell.autotune.governor import select_mode


def _profile_dict(profile) -> dict:
    return {
        "vendor": profile.vendor, "name": profile.name,
        "vram_total_gb": profile.vram_total_gb,
        "vram_usable_gb": profile.vram_usable_gb,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packs-dir",
                    default="screwshell/autotune/skillpacks",
                    help="directory scanned for SkillPack folders")
    ap.add_argument("--model", default="",
                    help="path to base GGUF (omit to skip file checks)")
    ap.add_argument("--loras-dir", default="",
                    help="dir holding <pack>/adapter.gguf (omit to use pack folders)")
    ap.add_argument("--deploy-base", default="Qwen/Qwen3.6-27B",
                    help="deployed base fingerprint; mismatched packs are dropped")
    ap.add_argument("--port", type=int, default=8080,
                    help="target llama-server port (preflight checks it)")
    ap.add_argument("--l3-mode", choices=["auto", "roomy", "tight"], default=None,
                    help="assert/echo the runtime scheduling mode the deployment "
                         "implies. Predicted from VRAM vs roster load when omitted.")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of the text report")
    args = ap.parse_args()

    profile = detect()
    packs = scan_skillpacks(args.packs_dir)
    pres = plan(profile, packs, target_base=args.deploy_base)
    doc = preflight(args.model, args.loras_dir, pres.selected, packs,
                   args.deploy_base, args.port, profile)
    spec = resolve(pres, profile)

    # Predict the runtime scheduling mode from VRAM vs roster load.
    base_est = QUANT_VRAM_GB.get(pres.quant, 16.0)
    roster_load = base_est + sum(packs[n].vram_gb for n in pres.selected if n in packs)
    predicted_mode = select_mode(profile.vram_usable_gb, roster_load)
    if args.l3_mode and args.l3_mode not in ("auto", predicted_mode):
        print(f"[note] --l3-mode={args.l3_mode} overrides predicted "
              f"'{predicted_mode}' for this host (VRAM {profile.vram_usable_gb:.1f}G "
              f"vs roster {roster_load:.1f}G).")

    if args.json:
        out = {
            "profile": _profile_dict(profile),
            "plan": {
                "base_model": pres.base_model, "quant": pres.quant,
                "selected": pres.selected,
                "covered_skills": pres.covered_skills,
                "degrade_level": pres.degrade_level, "scores": pres.scores,
            },
            "preflight_ok": doc.ok,
            "preflight_items": [{"level": i.level, "msg": i.msg}
                                for i in doc.items],
            "spec": {
                "base_model": spec.base_model, "quant": spec.quant,
                "lora_pack_names": spec.lora_pack_names,
                "ctx_tokens": spec.ctx_tokens,
                "degrade_level": spec.degrade_level, "notes": spec.notes,
            },
            "runtime_mode": {
                "predicted": predicted_mode,
                "asserted": args.l3_mode,
                "vram_usable_gb": profile.vram_usable_gb,
                "roster_load_gb": round(roster_load, 1),
            },
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0 if doc.ok else 1)

    print(pres.report)
    print()
    print(doc.report())
    print()
    print(spec.report())
    print()
    print(f"Runtime scheduling (L3): predicted '{predicted_mode}' "
          f"(VRAM {profile.vram_usable_gb:.1f}G vs roster {roster_load:.1f}G)")
    if args.l3_mode:
        print(f"  asserted override: {args.l3_mode}")
    sys.exit(0 if doc.ok else 1)


if __name__ == "__main__":
    main()
