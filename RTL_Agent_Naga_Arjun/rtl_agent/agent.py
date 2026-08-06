"""
agent.py — Core Autonomous RTL Verification Agent (v2: Two-Tier Loop).

Tier 1 — Syntax/Structure:
  verilator --lint-only catches compile errors → STDERR → LLM correction → repeat.

Tier 2 — Functional Correctness (NEW):
  Once Tier 1 passes, the agent generates a self-checking testbench, compiles
  and runs it with verilator --binary, and if it reports a FAIL (behavioral),
  feeds the simulation log back as a distinct correction prompt (functional
  behavior, not syntax).  If the --binary compile itself fails (structural
  elaboration error that --lint-only missed), it routes back through the Tier 1
  correction prompt instead (Amendment 2).

Amendments implemented:
  Am. 1 — MAX_TOTAL_ITERATIONS hard ceiling across both tiers.
  Am. 2 — SimResult.phase routes build failures → lint-correction prompt.
  Am. 6 — Single rolling message history spans both tiers.
  Am. 8 — elapsed_ms / tokens_generated telemetry in every LLM event.
"""

import asyncio
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List, Optional

from config import (
    MOCK_MODE, DEPLOY_MODE, VLLM_BASE_URL, VLLM_API_KEY, MODEL_NAME,
    MAX_TOKENS, TEMPERATURE,
    MAX_LINT_ITERATIONS, MAX_FUNCTIONAL_ITERATIONS, MAX_TOTAL_ITERATIONS,
    MAX_ITERATIONS,   # backward-compat alias
    WORKSPACE_DIR,
    ENABLE_PREFIX_CACHING, GPU_MEMORY_UTILIZATION, MAX_NUM_SEQS,
    QUANTIZATION, VLLM_DTYPE,
)
from prompts import (
    SYSTEM_PROMPT, TESTBENCH_GENERATION_SYSTEM_PROMPT,
    ARCHITECT_SYSTEM_PROMPT, build_architect_prompt,
    build_user_prompt, build_coder_user_prompt,
    build_correction_prompt,
    build_testbench_prompt, build_verifier_testbench_prompt,
    build_functional_correction_prompt,
    build_testbench_correction_prompt,
    build_testbench_functional_correction_prompt,
)
from tools.verilator_tool import run_verilator
from tools.sv_parser import extract_systemverilog
from tools.simulator_tool import run_simulation

# ─── LLM Client (initialized for all non-mock modes) ────────────────────────
_llm_client = None

if not MOCK_MODE:
    try:
        from openai import AsyncOpenAI

        # Remote APIs (amd-api, deepseek) need longer timeouts.
        # Local vLLM gets a shorter timeout since latency should be minimal.
        _timeout = 180.0 if DEPLOY_MODE in ("amd-api", "amd-deepseek", "deepseek") else 120.0

        # Use VLLM_BASE_URL / VLLM_API_KEY from config — NOT hardcoded localhost.
        # These are resolved from DEPLOY_MODE in config.py (_resolve_endpoint).
        _llm_client = AsyncOpenAI(
            base_url=VLLM_BASE_URL,
            api_key=VLLM_API_KEY or "sk-dummy",
            timeout=_timeout,
        )
    except ImportError as e:
        raise RuntimeError(
            "openai package not installed. Run: pip install openai"
        ) from e


