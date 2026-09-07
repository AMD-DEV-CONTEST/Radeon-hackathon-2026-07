# Third-simulator triangulation (Escalation 4) — not attempted, and why

Full-scale escalation brief (session 8), Escalation 4: add Isaac Sim / Isaac Lab
(PhysX) as a third, architecturally distinct physics backend, to triangulate the
cross-simulator direction-reversal found between Genesis and MuJoCo
(`cross_simulator_findings.md`).

**Status: not attempted. Confirmed infeasible on available hardware, not merely
deprioritized.**

Isaac Sim requires an NVIDIA GPU (RTX-class, for its PhysX GPU pipeline and
Omniverse rendering stack) — this is a hard dependency, not a performance
consideration. Checked directly on this machine before any engineering work
started:

```
$ which nvidia-smi
no matches found
$ ls /dev/nvidia*
no matches found
```

No `nvidia-smi`, no `/dev/nvidia*` device nodes. This machine's GPU is an AMD
Radeon iGPU (paired with an AMD Ryzen 7 5825U CPU) — the same machine Genesis
has been running on CPU-only throughout this project (`backend gs.cpu`, per
every prior session's logs). Isaac Sim does not run on AMD hardware; there is no
degraded or CPU-fallback mode that would make this merely slow rather than
impossible.

Session 4's ROCm/AMD GPU benchmarking used a *separate* remote Radeon Cloud
instance reached over SSH — a different machine from this one, provisioned
specifically for that purpose. Isaac Sim triangulation would need an equivalent
separate, NVIDIA-capable machine; none was available to this session, and per
project direction (asked explicitly this session) this escalation is being
skipped rather than pursued via a new remote-access request.

**What this means for the cross-simulator finding**: the triangulation in
`cross_simulator_findings.md` remains two-way (Genesis vs. MuJoCo), not
three-way. The reversal found there, and the confirmed shared friction-
sensitivity from the follow-up diagnostic, stand as reported — this gap doesn't
change either of those results, it just means a "2-of-3 engines agree" signal
was never obtainable here and should not be implied anywhere in the writeup.
If a third-engine check becomes valuable enough to pursue later, it needs
either a provisioned NVIDIA-capable remote machine or a different third engine
that runs on this hardware (e.g. Bullet/PyBullet, or Brax on CPU) — noted here
as a flagged follow-up, not pursued in this session per the brief's own
instruction not to open new instrumentation threads mid-escalation.
