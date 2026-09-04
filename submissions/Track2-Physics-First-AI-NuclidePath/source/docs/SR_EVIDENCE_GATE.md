# Sr-90 sorption evidence gate

## Status

NuclidePath does **not** yet implement a mechanistic Sr sorption model. The supported path remains a user-supplied, provenance-bearing linear Kd. This gate prevents reuse of the monovalent Cs GCS for divalent Sr.

## Evidence reviewed

1. Fuller, A.J. et al. (2016), *EXAFS Study of Sr Sorption to Illite, Goethite, Chlorite, and Mixed Sediment under Hyperalkaline Conditions*, Langmuir 32, 2937–2946, DOI `10.1021/acs.langmuir.5b04633`. The accepted manuscript was directly inspected. At moderate pH, Sr(II) sorption is predominantly outer-sphere exchange and decreases with increasing ionic strength/competition. Above approximately pH 12.5, inner-sphere SrOH+ complexes become important. The paper therefore rules out one universal exchange closure across circumneutral and hyperalkaline regimes.
2. Missana, T., García-Gutiérrez, M. & Alonso, U. (2008), *Sorption of strontium onto illite/smectite mixed clays*, Physics and Chemistry of the Earth 33, S156–S162, PII `S1474706508002635`. Discovery metadata and abstract were inspected; parameter extraction from full text remains pending. It identifies mineral mixture, pH, ionic strength and radionuclide concentration as required model context.
3. Wissocq, A. et al. (2018), *Application of the multi-site ion exchanger model to the sorption of Sr and Cs on natural clayey sandstone*, Applied Geochemistry. Discovery metadata indicates a mineral-mixture multi-site ion-exchange approach; full parameter-table verification remains pending.
4. IAEA-TECDOC-2095 (2025), *Distribution Coefficients for Soil, Freshwater and Marine Systems for Exposure Assessments*, DOI `10.61092/iaea.jitd-59bo`. Full text was retrieved. It supports Kd distributions for exposure screening and stresses conditioning on solid/liquid properties; it is not a mechanistic Sr/Ca/Mg parameter source by itself.

## Model eligibility requirements

A mechanistic Sr model may be implemented only after a versioned primary-source parameter record supplies:

- mineral phases and their CEC/site capacities;
- exchange convention and charge basis for Sr2+, Ca2+, Mg2+, Na+ and H+;
- selectivity coefficients with units/convention and uncertainty;
- pH and ionic-strength applicability;
- aqueous speciation assumptions, especially Sr2+ versus SrOH+;
- equilibrium/contact time and reversibility assumptions;
- independent measured isotherm or exchange-envelope points for validation.

## Required model hierarchy

```text
linear sourced Kd
  → circumneutral outer-sphere Sr/Ca/Mg/Na exchange
  → pH/activity-aware surface complexation
  → hyperalkaline inner-sphere/secondary-phase model
```

No level may silently replace the preceding one. Hyperalkaline behavior must not be extrapolated from circumneutral exchange coefficients.

## Current decision

- `linear_kd` with explicit source/classification: **eligible**.
- Cs Bradbury GCS applied to Sr-90: **rejected**.
- generic Sr/Ca/Mg coefficients inferred from search snippets: **rejected**.
- mechanistic Sr implementation: **blocked pending primary full-text parameter extraction and benchmark data**.

This is an evidence gate, not a completed Sr geochemical model.
