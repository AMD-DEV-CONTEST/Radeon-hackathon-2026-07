# Baseline v1 readiness

Freeze baseline v1 only after all required items are real and recorded:

- [ ] At least one fixture runs input → canonical asset → rendered output.
- [ ] Core generation is served on W7900 through ROCm/vLLM.
- [ ] Model repository, immutable revision, license, dtype/quantization,
      context/output limits, vLLM arguments, and code commit are recorded.
- [ ] Warm-up and repeated measured runs are retained, including failures.
- [ ] The canonical asset passes artifact mode.
- [ ] The performance manifest passes `validate_manifest.py`.
- [ ] Server, Agent task, and refinement UX results are stored separately.
- [ ] R0 proof includes `amd-smi`, `rocminfo`, PyTorch HIP/device, and vLLM
      startup/configuration evidence.

The first baseline may be slow or imperfect. It must be complete, reproducible,
and immutable. Create v2 rather than editing v1 after a material workflow or
contract change.
