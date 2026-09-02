# Experiment Record Guide

## 1. Purpose

This guide defines how AlphaNoah A1 records environment audits and inference benchmarks so another reviewer can understand what was measured, reproduce the procedure, and separate evidence from interpretation.

Available templates:

- [AMD Ryzen AI Max+ 395 Environment Audit](AMD395_ENVIRONMENT_AUDIT_TEMPLATE.md)
- [ROCm Inference Benchmark](ROCM_INFERENCE_BENCHMARK_TEMPLATE.md)

The templates intentionally contain no machine result. A completed record must be created only after a real run.

## 2. Evidence Rules

Every experimental statement must be labeled as one of:

- **Observed**: directly emitted by a command, API, monitoring source, or timer.
- **Derived**: calculated from preserved observed values with the method stated.
- **Interpretation**: an explanation or hypothesis that may require more evidence.
- **Not measured**: unavailable or not collected; never replace this with zero.

Do not:

- fill a template from memory;
- copy values from another machine without identifying them as a separate source;
- omit failed runs;
- combine cold-start and warm-response results without separate labels;
- change the prompt, model, settings, or backend inside one sample population;
- present a documentation statement as measured evidence;
- round a value so aggressively that the underlying result cannot be reconstructed.

## 3. Record Identity

Give each completed record a stable ID:

```text
EXP-YYYYMMDD-<SHORT-NAME>-NN
```

Recommended completed-record filename:

```text
YYYYMMDD_<SHORT_NAME>_<SEQUENCE>.md
```

Record:

- operator and reviewer;
- local date, time, and time zone;
- non-identifying host alias;
- repository commit;
- hardware and software identity;
- model name, revision or digest, and quantization;
- prompt identifier and checksum;
- raw evidence location and checksum;
- redactions and their reasons.

If any benchmark-defining field changes, start a new record rather than editing the earlier environment into a different experiment.

## 4. Procedure

1. Copy the relevant template; do not overwrite the template.
2. Assign an experiment ID before collecting data.
3. Complete the environment section from the actual machine.
4. Freeze the prompt, model settings, backend, success criteria, run count, and metric sources.
5. Capture raw command output and per-run observations.
6. Record failures and unavailable metrics explicitly.
7. Calculate derived metrics from the preserved raw samples.
8. Add interpretation only after the observed and derived sections are complete.
9. Redact secrets and personal or confidential data without removing technical provenance.
10. Ask a second person to verify the calculations and release boundary.

## 5. Raw Evidence

Raw evidence should be append-only for the experiment. If a correction is needed:

- preserve the original;
- add the corrected value;
- state who made the correction, when, and why;
- update the checksum reference.

Raw logs do not belong in Git automatically. Before adding any evidence to the repository, check its size, confidentiality, personal paths, hostnames, network identifiers, model license, and data license. Store only sanitized evidence approved for release.

## 6. Benchmark Calculations

For every calculated metric:

- name the input sample population;
- state whether failures are included;
- preserve units;
- identify the calculation method and tool;
- record the unrounded value when reporting a rounded value.

For P95, record the library or percentile convention because small samples and interpolation methods can produce different values. Do not report P95 as a universal performance guarantee.

First-token latency requires a client-observed first-token event. If the selected API is non-streaming and exposes only a complete response, mark first-token latency as not measured.

## 7. Privacy, Security, and Data Licensing

Experiments may use only synthetic, non-confidential prompts and test records approved by Data License and Provenance.

Never record:

- API keys, tokens, `.env` content, or credentials;
- real customer, factory, employee, or asset data;
- confidential documents or real SOP text;
- private prompts;
- personal filesystem paths, device serial numbers, or public IP addresses unless specifically approved and necessary.

When a command output contains both necessary evidence and sensitive values, keep a private original outside Git, create a sanitized copy, and document the redaction.

## 8. Publication Checklist

- [ ] The record uses a real run and identifies the audited machine by a non-sensitive alias.
- [ ] The repository commit, model, prompt, settings, and versions are reproducible.
- [ ] Raw observations and derived metrics are distinguishable.
- [ ] Failed and timed-out runs are preserved.
- [ ] Average and P95 calculations are independently reproducible.
- [ ] GPU utilization and memory usage name the tool, units, and sampling method.
- [ ] No customer, factory, confidential, credential, or personal data is present.
- [ ] Model, data, and third-party licenses have been reviewed.
- [ ] Performance wording is limited to the recorded prototype environment.
- [ ] A human reviewer has approved the record for publication.
