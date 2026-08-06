"""
test_sim_logging.py — Verify simulation log and waveform persistence & API retrieval.
"""
import asyncio
import json
import os
from pathlib import Path
from agent import run_agent
from config import LOGS_DIR
from tools.simulator_tool import run_simulation
from fastapi.testclient import TestClient
from agent_server import app

def test_simulator_logging_direct():
    session_id = "test_sess_001"
    os.makedirs("workspace", exist_ok=True)
    dut_file = "workspace/test_dut.sv"
    Path(dut_file).write_text("module counter(input clk, input rst, output reg [3:0] count); endmodule", encoding="utf-8")
    tb_code = "module tb_counter; initial begin $display(\"TB START\"); end endmodule"
    workdir = f"workspace/{session_id}_sim"

    res = run_simulation(
        dut_path=dut_file,
        tb_code=tb_code,
        workdir=workdir,
        session_id=session_id,
        iteration=1
    )

    print("[DIRECT SIM] SimResult passed:", res.passed)
    print("[DIRECT SIM] Log path:", res.log_file_path)
    print("[DIRECT SIM] VCD path:", res.vcd_file_path)
    print("[DIRECT SIM] Error summary:", res.error_summary)

    session_log_dir = LOGS_DIR / session_id
    assert session_log_dir.exists(), f"Log dir {session_log_dir} does not exist"
    
    history_file = session_log_dir / "simulation_history.json"
    assert history_file.exists(), f"History file {history_file} does not exist"
    
    history = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(history) >= 1, "History has no recorded iterations"
    print(f"[PASS] Direct simulator logging verified: {len(history)} record(s) in JSON history.")

async def test_agent_event_flow():
    spec = "Design an 8-bit synchronous counter with reset"
    session_id = "test_agent_flow_002"
    
    events = []
    log_saved_events = []
    waveform_events = []
    
    async for ev in run_agent(spec, session_id=session_id):
        events.append(ev)
        if ev["type"] in ("sim_iteration", "sim_build_error"):
            if ev.get("log_file_path"):
                log_saved_events.append(ev)
        elif ev["type"] == "waveform_ready":
            waveform_events.append(ev)

    print(f"[AGENT FLOW] Total events: {len(events)}")
    print(f"[AGENT FLOW] Sim events with log paths: {len(log_saved_events)}")
    print(f"[AGENT FLOW] Waveform ready events: {len(waveform_events)}")
    
    assert len(log_saved_events) > 0, "No simulation events emitted log paths!"
    print("[PASS] Agent flow correctly emits simulation log paths in SSE events.")

def test_api_endpoints():
    client = TestClient(app)
    session_id = "test_sess_001"
    
    # 1. Test /api/logs/{session_id}
    res = client.get(f"/api/logs/{session_id}")
    assert res.status_code == 200, f"Failed /api/logs: {res.text}"
    data = res.json()
    print("[API] /api/logs data:", data.get("total_simulations"), "iterations found.")
    assert data["total_simulations"] >= 1

    # 2. Test /api/logs/{session_id}/raw/{filename}
    log_filename = "sim_iter1.log"
    res_log = client.get(f"/api/logs/{session_id}/raw/{log_filename}")
    assert res_log.status_code == 200, f"Failed /api/logs raw: {res_log.text}"
    assert "RTL-AGENT SIMULATION & WAVEFORM LOG" in res_log.text
    print(f"[PASS] API raw log download verified ({len(res_log.text)} bytes).")

    # 3. Test /api/logs/{session_id}/latest_vcd on session with trace
    res_vcd = client.get("/api/logs/test_agent_flow_002/latest_vcd")
    assert res_vcd.status_code == 200, f"Failed latest_vcd: {res_vcd.text}"
    assert "$date" in res_vcd.text or "$version" in res_vcd.text or "$var" in res_vcd.text
    print(f"[PASS] API latest VCD download verified ({len(res_vcd.content)} bytes).")

if __name__ == "__main__":
    print("=== RUNNING SIMULATION LOGGING TESTS ===")
    test_simulator_logging_direct()
    asyncio.run(test_agent_event_flow())
    test_api_endpoints()
    print("\n[ALL PASS] ALL SIMULATION LOGGING & TRACE PERSISTENCE TESTS PASSED!")
