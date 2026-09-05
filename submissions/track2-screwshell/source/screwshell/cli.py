"""ScrewShell CLI — fallback interface (same engine as the UI).

Usage (remote):
  source /opt/venv/bin/activate
  python -m screwshell.cli --workspace /persistent/screwshell/demo_workspace
"""
from __future__ import annotations

import argparse

from screwshell.app import build_app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--base", default="/models/unsloth/Qwen3.5-9B")
    ap.add_argument("--lora-dir", default="/persistent/loras")
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("-q", "--query", help="one-shot query (otherwise REPL)")
    # --- L3 runtime governance switch ---
    ap.add_argument("--l3-mode", choices=["auto", "roomy", "tight"],
                    default="auto",
                    help="runtime LoRA scheduling: auto (tight iff --launch-cmd "
                         "given) / roomy (hot-swap, no restart) / tight "
                         "(restart-swap experts).")
    ap.add_argument("--launch-cmd", default=None,
                    help="llama-server launch template with {lora} (and optional "
                         "{ctx}/{kv}) placeholders; REQUIRED for --l3-mode tight.")
    ap.add_argument("--takeover", action="store_true",
                    help="allow the orchestrator to kill a pre-existing listener "
                         "on the target port (tight mode only).")
    args = ap.parse_args()

    if args.l3_mode == "tight" and not args.launch_cmd:
        ap.error("--l3-mode tight requires --launch-cmd")

    ctx = build_app(workspace=args.workspace, base=args.base,
                    lora_dir=args.lora_dir, build_rag=not args.no_rag,
                    l3_mode=args.l3_mode, launch_cmd=args.launch_cmd,
                    takeover=args.takeover)

    def on_event(kind, data):
        if kind == "lora_switch" and data.get("from") != data.get("to"):
            print(f"  [MoL] {data.get('from') or 'base'} -> "
                  f"{data.get('to') or 'base'} ({data['ms']:.1f} ms, "
                  f"{data.get('mode', '?')})")
        elif kind == "lora_swap_restart":
            print(f"  [MoL restart-swap] -> {data.get('to')} "
                  f"(reload {data.get('to_serve_s')}s, tight mode)")
        elif kind == "governor_thinking":
            print(f"  [governor] thinking -> {data.get('thinking')} "
                  f"({data.get('reason', '')})")
        elif kind == "governor_ctx":
            print(f"  [governor] ctx -> {data.get('ctx')} "
                  f"({data.get('reason', '')})")
        elif kind == "governor_kv":
            print(f"  [governor] kv_quant -> {data.get('kv_quant')}")
        elif kind == "governor_alert":
            print(f"  [governor ALERT] {data.get('reason', '')}")
        elif kind == "plan":
            print(f"  [plan]\n{data['task']}")
        elif kind == "tool":
            print(f"  [tool] {data['tool']} ok={data['ok']}: {data['digest'][:120]}")
        elif kind == "step_done":
            print(f"  [step done] {data['finding'][:150]}")

    ctx.orchestrator.on_event = on_event

    def _fmt(value, unit: str = "", nd: int = 1) -> str:
        """`n/a` for an unmeasured value -- never a plausible-looking zero."""
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:.{nd}f}{unit}"
        return f"{value}{unit}"

    def ask(q: str):
        r = ctx.orchestrator.run(q)
        print("\n=== ANSWER ===\n" + r.answer)
        print(f"\n[stats] {r.stats['seconds']}s, l3_mode={r.stats['l3_mode']}, "
              f"vram={r.stats['engine']['vram_gb'] or 'n/a'}GB, "
              f"switches={r.stats['engine']['switches']}, "
              f"last_switch={r.stats['engine']['last_switch_ms']}ms")
        llm = r.stats.get("llm") or {}
        if llm.get("calls"):
            phases = r.stats.get("phases") or {}
            coverage = (llm.get("coverage") or {}).get("timings", 0.0)
            # coverage < 1.0 means the server did not report `timings` for
            # every call, so prefill/decode below are partial. Say so instead
            # of printing a confident number built from missing data.
            warn = "" if coverage >= 1.0 else f"  (timings coverage {coverage:.0%})"
            print(f"[llm]   calls={llm['calls']} "
                  f"prompt={llm['prompt_tokens']}tok "
                  f"new={llm['new_tokens']}tok | "
                  f"prefill={_fmt(llm.get('prefill_s'), 's', 2)}"
                  f"@{_fmt(llm.get('prefill_tps'), ' tok/s')} "
                  f"decode={_fmt(llm.get('decode_s'), 's', 2)}"
                  f"@{_fmt(llm.get('decode_tps'), ' tok/s')} "
                  f"kv_hit={llm.get('kv_hit_rate', 0.0):.1%}{warn}")
            print(f"[phase] plan={phases.get('plan_s', 0.0)}s "
                  f"steps={phases.get('steps_s', 0.0)}s "
                  f"final={phases.get('final_s', 0.0)}s")

    try:
        if args.query:
            ask(args.query)
            return
        print("ScrewShell REPL — type 'exit' to quit")
        while True:
            try:
                q = input("\nscrewshell> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("exit", "quit", ""):
                if q:
                    break
                continue
            ask(q)
    finally:
        ctx.orchestrator.shutdown()


if __name__ == "__main__":
    main()
