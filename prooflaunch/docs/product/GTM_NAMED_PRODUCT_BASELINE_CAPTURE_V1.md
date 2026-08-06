# Named-product same-brief baseline capture V1

## Outcome

The 130 product rows are executable capture slots rather than a list of names. Each slot binds one reference product to one frozen category brief, four immutable shared inputs, admitted output formats, a maximum byte size, product/model/version metadata, a named operator, three explicit rights/fidelity attestations, and the SHA-256 of the unchanged export.

Capturing a baseline is not a product win. It starts no review and cannot change a PK, 4A, publication, lift, or revenue verdict.

## Graph

1. Choose one of 13 category briefs and one of its 10 named products.
2. Run the frozen task with the exact shared inputs using an authorized account or an authorized public demo.
3. Preserve the original export without hidden post-editing.
4. Open the category capture page, record the observed product/model/version and named operator, attach the original export, complete the three attestations, and download the local receipt.
5. Import the receipt and artifact through the guarded CLI.
6. Only after a separate identity-hidden pair is compiled may five qualified humans review it.
7. Only a completed aggregate may be evaluated against the predeclared promotion thresholds.

## Loop boundary

The capture loop may repair missing metadata, wrong extension, size, timestamp, or digest. It may not edit the baseline output, change the frozen brief, fabricate authorization, select a winner, or substitute a model judge for qualified human review.

## Harness gates

- Every kit and capture object is content sealed.
- All four shared inputs and every page are hash inventoried.
- A slot accepts only its exact category, product URL, frozen-brief hash, extension, and byte ceiling.
- The original artifact name, size, and SHA-256 must match the receipt.
- All three rights/fidelity attestations and a named operator are mandatory.
- Imported slots are immutable; a different second capture fails closed.
- Import creates `authorized_baseline_present_review_not_started`, never `completed` or `winner`.
- Network submission, product automation, automatic pairing, publication, spend, and automatic PK promotion are disabled.

## Run it

Open `artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/index.html` or distribute the deterministic ZIP to an authorized operator.

```bash
PYTHONPATH=src .venv/bin/python -B scripts/import_gtm_named_product_baseline.py \
  --capture /path/to/pk-xxxxxxxxxxxxxxxx-capture.json \
  --artifact /path/to/original-product-export.json
```

The importer writes an immutable slot directory plus a sealed `registry.json` under `artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/`.

## Current evidence state

- Frozen category briefs: 13/13.
- Independent named-product capture slots: 130/130.
- Authorized named-product baselines imported: 0/130.
- Named-product blind reviews submitted: 0.
- Completed named-product PK rows: 0/130.
- Effect-aligned categories: 0/13.

This is an execution-ready evidence intake, not evidence that the candidate has surpassed any named product.
