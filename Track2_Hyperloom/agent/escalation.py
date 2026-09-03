#!/usr/bin/env python3
"""
Hyperloom — local-first agent with confidence-gated Radeon-cloud escalation.

The local brain (a quantized LLM on an AMD Radeon GPU) drives the optimization
mission loop. Its inference is LOCAL and PRIVATE by default. Only when it gets
genuinely STUCK does it escalate a structured problem to a more capable model
served on the Radeon cloud — and the cloud's answer is treated as ASSUMED until
it passes a LOCAL correctness gate on the actual Radeon GPU.

Design goals (AMD AI DevMaster Hackathon, Track 2 "Private AI Agents"):
  * "Core inference processes shall be executed locally on AMD Radeon GPU"  -> local by default.
  * Radeon cloud model API used only as an on-demand assist                 -> hits the cloud-API bonus.
  * measure-never-assume: cloud advice is validated locally before use.

The cloud client is OpenAI-compatible (AMD AIMs / vLLM / llama-server all speak it),
so it plugs into whatever endpoint you deploy on a Radeon cloud instance.
"""
from __future__ import annotations
import os, json, re, time, urllib.request, urllib.error
from dataclasses import dataclass, field
from typing import Callable, Optional


# --------------------------------------------------------------------------------------
# Config — point this at the OpenAI-compatible endpoint you deploy on a Radeon cloud
# instance (vLLM / llama-server / AIM). Env-driven so nothing is hard-coded.
# --------------------------------------------------------------------------------------
CLOUD_BASE  = os.environ.get("RADEON_CLOUD_API_BASE", "")          # e.g. https://.../spaces/<id>/8000
CLOUD_KEY   = os.environ.get("RADEON_CLOUD_API_KEY", "")           # bearer token / API key
CLOUD_MODEL = os.environ.get("RADEON_CLOUD_MODEL", "")            # served model name


# --------------------------------------------------------------------------------------
# 1. Stuck-detector — decide when the local brain should escalate.
# --------------------------------------------------------------------------------------
_ESCALATE_MARK = re.compile(r"\[\[\s*ESCALATE\s*\]\]|I(?:'?m| am)\s+stuck", re.I)

@dataclass
class StuckDetector:
    """Trips when the local brain is genuinely stuck on a subtask, not just working.

    Stuck = ANY of:
      (a) >= max_failures correctness-gated failures on the same subtask,
      (b) degenerate / looping output (same output repeated, or collapsed),
      (c) an explicit self-report from the local brain ("[[ESCALATE]]" / "I'm stuck").
    """
    max_failures: int = 3
    loop_window: int = 3
    _failures: dict = field(default_factory=dict)   # subtask -> failed correctness-gated attempts
    _recent:   dict = field(default_factory=dict)   # subtask -> [recent outputs]

    def record_attempt(self, subtask: str, output: str, passed: bool) -> bool:
        """Record one attempt (output + whether it passed the local correctness gate).
        Returns True if the agent should now escalate."""
        if not passed:
            self._failures[subtask] = self._failures.get(subtask, 0) + 1
        buf = self._recent.setdefault(subtask, [])
        buf.append((output or "").strip())
        if len(buf) > self.loop_window:
            buf.pop(0)
        return self.is_stuck(subtask, output)

    def is_stuck(self, subtask: str, latest_output: Optional[str] = None) -> bool:
        if latest_output and _ESCALATE_MARK.search(latest_output):
            return True                                     # (c) explicit self-report
        if self._failures.get(subtask, 0) >= self.max_failures:
            return True                                     # (a) repeated correctness failures
        buf = self._recent.get(subtask, [])
        if len(buf) >= self.loop_window and len(set(buf)) == 1 and buf[0]:
            return True                                     # (b) identical output looping
        return False

    def reset(self, subtask: str) -> None:
        self._failures.pop(subtask, None)
        self._recent.pop(subtask, None)


