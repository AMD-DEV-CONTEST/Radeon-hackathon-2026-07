# ML/AI Expansion Study — NuclidePath

**Date:** 22 July 2026
**Authors:** Stefano Rigante + Hermes Agent
**Purpose:** Document brainstorming on ML/AI integration for NuclidePath v0.5+ on AMD hardware

**Status key:** **Implemented** means present in the repository; **Measured** means backed by a reproducible project benchmark; **Planned** means proposed work; **Research-only** means feasibility is unverified. This study contains roadmap ideas, not claims that the proposed ML stack currently runs on ROCm. In particular, PyMC-on-ROCm is not established here; custom PyTorch HMC or another validated backend would need separate implementation and testing.

---

## Context

The Bradbury & Baeyens (2000) paper — *A Generic Sorption Model for the Simultaneous Sorption/Desorption of Trace Ratios of Cationic Radionuclides by Argillaceous Media*, J. Contaminant Hydrology 42, 141–163 — provides a rigorous cation exchange model with three site types (Frayed Edge Sites, Type-II Sites, Planar Sites), selectivity coefficients Kc for multiple radionuclide/competitor pairs, and site capacity distributions as fractions of illite CEC (~22 meq/100g).

This gives NuclidePath a genuine scientific foundation beyond a single Kd parameter.

---

## Expansion Direction 1 — GCS Surrogate Model

### What
A small neural network (MLP with Fourier Feature encoding) learns to approximate the GCS NumPy solver input→output mapping:

```
Input:  [K+], [Na+], [Ca2+], [Mg2+], [NH4+], %illite, pH, T, radionuclide_id
Output: Kd_eff, retardation R, G_sorbed
```

### Why AMD hardware matters
- Training: 50k–200k GCS evaluations. Each GCS solve is O(1) but 200k serial evaluations is slow on CPU.
- GPU parallelization: all 200k evaluations are independent → batched GPU computation.
- Inference speedup: **planned benchmark; no multiplier or real-time claim** until measured against the NumPy solver.
- ROCm + PyTorch: native support on AMD hardware already available.

### Training pipeline
1. Generate sparse training set with Latin Hypercube sampling over parameter space.
2. Ground truth = GCS NumPy solver output (deterministic, verified).
3. Validate surrogate against analytical limits (e.g., Kd_eff → Kd_base as [competitor] → 0).
4. If surrogate diverges beyond tolerance → deterministic fallback to NumPy GCS.

### Architecture
```
FourierFeatureMLP(input_dim=9, hidden=[256,128,64,32], output=3)
- Fourier features encode non-linear ion competition behavior
- Conservative: small enough to run on AMD GPU with room for other agents
```

### Validation checkpoints
- Charge balance: sum(q_i * Kc) = CEC (surrogate must respect same constraint as GCS)
- Bradbury 2000 reference values at known ion concentrations
- Limiting behavior at zero competitor, saturating competitor

---

## Expansion Direction 2 — GCS Parameter Extraction from Literature

### What
Automated extraction of GCS parameters from scientific papers (Bradbury 2000 first, then others).

### Bradbury 2000 contains
| Data type | Content |
|---|---|
| Selectivity coefficients Kc | Cs/K, Sr/Ca, Am/Na on FES, Type-II, Planar sites |
| Site capacities | %FES, %Type-II, %Planar as fraction of illite CEC |
| CEC reference | ~22 meq/100g for illite |
| Temperature corrections | Kc as function of T |
| Validation cases | 4 argillaceous rocks (Opalinus Clay, MUri, Boda, KFM01) |

### Extraction pipeline
```
PDF stream → zlib decompress → regex parse → semantic assignment → JSON
```

### Output schema
```json
{
  "source": "Bradbury & Baeyens 2000",
  "selectivity_coefficients": {
    "Cs_K": {
      "FES": {"value": 47.0, "unit": "dimensionless"},
      "Type_II": {"value": 2.3, "unit": "dimensionless"},
      "Planar": {"value": 0.09, "unit": "dimensionless"}
    }
  },
  "site_capacities": {
    "FES": {"value": 0.009, "unit": "mol/kg"},
    "Type_II": {"value": 0.09, "unit": "mol/kg"},
    "Planar": {"value": 0.90, "unit": "mol/kg"}
  },
  "cec_illite": {"value": 22.0, "unit": "meq/100g"},
  "validation_rocks": ["Opalinus Clay", "MUri", "Boda", "KFM01"]
}
```

---

## Expansion Direction 3 — Multi-Isotope, Multi-Competitor Extension

### Radionuclides with GCS-applicable data
| Radionuclide | Half-life | Main competitor | GCS status |
|---|---|---|---|
| Cs-137 | 30.1 yr | K+, NH4+ | Implemented |
| Sr-90 | 28.8 yr | Ca2+, Mg2+ | Kc available in Bradbury |
| Am-241 | 432 yr | Na+, Ca2+ | Partial data |
| Eu-152 | 13.5 yr | Ca2+, Mg2+ | Limited data |

Recommended near-term: Cs-137 + Sr-90 (both have Bradbury Kc data, most relevant for groundwater contamination).

### Competing ion hierarchy
```
K+  : 1-50 mg/L      Cs competitor - IMPLEMENTED
Na+ : 10-500 mg/L    Cs competitor in primary GCS - IMPLEMENTED
Ca2+: 20-400 mg/L    retained chemistry; mechanistic Sr competition - FUTURE RESEARCH
Mg2+: 5-100 mg/L     retained chemistry; mechanistic Sr competition - FUTURE RESEARCH
NH4+: 0.1-50 mg/L   FES competitor in primary GCS - IMPLEMENTED
```

### Illite% scaling
```
CEC_eff = CEC_illite x f_illite + CEC_other x (1 - f_illite)
R_eff   = 1 + (rho_b / theta) x (CEC_eff / CEC_illite) x Kd_eff_illite

When f_illite = 1 --> R = R_illite (Bradbury reference case)
When f_illite = 0 --> R = 1 (sand, no retardation)
```

---

## Open Questions

1. Surrogate architecture: Fourier Feature MLP vs standard MLP - is the extra complexity justified by the competition non-linearities?
2. Training data: How many GCS evaluations needed for a reliable surrogate? Is 50k enough or is 200k necessary?
3. Bradbury data quality: Kc values have measurement uncertainty. Should the surrogate encode this as aleatoric uncertainty?
4. Sr-90 integration: Does the GCS system for Sr-90 + Ca2+ share the same three-site structure, or does it need a different site model?
5. Illite% validation: Is the linear CEC scaling approach physically sound, or does illite% affect Kc values themselves?

---

## References

- Bradbury, M.H. & Baeyens, B. (2000). A Generic Sorption Model for the Simultaneous Sorption/Desorption of Trace Ratios of Cationic Radionuclides by Argillaceous Media. J. Contaminant Hydrology, 42, 141-163.
- NuclidePath transport-prototype-0.3: reactive Ogata-Banks solution with K+/Cs+ competition.