# ─── Event builder ────────────────────────────────────────────────────────────
def _ev(event_type: str, **payload) -> Dict[str, Any]:
    return {"type": event_type, "ts": time.time(), **payload}


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────
async def run_agent(
    spec: str,
    session_id: str,
    max_iterations: int = MAX_ITERATIONS,   # kept for backward compat — ignored internally
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Main agentic loop. Yields JSON-serialisable event dicts.
    Consume with:  async for event in run_agent(spec, sid): ...

    The max_iterations parameter is kept for API compatibility but the actual
    limits are read from config: MAX_LINT_ITERATIONS, MAX_FUNCTIONAL_ITERATIONS,
    MAX_TOTAL_ITERATIONS (Amendment 1).
    """
    if MOCK_MODE:
        async for ev in _mock_loop(spec, session_id):
            yield ev
    else:
        async for ev in _real_loop(spec, session_id):
            yield ev


# ─────────────────────────────────────────────────────────────────────────────
#  LLM call helper (real mode) — returns full_response + usage stats (Am. 8)
# ─────────────────────────────────────────────────────────────────────────────
async def _llm_call(
    messages: List[Dict],
    session_id: str,
    iteration: int,
    system_override: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Async generator that streams tokens from the LLM and yields SSE events.
    Yields events; returns (full_response, elapsed_ms, tokens_generated) via
    a 1-element list side-channel (Python async generators can't return values).
    """
    # We can't return values from an async generator, so we use a shared list.
    raise NotImplementedError("Use _llm_stream() instead")


class _TelemetryTracker:
    def __init__(self):
        self.run_start_time = time.monotonic()
        self.first_token_time: Optional[float] = None
        self.total_tokens = 0


async def _llm_stream(
    messages: List[Dict],
    result_holder: list,
    iteration: int,
    tracker: Optional[_TelemetryTracker] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream LLM response, yielding SSE token events.
    Appends (full_response, elapsed_ms, tokens_generated, ttft_ms) to result_holder[0].

    Mode-aware:
      - vllm mode:    sends extra_body for prefix caching, shorter timeout
      - amd-api mode: no extra_body (hosted API), longer timeout, retry on 429/5xx
    """
    t0 = time.perf_counter()
    full_response = ""
    tokens_generated = 0
    ttft_ms: float = 0.0
    first_token_received = False

    yield _ev("llm_start", iteration=iteration, model=MODEL_NAME, deploy_mode=DEPLOY_MODE)

    # Build request kwargs (mode-aware)
    create_kwargs = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": True,
    }
    # Only local vLLM supports extra_body params for prefix caching
    if DEPLOY_MODE == "vllm":
        create_kwargs["extra_body"] = {"enable_prefix_caching": ENABLE_PREFIX_CACHING}

    # Retry for transient remote API failures (429 rate limit, 502/503 gateway)
    max_retries = 2 if DEPLOY_MODE in ("amd-api", "amd-deepseek") else 0
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            full_response = ""
            tokens_generated = 0
            ttft_ms = 0.0
            first_token_received = False

            stream = await _llm_client.chat.completions.create(**create_kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                content = delta.content or ""
                if content:
                    if not first_token_received:
                        ttft_ms = (time.perf_counter() - t0) * 1000
                        first_token_received = True
                        if tracker is not None and tracker.first_token_time is None:
                            tracker.first_token_time = time.monotonic()
                            ttft_total_ms = (tracker.first_token_time - tracker.run_start_time) * 1000
                            yield _ev("telemetry_update",
                                      ttft_ms=round(ttft_total_ms, 1),
                                      tokens_per_sec=0.0,
                                      total_tokens=tracker.total_tokens,
                                      elapsed_sec=round(tracker.first_token_time - tracker.run_start_time, 2))
                    full_response += content
                    tokens_generated += 1
                    if tracker is not None:
                        tracker.total_tokens += 1
                    yield _ev("llm_token", token=content)

            # Success — break out of retry loop
            last_error = None
            break

        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait_s = 2.0 * (attempt + 1)
                yield _ev("thought", message=f"⚠ API call failed ({exc}), retrying in {wait_s:.0f}s... (attempt {attempt+1}/{max_retries+1})")
                await asyncio.sleep(wait_s)
            else:
                yield _ev("error", message=f"LLM request failed after {attempt+1} attempt(s): {exc}")
                result_holder.append((None, 0.0, 0, 0.0))
                return

    elapsed_ms = (time.perf_counter() - t0) * 1000
    tps = (tokens_generated / elapsed_ms * 1000) if elapsed_ms > 0 else 0.0

    if tracker is not None:
        now = time.monotonic()
        tot_elapsed = now - tracker.run_start_time
        tok_per_sec = tracker.total_tokens / tot_elapsed if tot_elapsed > 0 else 0.0
        ttft_val = (tracker.first_token_time - tracker.run_start_time) * 1000 if tracker.first_token_time else 0.0
        yield _ev("telemetry_update",
                  ttft_ms=round(ttft_val, 1),
                  tokens_per_sec=round(tok_per_sec, 1),
                  total_tokens=tracker.total_tokens,
                  elapsed_sec=round(tot_elapsed, 2))

    yield _ev("llm_done",
               chars=len(full_response),
               elapsed_ms=elapsed_ms,
               ttft_ms=round(ttft_ms, 1),
               tokens_generated=tokens_generated,
               tokens_per_sec=round(tps, 1),
               prefix_caching=ENABLE_PREFIX_CACHING if DEPLOY_MODE == "vllm" else False,
               deploy_mode=DEPLOY_MODE)
    result_holder.append((full_response, elapsed_ms, tokens_generated, ttft_ms))


# ─────────────────────────────────────────────────────────────────────────────
#  Real Agent (vLLM + real Verilator) — 3-Agent Pipeline
# ─────────────────────────────────────────────────────────────────────────────
async def _real_loop(
    spec: str,
    session_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:

    # ── Pipeline State Dictionary (Pure Python State Machine) ─────────────────
    state: Dict[str, str] = {
        "spec": spec,
        "architect_plan": "",
        "rtl_code": "",
        "tb_code": ""
    }

    # Telemetry tracker across the entire session run
    tracker = _TelemetryTracker()

    # Global iteration counter across all agents
    total_iter = 0
    lint_status = "NOT_RUN"
    functional_status = "NOT_RUN"

    yield _ev("agent_start",
              spec=spec,
              session_id=session_id,
              max_lint_iterations=MAX_LINT_ITERATIONS,
              max_functional_iterations=MAX_FUNCTIONAL_ITERATIONS,
              max_total_iterations=MAX_TOTAL_ITERATIONS,
              mock=False,
              model=MODEL_NAME)

    # ══════════════════════════════════════════════════════════════════════════
    #  AGENT 1: ARCHITECT — Plan, Ports, Edge Cases, Verification Strategy
    # ══════════════════════════════════════════════════════════════════════════
    yield _ev("agent_status", agent="Architect", status="Drafting Verification Plan...")
    yield _ev("thought", message="[Agent 1 · Architect] Analyzing spec to draft Micro-Architecture & Verification Strategy...")

    arch_messages: List[Dict] = [
        {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
        {"role": "user",   "content": build_architect_prompt(state["spec"])},
    ]

    total_iter += 1
    arch_result: List = []
    async for ev in _llm_stream(arch_messages, arch_result, total_iter, tracker=tracker):
        yield ev

    if arch_result and arch_result[0][0]:
        state["architect_plan"] = arch_result[0][0]
    else:
        state["architect_plan"] = f"Micro-Architecture Plan for {state['spec']}"

    yield _ev("thought", message="[Agent 1 · Architect] Micro-Architecture plan finalized. Handing off to Coder...")
    yield _ev("agent_status", agent="Architect", status="Plan Complete ✓")

    # ══════════════════════════════════════════════════════════════════════════
    #  AGENT 2: CODER — RTL Generation & Verilator Lint Self-Correction
    # ══════════════════════════════════════════════════════════════════════════
    yield _ev("agent_status", agent="Coder", status="Synthesizing RTL & Linting...")
    yield _ev("thought", message="[Agent 2 · Coder] Synthesizing SystemVerilog RTL and executing Verilator lint loop...")

    messages: List[Dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": build_coder_user_prompt(state["spec"], state["architect_plan"])},
    ]

    final_dut: Optional[str] = None
    final_tb: Optional[str] = None
    dut_filename: Optional[str] = None
    sv_path = None

    lint_status = "RUNNING"
    for lint_iter in range(1, MAX_LINT_ITERATIONS + 1):
        if total_iter >= MAX_TOTAL_ITERATIONS:
            yield _ev("thought", message=f"⛔ Global iteration ceiling ({MAX_TOTAL_ITERATIONS}) reached. Stopping.")
            break

        total_iter += 1
        yield _ev("lint_iteration",
                  iteration=lint_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  phase="tier1_lint")

        action = "Generating initial RTL design" if lint_iter == 1 else "Rewriting — applying lint corrections"
        yield _ev("thought", message=f"[Tier 1 · Iter {lint_iter}/{MAX_LINT_ITERATIONS} · Total {total_iter}/{MAX_TOTAL_ITERATIONS}] {action}...")

        # ── LLM call ──────────────────────────────────────────────────────
        result_holder: list = []
        async for ev in _llm_stream(messages, result_holder, total_iter, tracker=tracker):
            yield ev

        if not result_holder or result_holder[0][0] is None:
            return   # error already emitted by _llm_stream

        full_response, elapsed_ms, tok, ttft_ms = result_holder[0]

        # ── Extract SV ────────────────────────────────────────────────────
        _dump_label = f"{session_id}_parse_fail_iter{total_iter}"
        sv_code = extract_systemverilog(
            full_response,
            dump_on_failure=True,
            dump_path=WORKSPACE_DIR,
            label=_dump_label,
        )
        if not sv_code:
            yield _ev("thought",
                      message=f"[!] Could not extract SV from response. "
                              f"Raw response saved to workspace/{_dump_label}.txt. "
                              "Asking LLM to reformat...")
            messages.append({"role": "assistant", "content": full_response})
            messages.append({
                "role": "user",
                "content": (
                    "Your response did not contain a parseable SystemVerilog code block.\n"
                    "Output the complete module inside exactly ONE ```verilog fence.\n"
                    "Example:\n"
                    "```verilog\n"
                    "module example(input logic a, output logic b);\n"
                    "  assign b = a;\n"
                    "endmodule\n"
                    "```\n"
                    "No other text after the closing fence."
                ),
            })
            continue

        sv_filename = f"{session_id}_iter{total_iter}.sv"
        sv_path = WORKSPACE_DIR / sv_filename
        sv_path.write_text(sv_code, encoding="utf-8")

        yield _ev("code_generated",
                  iteration=lint_iter,
                  total_iterations=total_iter,
                  code=sv_code,
                  filename=sv_filename,
                  lines=sv_code.count("\n") + 1,
                  elapsed_ms=elapsed_ms,
                  ttft_ms=ttft_ms,
                  tokens_generated=tok)

        # ── Verilator lint ────────────────────────────────────────────────
        yield _ev("thought", message=f"Running: verilator --lint-only -Wall -Wno-style --timing {sv_filename}")
        yield _ev("tool_call", tool="verilator", file=sv_filename)

        vresult = await asyncio.get_event_loop().run_in_executor(
            None, run_verilator, str(sv_path)
        )

        yield _ev("lint_iteration",
                  iteration=lint_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  code=sv_code,
                  verilator_log=vresult["stderr"] or vresult["stdout"],
                  passed=vresult["success"],
                  phase="tier1_lint_result")

        yield _ev("tool_result",
                  tool="verilator",
                  success=vresult["success"],
                  returncode=vresult["returncode"],
                  stdout=vresult["stdout"],
                  stderr=vresult["stderr"])

        if vresult["success"]:
            lint_status = "PASSED"
            final_dut = sv_code
            state["rtl_code"] = sv_code
            dut_filename = sv_filename
            yield _ev("thought", message="✓ Tier 1 PASSED — design is lint-clean. Handing off to Verifier.")
            yield _ev("agent_status", agent="Coder", status="RTL Lint-Clean ✓")
            break

        # ── Self-correction ────────────────────────────────────────────────
        error_log = vresult["stderr"] or vresult["stdout"]
        error_lines = [l for l in error_log.splitlines() if "error" in l.lower()]
        yield _ev("thought",
                  message=f"Verilator found {len(error_lines)} error line(s). "
                           "Injecting error context into conversation history...")

        messages.append({"role": "assistant", "content": full_response})
        messages.append({
            "role": "user",
            "content": build_correction_prompt(sv_code, error_log, lint_iter),
        })
    else:
        # Exhausted Tier 1 iterations without a clean lint
        lint_status = "FAILED"

    if lint_status != "PASSED":
        yield _ev("agent_status", agent="Coder", status="Lint Failed ✗")
        functional_status = "NOT_RUN"
        yield _ev("final_result",
                  lint_status=lint_status,
                  functional_status=functional_status,
                  final_dut=final_dut,
                  final_tb=None,
                  total_iterations=total_iter,
                  message=f"RTL synthesis/lint failed after {total_iter} iteration(s).")
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  AGENT 3: VERIFIER — Testbench Generation & Simulation Verification Loop
    # ══════════════════════════════════════════════════════════════════════════
    # Generate testbench (uses its own system prompt but SAME conversation history)
    if total_iter >= MAX_TOTAL_ITERATIONS:
        yield _ev("thought", message="⛔ Global ceiling reached before Verifier could start.")
        yield _ev("final_result",
                  lint_status="PASSED",
                  functional_status="NOT_RUN",
                  final_dut=final_dut,
                  final_tb=None,
                  total_iterations=total_iter,
                  message="Global iteration ceiling reached after Tier 1.")
        return

    yield _ev("agent_status", agent="Verifier", status="Simulating & Extracting Waveforms...")
    total_iter += 1
    yield _ev("thought", message="[Agent 3 · Verifier] Generating self-checking testbench with VCD waveform extraction...")

    # Amendment 6: append testbench request to the SAME rolling history
    messages.append({"role": "assistant", "content": f"```verilog\n{final_dut}\n```"})
    messages.append({
        "role": "user",
        "content": build_verifier_testbench_prompt(state["spec"], final_dut, state["architect_plan"]),
    })
    # Override system prompt for testbench generation (allows $display, etc.)
    tb_messages = [
        {"role": "system", "content": TESTBENCH_GENERATION_SYSTEM_PROMPT},
        *messages[1:],   # reuse full conversation context minus original system prompt
    ]

    tb_result_holder: list = []
    async for ev in _llm_stream(tb_messages, tb_result_holder, total_iter, tracker=tracker):
        yield ev

    if not tb_result_holder or tb_result_holder[0][0] is None:
        return

    tb_response, tb_elapsed_ms, tb_tok, tb_ttft_ms = tb_result_holder[0]

    # Extract testbench code (uses ```verilog fence from build_testbench_prompt)
    tb_code = extract_systemverilog(tb_response)
    if not tb_code:
        # Fallback: try to use the whole response if it contains a module keyword
        tb_code = tb_response

    tb_filename = f"{session_id}_tb_iter{total_iter}.sv"
    tb_path = WORKSPACE_DIR / tb_filename
    tb_path.write_text(tb_code, encoding="utf-8")
    final_tb = tb_code
    state["tb_code"] = tb_code

    yield _ev("testbench_generated",
              total_iterations=total_iter,
              code=tb_code,
              filename=tb_filename,
              elapsed_ms=tb_elapsed_ms,
              ttft_ms=tb_ttft_ms,
              tokens_generated=tb_tok)

    # ── Functional iteration loop ─────────────────────────────────────────
    functional_status = "RUNNING"
    workdir = str(WORKSPACE_DIR / f"{session_id}_sim")

    for func_iter in range(1, MAX_FUNCTIONAL_ITERATIONS + 1):
        if total_iter >= MAX_TOTAL_ITERATIONS:
            yield _ev("thought", message=f"⛔ Global iteration ceiling ({MAX_TOTAL_ITERATIONS}) reached during Tier 2.")
            break

        # ── Run simulation ────────────────────────────────────────────────
        yield _ev("thought", message=f"[Tier 2 · Func {func_iter}/{MAX_FUNCTIONAL_ITERATIONS} · Total {total_iter}/{MAX_TOTAL_ITERATIONS}] Running functional simulation...")

        sim = await asyncio.get_event_loop().run_in_executor(
            None, run_simulation,
            str(sv_path), tb_code, workdir
        )

        # Amendment 2: distinguish build vs run phase for event routing
        event_type = "sim_build_error" if (not sim.passed and sim.phase == "build") else "sim_iteration"
        yield _ev(event_type,
                  iteration=func_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  sim_stdout=sim.stdout,
                  sim_stderr=sim.stderr,
                  passed=sim.passed,
                  timed_out=sim.timed_out,
                  phase=sim.phase,
                  elapsed_ms=sim.elapsed_ms)

        if sim.vcd_data is not None:
            yield _ev("waveform_ready",
                      vcd_data=sim.vcd_data,
                      vcd_size_bytes=sim.vcd_size_bytes)
        elif sim.vcd_size_bytes > 0:
            yield _ev("waveform_warning",
                      message=f"VCD too large ({sim.vcd_size_bytes:,} bytes). Add #5000 $finish to testbench.")

        if sim.passed:
            functional_status = "PASSED"
            yield _ev("agent_status", agent="Verifier", status="Verification Passed ✓")
            yield _ev("final_result",
                      lint_status="PASSED",
                      functional_status="PASSED",
                      final_dut=state["rtl_code"],
                      final_tb=state["tb_code"],
                      total_iterations=total_iter,
                      message=f"✓ Complete 3-Agent Pipeline PASSED in {total_iter} total iteration(s). Architect ➔ Coder ➔ Verifier clean.")
            return

        # ── Dual-track routing on failure ─────────────────────────────────────────
        total_iter += 1
        sim_log = sim.stdout + ("\n" + sim.stderr if sim.stderr else "")

        if sim.phase == "build":
            # Check whether the error is in the TESTBENCH or the DUT.
            # sim.error_file is set to "tb_top.sv" by simulator_tool when the
            # error text references that filename; otherwise it's empty.
            tb_error = (
                sim.error_file == "tb_top.sv"
                or "tb_top.sv" in sim_log
                or "tb_" in sim_log
                or "Cannot find file containing module" in sim_log
                or "top-module" in sim_log
            )

            if tb_error:
                # Testbench has the error -- DUT is correct and FROZEN.
                # Regenerate only the testbench; do not touch final_dut.
                yield _ev("thought",
                          message="[Tier 2] Build FAILED in TESTBENCH (not DUT). "
                                   "DUT frozen. Regenerating testbench only...")
                tb_messages_fix = [
                    {"role": "system", "content": TESTBENCH_GENERATION_SYSTEM_PROMPT},
                    {"role": "user",
                     "content": build_testbench_correction_prompt(
                         state["spec"], final_dut, tb_code, sim_log
                     )},
                ]
                tb_fix_result: list = []
                async for ev in _llm_stream(tb_messages_fix, tb_fix_result, total_iter, tracker=tracker):
                    yield ev

                if tb_fix_result and tb_fix_result[0][0] is not None:
                    tb_fix_resp = tb_fix_result[0][0]
                    new_tb = extract_systemverilog(tb_fix_resp)
                    if new_tb:
                        tb_code = new_tb
                        final_tb = new_tb
                        state["tb_code"] = new_tb
                        tb_path.write_text(new_tb, encoding="utf-8")
                        yield _ev("testbench_generated",
                                  total_iterations=total_iter,
                                  code=new_tb,
                                  filename=str(tb_path.name),
                                  elapsed_ms=tb_fix_result[0][1],
                                  ttft_ms=tb_fix_result[0][3],
                                  tokens_generated=tb_fix_result[0][2],
                                  source="tb_correction")
                continue  # retry simulation with fixed testbench

            else:
                # Error is in the DUT -- use lint correction prompt.
                yield _ev("thought",
                          message="[Am.2] Build FAILED in DUT (structural/elaboration error). "
                                   "Routing to Tier 1 lint correction prompt.")
                messages.append({"role": "assistant", "content": f"```verilog\n{final_dut}\n```"})
                messages.append({
                    "role": "user",
                    "content": build_correction_prompt(final_dut, sim_log, total_iter),
                })

        else:
            # run failure -- behavioral bug -- alternate between DUT fix and Testbench fix
            # If func_iter is even, reflect on the testbench to fix flawed assertions/expectations
            if func_iter % 2 == 0:
                yield _ev("thought",
                          message="[Tier 2] Simulation FAILED functionally. "
                                   "Reflecting on TESTBENCH assertions & expectations (DUT frozen)...")
                tb_messages_fix = [
                    {"role": "system", "content": TESTBENCH_GENERATION_SYSTEM_PROMPT},
                    {"role": "user",
                     "content": build_testbench_functional_correction_prompt(
                         state["spec"], final_dut, tb_code, sim_log
                     )},
                ]
                tb_fix_result: list = []
                async for ev in _llm_stream(tb_messages_fix, tb_fix_result, total_iter, tracker=tracker):
                    yield ev

                if tb_fix_result and tb_fix_result[0][0] is not None:
                    tb_fix_resp = tb_fix_result[0][0]
                    new_tb = extract_systemverilog(tb_fix_resp)
                    if new_tb:
                        tb_code = new_tb
                        final_tb = new_tb
                        state["tb_code"] = new_tb
                        tb_path.write_text(new_tb, encoding="utf-8")
                        yield _ev("testbench_generated",
                                  total_iterations=total_iter,
                                  code=new_tb,
                                  filename=str(tb_path.name),
                                  elapsed_ms=tb_fix_result[0][1],
                                  ttft_ms=tb_fix_result[0][3],
                                  tokens_generated=tb_fix_result[0][2],
                                  source="tb_functional_correction")
                continue  # re-run simulation with the corrected testbench

            else:
                # Odd iteration: feed sim log into DUT behavioral correction prompt
                yield _ev("thought",
                          message="[Tier 2] Simulation FAILED functionally. "
                                   "Feeding sim log into DUT behavioral correction prompt...")
                messages.append({"role": "assistant", "content": f"```verilog\n{final_dut}\n```"})
                messages.append({
                    "role": "user",
                    "content": build_functional_correction_prompt(sim_log, state["spec"], final_dut),
                })

        yield _ev("thought", message=f"[Total {total_iter}/{MAX_TOTAL_ITERATIONS}] Generating corrected DUT...")

        # ── Re-generate DUT ───────────────────────────────────────────────
        regen_result: list = []
        async for ev in _llm_stream(messages, regen_result, total_iter, tracker=tracker):
            yield ev

        if not regen_result or regen_result[0][0] is None:
            return

        regen_response, regen_elapsed, regen_tok, regen_ttft = regen_result[0]
        new_sv_code = extract_systemverilog(regen_response)

        if not new_sv_code:
            yield _ev("thought", message="⚠ Could not parse SV from functional-correction response.")
            continue

        sv_filename = f"{session_id}_iter{total_iter}.sv"
        sv_path = WORKSPACE_DIR / sv_filename
        sv_path.write_text(new_sv_code, encoding="utf-8")
        final_dut = new_sv_code
        state["rtl_code"] = new_sv_code

        yield _ev("code_generated",
                  iteration=total_iter,
                  total_iterations=total_iter,
                  code=new_sv_code,
                  filename=sv_filename,
                  lines=new_sv_code.count("\n") + 1,
                  elapsed_ms=regen_elapsed,
                  ttft_ms=regen_ttft,
                  tokens_generated=regen_tok,
                  source="functional_correction")

        # ── Re-lint before re-running simulation ─────────────────────────
        # A functional fix can reintroduce a syntax error
        yield _ev("thought", message="Re-linting corrected DUT before re-attempting simulation...")
        yield _ev("tool_call", tool="verilator", file=sv_filename)

        vresult2 = await asyncio.get_event_loop().run_in_executor(
            None, run_verilator, str(sv_path)
        )

        yield _ev("lint_iteration",
                  iteration=total_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  code=new_sv_code,
                  verilator_log=vresult2["stderr"] or vresult2["stdout"],
                  passed=vresult2["success"],
                  phase="tier2_relint")

        yield _ev("tool_result",
                  tool="verilator",
                  success=vresult2["success"],
                  returncode=vresult2["returncode"],
                  stdout=vresult2["stdout"],
                  stderr=vresult2["stderr"])

        if not vresult2["success"]:
            # Functional fix introduced a syntax error — another total iteration consumed
            if total_iter >= MAX_TOTAL_ITERATIONS:
                break
            total_iter += 1
            yield _ev("thought", message="⚠ Functional fix reintroduced a lint error. Applying Tier 1 correction...")
            error_log2 = vresult2["stderr"] or vresult2["stdout"]
            messages.append({"role": "assistant", "content": regen_response})
            messages.append({
                "role": "user",
                "content": build_correction_prompt(new_sv_code, error_log2, total_iter),
            })

            lint_fix_result: list = []
            async for ev in _llm_stream(messages, lint_fix_result, total_iter, tracker=tracker):
                yield ev

            if lint_fix_result and lint_fix_result[0][0] is not None:
                fixed_resp, fixed_elapsed, fixed_tok, fixed_ttft = lint_fix_result[0]
                fixed_code = extract_systemverilog(fixed_resp)
                if fixed_code:
                    sv_filename = f"{session_id}_iter{total_iter}.sv"
                    sv_path = WORKSPACE_DIR / sv_filename
                    sv_path.write_text(fixed_code, encoding="utf-8")
                    final_dut = fixed_code
                    state["rtl_code"] = fixed_code
                    yield _ev("code_generated",
                              iteration=total_iter,
                              total_iterations=total_iter,
                              code=fixed_code,
                              filename=sv_filename,
                              lines=fixed_code.count("\n") + 1,
                              elapsed_ms=fixed_elapsed,
                              ttft_ms=fixed_ttft,
                              tokens_generated=fixed_tok,
                              tier="tier1_relint_fix")
    else:
        # Functional loop exhausted
        functional_status = "FAILED"

    if functional_status not in ("PASSED",):
        functional_status = "FAILED"
        yield _ev("agent_status", agent="Verifier", status="Verification Incomplete ✗")

    yield _ev("final_result",
              lint_status="PASSED",
              functional_status=functional_status,
              final_dut=final_dut,
              final_tb=final_tb,
              total_iterations=total_iter,
              message=(
                  f"Lint PASSED but functional verification {'FAILED' if functional_status == 'FAILED' else 'did not complete'} "
                  f"after {total_iter} total iteration(s). Partial result — see simulation log."
              ))


# ─────────────────────────────────────────────────────────────────────────────
#  Mock Agent (pre-scripted for demo / local dev) — 3-Agent Pipeline
# ─────────────────────────────────────────────────────────────────────────────
async def _mock_loop(
    spec: str,
    session_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:

    from tools.mock_responses import (
        get_mock_responses, get_mock_tb_response,
        get_mock_functional_fix_response, reset_mock_sim_counter,
        get_mock_sim_result, get_mock_architect_response,
        _COUNTER_ASYNC_RESET_BUGGY, _llm_wrap as _mwrap
    )
    from tools.simulator_tool import SimResult

    state: Dict[str, str] = {
        "spec": spec,
        "architect_plan": "",
        "rtl_code": "",
        "tb_code": ""
    }

    # Reset functional mock counter for this session
    reset_mock_sim_counter()

    # Tier 1 lint responses (scripted fail→fix sequence)
    lint_responses = get_mock_responses(spec)

    # For mock: use a fresh counter DUT that passes lint but has async reset (fails sim)
    # We hijack the clean counter from mock_responses and replace it with the async-reset version

    # Override last lint response's code with the async-reset buggy version
    # so Tier 2 has something meaningful to catch
    if lint_responses and lint_responses[-1][1] is None:
        # Replace the "clean" lint response's DUT with the async-reset version
        # so it passes --lint-only but fails simulation
        clean_tb_resp = _mwrap(
            _COUNTER_ASYNC_RESET_BUGGY,
            "I identified and fixed the lint error. The design now passes verilator --lint-only. "
            "Note: I used an asynchronous reset for robustness.",
        )
        lint_responses[-1] = (clean_tb_resp, None)

    total_iter = 0
    lint_status = "NOT_RUN"
    functional_status = "NOT_RUN"

    yield _ev("agent_start",
              spec=spec,
              session_id=session_id,
              max_lint_iterations=MAX_LINT_ITERATIONS,
              max_functional_iterations=MAX_FUNCTIONAL_ITERATIONS,
              max_total_iterations=MAX_TOTAL_ITERATIONS,
              mock=True,
              model=f"{MODEL_NAME} [MOCK]")

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 1: AGENT 1 (Architect)
    # ══════════════════════════════════════════════════════════════════════════
    yield _ev("agent_status", agent="Architect", status="Drafting Verification Plan...")
    yield _ev("thought", message="[Agent 1 · Architect] Analyzing spec to draft Micro-Architecture & Verification Strategy...")
    await asyncio.sleep(0.5)

    arch_response = get_mock_architect_response(spec)
    total_iter += 1
    yield _ev("llm_start", iteration=total_iter, model=f"{MODEL_NAME} [MOCK]")
    arch_words = arch_response.split(" ")
    for i, word in enumerate(arch_words):
        token = word + (" " if i < len(arch_words) - 1 else "")
        yield _ev("llm_token", token=token)
        if i % 12 == 0:
            await asyncio.sleep(0.015)
    yield _ev("llm_done", chars=len(arch_response), elapsed_ms=650.0, tokens_generated=len(arch_words),
              ttft_ms=110.0, tokens_per_sec=len(arch_words)/0.65, prefix_caching=False)

    state["architect_plan"] = arch_response
    yield _ev("thought", message="[Agent 1 · Architect] Plan formulated. Handoff to Coder for RTL synthesis.")
    yield _ev("agent_status", agent="Architect", status="Plan Complete ✓")
    await asyncio.sleep(0.3)

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 2: AGENT 2 (Coder)
    # ══════════════════════════════════════════════════════════════════════════
    yield _ev("agent_status", agent="Coder", status="Synthesizing RTL & Linting...")
    yield _ev("thought", message="[Agent 2 · Coder] Synthesizing SystemVerilog RTL and executing Verilator lint loop...")
    await asyncio.sleep(0.3)

    final_dut: Optional[str] = None
    final_tb: Optional[str] = None
    lint_status = "RUNNING"
    sv_path = None

    for lint_iter, (mock_llm_response, mock_error) in enumerate(lint_responses, 1):
        if total_iter >= MAX_TOTAL_ITERATIONS:
            break

        total_iter += 1
        yield _ev("lint_iteration",
                  iteration=lint_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  phase="tier1_lint")
        await asyncio.sleep(0.3)

        action = "Generating initial RTL design" if lint_iter == 1 else "Rewriting — applying lint corrections"
        yield _ev("thought", message=f"[Tier 1 · Iter {lint_iter} · Total {total_iter}/{MAX_TOTAL_ITERATIONS}] {action}...")
        await asyncio.sleep(0.5)

        # Simulate token streaming
        yield _ev("llm_start", iteration=total_iter, model=f"{MODEL_NAME} [MOCK]")
        words = mock_llm_response.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield _ev("llm_token", token=token)
            if i % 8 == 0:
                await asyncio.sleep(0.018)
        yield _ev("llm_done", chars=len(mock_llm_response), elapsed_ms=850.0, tokens_generated=len(words),
                  ttft_ms=120.0, tokens_per_sec=len(words)/0.85, prefix_caching=False)

        sv_code = extract_systemverilog(mock_llm_response)
        if not sv_code:
            sv_code = mock_llm_response

        sv_filename = f"{session_id}_iter{total_iter}.sv"
        sv_path = WORKSPACE_DIR / sv_filename
        sv_path.write_text(sv_code, encoding="utf-8")

        yield _ev("code_generated",
                  iteration=lint_iter,
                  total_iterations=total_iter,
                  code=sv_code,
                  filename=sv_filename,
                  lines=sv_code.count("\n") + 1,
                  elapsed_ms=850.0,
                  tokens_generated=len(words))

        await asyncio.sleep(0.3)
        yield _ev("thought", message=f"Running: verilator --lint-only --Wall --timing {sv_filename}")
        yield _ev("tool_call", tool="verilator", file=sv_filename)
        await asyncio.sleep(0.8)

        if mock_error:
            yield _ev("tool_result",
                      tool="verilator",
                      success=False,
                      returncode=1,
                      stdout="",
                      stderr=mock_error)
            yield _ev("lint_iteration",
                      iteration=lint_iter,
                      total_iterations=total_iter,
                      max_total=MAX_TOTAL_ITERATIONS,
                      code=sv_code,
                      verilator_log=mock_error,
                      passed=False,
                      phase="tier1_lint_result")
            await asyncio.sleep(0.4)
            err_count = mock_error.lower().count("error:")
            yield _ev("thought",
                      message=f"Verilator reported {err_count} error(s). "
                               "Parsing error messages and building correction prompt...")
            await asyncio.sleep(0.5)
        else:
            # Lint clean — proceed to Tier 2
            yield _ev("tool_result",
                      tool="verilator",
                      success=True,
                      returncode=0,
                      stdout=f"%verilator: lint: {sv_filename}: No issues found.\n",
                      stderr="")
            yield _ev("lint_iteration",
                      iteration=lint_iter,
                      total_iterations=total_iter,
                      max_total=MAX_TOTAL_ITERATIONS,
                      code=sv_code,
                      verilator_log="",
                      passed=True,
                      phase="tier1_lint_result")
            lint_status = "PASSED"
            final_dut = sv_code
            state["rtl_code"] = sv_code
            yield _ev("thought", message="✓ Tier 1 PASSED. Proceeding to Verifier for functional simulation...")
            yield _ev("agent_status", agent="Coder", status="RTL Lint-Clean ✓")
            await asyncio.sleep(0.3)
            break
    else:
        lint_status = "FAILED"

    if lint_status != "PASSED":
        yield _ev("agent_status", agent="Coder", status="Lint Failed ✗")
        functional_status = "NOT_RUN"
        yield _ev("final_result",
                  lint_status="FAILED",
                  functional_status="NOT_RUN",
                  final_dut=final_dut,
                  final_tb=None,
                  total_iterations=total_iter,
                  message=f"Lint failed after {total_iter} iteration(s).")
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 3: AGENT 3 (Verifier)
    # ══════════════════════════════════════════════════════════════════════════
    if total_iter >= MAX_TOTAL_ITERATIONS:
        yield _ev("final_result",
                  lint_status="PASSED",
                  functional_status="NOT_RUN",
                  final_dut=final_dut,
                  final_tb=None,
                  total_iterations=total_iter,
                  message="Global ceiling reached before Tier 2.")
        return

    yield _ev("agent_status", agent="Verifier", status="Simulating & Extracting Waveforms...")
    total_iter += 1
    yield _ev("thought", message="[Agent 3 · Verifier] Generating self-checking testbench with VCD trace dump...")
    await asyncio.sleep(0.5)

    tb_response = get_mock_tb_response(spec)
    yield _ev("llm_start", iteration=total_iter, model=f"{MODEL_NAME} [MOCK]")
    tb_words = tb_response.split(" ")
    for i, word in enumerate(tb_words):
        token = word + (" " if i < len(tb_words) - 1 else "")
        yield _ev("llm_token", token=token)
        if i % 8 == 0:
            await asyncio.sleep(0.018)
    yield _ev("llm_done", chars=len(tb_response), elapsed_ms=920.0, tokens_generated=len(tb_words),
              ttft_ms=130.0, tokens_per_sec=len(tb_words)/0.92, prefix_caching=False)

    tb_code = extract_systemverilog(tb_response)
    if not tb_code:
        tb_code = tb_response

    tb_filename = f"{session_id}_tb_iter{total_iter}.sv"
    tb_path = WORKSPACE_DIR / tb_filename
    tb_path.write_text(tb_code, encoding="utf-8")
    final_tb = tb_code
    state["tb_code"] = tb_code

    yield _ev("testbench_generated",
              total_iterations=total_iter,
              code=tb_code,
              filename=tb_filename,
              elapsed_ms=920.0,
              tokens_generated=len(tb_words))
    await asyncio.sleep(0.3)

    # ──  Functional iteration loop (mock) ────────────────────────────────────
    functional_status = "RUNNING"

    for func_iter in range(1, MAX_FUNCTIONAL_ITERATIONS + 1):
        if total_iter >= MAX_TOTAL_ITERATIONS:
            break

        yield _ev("thought", message=f"[Tier 2 · Func {func_iter}/{MAX_FUNCTIONAL_ITERATIONS} · Total {total_iter}/{MAX_TOTAL_ITERATIONS}] Running mock functional simulation...")
        await asyncio.sleep(1.0)  # simulate compilation + run time

        # Get scripted SimResult
        sim = get_mock_sim_result(str(sv_path), tb_code)

        event_type = "sim_build_error" if (not sim.passed and sim.phase == "build") else "sim_iteration"
        yield _ev(event_type,
                  iteration=func_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  sim_stdout=sim.stdout,
                  sim_stderr=sim.stderr,
                  passed=sim.passed,
                  timed_out=sim.timed_out,
                  phase=sim.phase,
                  elapsed_ms=sim.elapsed_ms)

        if sim.vcd_data is not None:
            yield _ev("waveform_ready",
                      vcd_data=sim.vcd_data,
                      vcd_size_bytes=sim.vcd_size_bytes)
        elif sim.vcd_size_bytes > 0:
            yield _ev("waveform_warning",
                      message=f"VCD too large ({sim.vcd_size_bytes:,} bytes). Add #5000 $finish to testbench.")

        if sim.passed:
            functional_status = "PASSED"
            yield _ev("agent_status", agent="Verifier", status="Verification Passed ✓")
            yield _ev("final_result",
                      lint_status="PASSED",
                      functional_status="PASSED",
                      final_dut=state["rtl_code"],
                      final_tb=state["tb_code"],
                      total_iterations=total_iter,
                      message=f"✓ Complete 3-Agent Pipeline PASSED in {total_iter} total iteration(s). Architect ➔ Coder ➔ Verifier clean.")
            return

        # Generate functional correction
        total_iter += 1
        yield _ev("thought",
                  message=f"[Tier 2] Simulation FAILED (async reset policy violation detected). "
                           "Generating behavioral correction... [Total {total_iter}/{MAX_TOTAL_ITERATIONS}]")
        await asyncio.sleep(0.4)

        fix_response = get_mock_functional_fix_response(spec)
        yield _ev("llm_start", iteration=total_iter, model=f"{MODEL_NAME} [MOCK]")
        fix_words = fix_response.split(" ")
        for i, word in enumerate(fix_words):
            token = word + (" " if i < len(fix_words) - 1 else "")
            yield _ev("llm_token", token=token)
            if i % 8 == 0:
                await asyncio.sleep(0.018)
        yield _ev("llm_done", chars=len(fix_response), elapsed_ms=780.0, tokens_generated=len(fix_words),
                  ttft_ms=110.0, tokens_per_sec=len(fix_words)/0.78, prefix_caching=False)

        fixed_sv = extract_systemverilog(fix_response)
        if not fixed_sv:
            fixed_sv = fix_response

        sv_filename = f"{session_id}_iter{total_iter}.sv"
        sv_path = WORKSPACE_DIR / sv_filename
        sv_path.write_text(fixed_sv, encoding="utf-8")
        final_dut = fixed_sv
        state["rtl_code"] = fixed_sv

        yield _ev("code_generated",
                  iteration=total_iter,
                  total_iterations=total_iter,
                  code=fixed_sv,
                  filename=sv_filename,
                  lines=fixed_sv.count("\n") + 1,
                  elapsed_ms=780.0,
                  tokens_generated=len(fix_words),
                  tier="tier2_correction")

        # Mock re-lint (always passes since the fix is clean)
        await asyncio.sleep(0.5)
        yield _ev("thought", message="Re-linting corrected DUT before re-attempting simulation...")
        yield _ev("lint_iteration",
                  iteration=total_iter,
                  total_iterations=total_iter,
                  max_total=MAX_TOTAL_ITERATIONS,
                  code=fixed_sv,
                  verilator_log="",
                  passed=True,
                  phase="tier2_relint")
        yield _ev("tool_result",
                  tool="verilator",
                  success=True,
                  returncode=0,
                  stdout=f"%verilator: lint: {sv_filename}: No issues found.\n",
                  stderr="")
        await asyncio.sleep(0.3)

    else:
        functional_status = "FAILED"

    if functional_status not in ("PASSED",):
        functional_status = "FAILED"
        yield _ev("agent_status", agent="Verifier", status="Verification Incomplete ✗")

    yield _ev("final_result",
              lint_status="PASSED",
              functional_status=functional_status,
              final_dut=final_dut,
              final_tb=final_tb,
              total_iterations=total_iter,
              message=f"Lint PASSED but functional verification FAILED after {total_iter} total iteration(s).")


# ─────────────────────────────────────────────────────────────────────────────
#  Public Entrypoint
# ─────────────────────────────────────────────────────────────────────────────
async def run_agent(
    spec: str,
    session_id: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Main entry point for running the 3-agent verification loop.
    Dispatches to _mock_loop in mock mode or _real_loop in live mode.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    if MOCK_MODE:
        async for ev in _mock_loop(spec, session_id):
            yield ev
    else:
        async for ev in _real_loop(spec, session_id):
            yield ev


# Backward compatibility alias
run_agent_loop = run_agent


