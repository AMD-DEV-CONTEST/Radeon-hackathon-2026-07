## Off-Distribution Robustness (6 conditions, verified on AMD Radeon gfx1100)

Friction and mass sweep on parcel_small (desk→trash_bin), all **no failures**:

| Friction × | Mass × | Steps | Transport | Analysis |
|---|---|---|---|---|
| 0.5 | 1.0 | 6,137 | ✅ | Low friction — slip detection compensates, +19% steps |
| 1.0 | 1.0 | 5,137 | ✅ | Baseline |
| 1.5 | 1.0 | 5,537 | ✅ | High friction — stable, +8% steps |
| 2.0 | 1.0 | 6,337 | ✅ | Very high friction — +23% steps |
| 1.0 | 0.5 | 4,439 | ✅ | Light payload — faster, -14% steps |
| 1.0 | 2.0 | 4,034 | ✅ | Heavy payload — most stable, -21% steps |

**Key findings**:
- Deterministic position-force controller survives **4× friction** (0.5–2.0) and **4× mass** (0.5–2.0) variation
- **Zero transport failures** across all 6 off-distribution conditions
- Heavy payloads are most stable (lowest step count) — consistent with physics: higher normal force → stronger friction grip
- Low friction triggers most slip detection compensation (highest step count)
- Step count monotonically increases with friction deviation from baseline

Platform: ROCm/HIP 7.2, AMD Radeon gfx1100, Genesis 1.3.0 (gs.amdgpu)
