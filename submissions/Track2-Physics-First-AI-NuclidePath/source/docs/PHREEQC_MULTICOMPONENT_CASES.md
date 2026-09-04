# PHREEQC multicomponent cases

## Purpose

This increment removes the bridge's accidental `K+`/`Cs+` output limitation.
The PHREEQC projection now accepts `Cs` plus any explicitly declared subset of
`K`, `Na`, `Ca`, and `Mg`. The selected-output contract, parser, and diagnostics
are generated from that set, so a case with no potassium is valid and remains
fully inspectable.

The merged bridge passed final integration CI in run
`30928408962` (364 passed, 15 skipped), including the dependency-light suite,
workflow policy, compilation, wheel and whitespace checks. It was also executed
locally against the pinned PHREEQC release and database recorded in [the
scenario compiler evidence](PHREEQC_SCENARIO_COMPILER.md). Both cases exited
successfully, produced the closed parser schema, passed the independent oracle,
and yielded verified replay bundles. The trusted manual PHREEQC workflow on
`refs/heads/main` remains a separate publication gate; these runs are
process/integration evidence, not calibrated solver results.

The canonical NuclidePath screening model is unchanged. Its empirical
`Kd_eff` correction is still the legacy K-only path until a multi-cation
parameterization is calibrated and compared with experimental data. The
separate arithmetic oracle verifies the declared bridge contract but does not
calibrate the chemistry.

The non-runner calibration/hold-out gate merged in PR #22 provides the missing
software contract for that next step: traceable observations, explicit units,
group-disjoint fitting/hold-out, quantitative metrics and fail-closed promotion.
It remains unpromoted because no authorized experimental dataset is bundled.

## Case set

The two JSON cases are paired projections of the Central Oklahoma aquifer
example published in the official PHREEQC documentation:

| Case | Water composition | Competitors | Role |
|---|---|---|---|
| `central_oklahoma_brine_multicomponent.json` | Initial brine: Ca, Mg, Na, Cl, C, S | Na+, Ca2+, Mg2+ | K-free high-ionic-strength stress case |
| `central_oklahoma_recharge_multicomponent.json` | Recharge solution: Ca, Mg, Na, Cl, C, S | Na+, Ca2+, Mg2+ | K-free dilute recharge case |

The brine values are transcribed from the Example 14 `SOLUTION 1` block,
where they are given in mol/kgw, and converted to mmol/kgw for the scenario
contract. The recharge values are transcribed from the Example 14 `SOLUTION 0`
block, where the input unit is already mmol/kgw. The Example 14 water types
are real hydrogeochemical contexts described from the Central Oklahoma aquifer;
the Cs-137 source, 1-D transport geometry, and pairing with the NuclidePath
bridge are explicitly demonstration projections.

The PHREEQC database-convention values used for Na/Ca/Mg are recorded as
provenance-bearing inputs. `Cs: log_k=1.2` is deliberately labelled a
demonstration placeholder: it must be replaced or calibrated with Cs
multi-cation data before a scientific claim is made. This is consistent with
the published evidence that Cs exchange can involve Ca2+, Mg2+, and K+ and
that the relative response depends on the mineral structure and conditioning.

## Generated contract

For a K-free case, the compiler emits:

```text
-totals     Cs Na Ca Mg
-molalities Cs+ Na+ Ca+2 Mg+2 CsX NaX CaX2 MgX2
```

PHREEQC writes the raw molality header with an `m_` prefix (for example,
`m_Cs+`). The parser strips that prefix only for species declared by the
compiler and rejects every other unexpected column.

`-totals` are solution totals. The aqueous and exchange species are selected
separately. Diagnostics report, for every declared ion:

- solution total, aqueous amount, and exchange amount;
- solution-total residual;
- exchange charge equivalents;
- fraction of the available exchange capacity occupied.

For Cs, the report additionally derives the displayed dissolved/exchange
partition, apparent exchange `Kd`, apparent retardation, and the side-by-side
comparison with the legacy empirical path when that path is present. The
independent numerical oracle also checks total exchange-site occupancy, including
charge equivalents for Ca and Mg, before the evidence is returned.

## Scientific boundary

These cases are useful real-composition integration tests, not validated Cs
transport predictions. The repository still reports `PROCESS-QUALIFIED ONLY`:

- PHREEQC execution, bounded outputs, closed selected-output parsing and replay integrity can be verified;
- the pinned local runs for both cases are recorded in the scenario compiler evidence;
- the declared unit/mapping/occupancy contract is `NUMERICALLY VERIFIED` by an
  independent arithmetic oracle;
- water compositions have an external source;
- Cs selectivity and CEC mapping still require calibration and applicability
  review;
- no PHREEQC result replaces the canonical K-only screening result;
- no regulatory, dose, operational, or site-safety conclusion is produced.

## Sources

- USGS PHREEQC Example 14 — Central Oklahoma aquifer, cation exchange and
  advective transport: <https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-76.htm>
- USGS `EXCHANGE_SPECIES` documentation and Gaines–Thomas convention:
  <https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-16.htm>
- USGS `SELECTED_OUTPUT` documentation:
  <https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-45.htm>
- Dubus, Leonhardt & Latrille, *Multi-cation exchanges involved in cesium
  and potassium sorption mechanisms on vermiculite and micaceous structures*,
  DOI: <https://doi.org/10.1007/s11356-022-22321-4>
