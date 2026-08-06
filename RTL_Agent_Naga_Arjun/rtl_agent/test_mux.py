import asyncio
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agent import run_agent

async def main():
    spec = "A parameterized 2-to-1 multiplexer with DATA_WIDTH defaulting to 8. Inputs are a and b; sel=0 selects a, sel=1 selects b. Output is y. Fully combinational, no clock or reset needed."
    print("Running 2-to-1 Mux through agent pipeline...")
    last_ev = None
    async for ev in run_agent(spec, "mux_test_run"):
        ev_type = ev.get("type")
        if ev_type in ("thought", "final_result", "sim_iteration", "dut_lint_result"):
            print(f"[{ev_type}] {ev.get('message', '')}")
            if ev_type == "sim_iteration":
                print(f"  Passed: {ev.get('passed')}, Phase: {ev.get('phase')}")
                if ev.get("error_summary"):
                    print(f"  Summary: {ev.get('error_summary')}")
        last_ev = ev

    print("\n" + "="*50)
    print(f"Lint Pass: {last_ev.get('lint_status') == 'PASSED'}")
    print(f"Sim Pass : {last_ev.get('functional_status') == 'PASSED'}")
    print(f"Result   : {last_ev.get('message')}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
