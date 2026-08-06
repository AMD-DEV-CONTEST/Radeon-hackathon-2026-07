# NobiRack — Track 3 Submission

**Track:** Track 3 — Physical AI Challenge  
**Team:** NobiDefence  
**Application:** NobiRack  
**Developer:** Manibharathy K

## Project

NobiRack is a Physical AI system for autonomous server-rack inspection and diagnostics in data centers.

It provides an independent physical diagnostic path when remote monitoring is unavailable or inconclusive. The system combines a robot digital twin, RGB and ToF observations, physical/digital evidence fusion, diagnostics, planning, and safety-policy gating.

## AMD Radeon / ROCm

NobiRack was validated on AMD Radeon Cloud using PyTorch with ROCm 7.2 / HIP.

GPU: AMD Radeon Graphics (gfx1100)

GPU compute validation: PASS

Cloud repository validation:
- 248 tests passed
- 9 tests skipped

## Final Demo Workflow

Remote fault
→ Robot dispatch
→ Front inspection
→ Rear inspection
→ Service-port alignment
→ Local diagnostic
→ Evidence fusion
→ NETWORK_DOWN diagnosis
→ Safety-gated recommendation
→ Return to dock

Physical remediation requires separate approval.

**NO AUTOMATIC HARDWARE MODIFICATION.**

## Perception Disclosure

NobiRackVisionNet and the AMD ROCm inference path are implemented.

The trained checkpoint was not recoverable for the final submission. Therefore, the deterministic final demonstration uses SyntheticPerceptionAdapter fallback. We do not claim that the final Genesis RGB frames are classified by a trained CNN.

## Source Code

https://github.com/ManiBharathy-k/NobiRackBot

Final integration branch: `integration/final-submission`

## Demo

https://Nobirack.nobitv.online