# --------------------------------------------------------------------------------------
# 2. Structured escalation packet — Hyperloom's edge: don't ask "help", send the layered
#    fault-isolation context so the cloud model gets a precise, verifiable problem.
# --------------------------------------------------------------------------------------
@dataclass
class EscalationPacket:
    subtask: str                       # what we're trying to do
    layer: str                         # which stack layer (L1 ISA .. L7 serving)
    goal: str                          # the measurable target (e.g. "beat dp4a decode, err=0")
    evidence: str                      # pasted ground-truth stdout (rocminfo, disasm, bench, error)
    attempts: list = field(default_factory=list)   # [(what_we_tried, why_it_failed)]

    def to_prompt(self) -> str:
        tried = "\n".join(f"  - tried: {a}\n    failed: {b}" for a, b in self.attempts) or "  (none yet)"
        return (
            "You are an expert AMD ROCm/HIP GPU kernel engineer helping a local agent that is stuck.\n"
            "The agent works by LAYERED FAULT ISOLATION (L1 silicon/ISA -> L7 serving) and MEASURES "
            "everything; a fix is only accepted after it passes a numeric correctness gate on the real GPU.\n\n"
            f"SUBTASK: {self.subtask}\n"
            f"STACK LAYER: {self.layer}\n"
            f"GOAL (measurable): {self.goal}\n\n"
            f"GROUND-TRUTH EVIDENCE (verbatim tool output):\n{self.evidence}\n\n"
            f"WHAT THE LOCAL AGENT ALREADY TRIED (and why each failed):\n{tried}\n\n"
            "Give a concrete, minimal, correctness-preserving fix at THIS layer. Prefer a specific "
            "instruction/builtin/flag/kernel change over general advice. Return only the change and a "
            "one-line rationale. The agent will VALIDATE your suggestion locally before trusting it."
        )


# --------------------------------------------------------------------------------------
# 3. Cloud client — OpenAI-compatible POST to a Radeon-cloud-served model.
# --------------------------------------------------------------------------------------
class CloudEscalator:
    def __init__(self, base: str = CLOUD_BASE, key: str = CLOUD_KEY,
                 model: str = CLOUD_MODEL, timeout: int = 120):
        self.base, self.key, self.model, self.timeout = base.rstrip("/"), key, model, timeout

    def available(self) -> bool:
        return bool(self.base and self.model)

    def ask(self, packet: EscalationPacket, temperature: float = 0.2) -> str:
        """Send the structured packet to the Radeon-cloud model, return its raw suggestion."""
        if not self.available():
            raise RuntimeError(
                "Radeon cloud endpoint not configured. Set RADEON_CLOUD_API_BASE / _MODEL / _KEY "
                "to the OpenAI-compatible endpoint you deployed on a Radeon cloud instance.")
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": packet.to_prompt()}],
            "temperature": temperature,
            "max_tokens": 1024,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------------------
# 4. Orchestrator — escalate, then VALIDATE the cloud answer locally before trusting it.
# --------------------------------------------------------------------------------------
def escalate_and_validate(packet: EscalationPacket,
                          validate: Callable[[str], bool],
                          escalator: Optional[CloudEscalator] = None) -> dict:
    """
    1) ask the Radeon-cloud model for a fix (ASSUMED),
    2) run the LOCAL correctness gate `validate(suggestion)` on the real GPU,
    3) return the suggestion tagged MEASURED (passed) or REJECTED (cloud was wrong).
    The discipline holds even for cloud advice: it is not trusted until it runs and passes.
    """
    escalator = escalator or CloudEscalator()
    t0 = time.time()
    suggestion = escalator.ask(packet)
    passed = bool(validate(suggestion))
    return {
        "subtask": packet.subtask,
        "layer": packet.layer,
        "suggestion": suggestion,
        "status": "MEASURED-PASS" if passed else "REJECTED (cloud answer failed local gate)",
        "trusted": passed,
        "seconds": round(time.time() - t0, 1),
    }


# --------------------------------------------------------------------------------------
# Demo (offline) — shows the full flow with a stub cloud + stub gate, no endpoint needed.
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    det = StuckDetector(max_failures=2)
    sub = "int4 decode GEMV faster than dp4a"
    for out, ok in [("use v_dot4 dp4a", False), ("still dp4a", False)]:
        stuck = det.record_attempt(sub, out, ok)
        print(f"attempt ok={ok} -> stuck={stuck}")
    assert det.is_stuck(sub), "should be stuck after 2 failures"

    packet = EscalationPacket(
        subtask=sub, layer="L1 silicon/ISA",
        goal="beat dp4a int4 decode, err=0 vs CPU ref",
        evidence="scan-isa-gfx.sh: v_dot8_i32_iu4 PRESENT; current kernel emits only v_dot4_i32_iu8",
        attempts=[("dp4a via unpack int4->int8", "2 dot instrs/8 values, 1.0x")])
    print("\n--- escalation packet the cloud would receive ---\n")
    print(packet.to_prompt())

    class _StubCloud(CloudEscalator):
        def available(self): return True
        def ask(self, p, temperature=0.2):
            return "Use __builtin_amdgcn_sudot8 -> v_dot8_i32_iu4 (1 instr/8 int4 values, native)."
    result = escalate_and_validate(
        packet, validate=lambda s: "sudot8" in s and "v_dot8" in s, escalator=_StubCloud())
    print("\n--- result ---\n" + json.dumps(result, indent=2))
