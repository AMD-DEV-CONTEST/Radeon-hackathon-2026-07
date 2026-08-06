# Manual publication receipt V1

## Outcome

ProofLaunch can now record which approved candidate asset a named operator
manually published, on which approved channel, at which public HTTPS URL, and
with which exact experiment attribution tags. The record is append-only and
hash-chained to the delivered run. ProofLaunch still has no external publishing,
sending, or spending authority.

This closes the traceability gap between a delivered Campaign Workspace and the
aggregate production-observation contract. It does **not** prove that a platform
served the post, that the audience saw it, that assignment was randomized, or
that the asset caused an effect.

## Preconditions

1. The run is `delivered` internally (`bundle_ready` in the store).
2. A named human approved the immutable release preview.
3. The candidate asset bytes come from the delivered ZIP. Calculate the SHA-256
   of the exact JSON member used, such as `channel-copy.json`.
4. The public URL contains every candidate tag from
   `attribution-plan.json` in the production observation field kit. Duplicate,
   missing, or drifted tags are rejected.
5. A local SHA-256 is calculated for either an official platform receipt export
   or an operator-attestation file. The source file itself is not uploaded.

## Accepted payload

```json
{
  "receipt_id": "pub-unique-id",
  "channel": "short_video_organic",
  "asset_name": "channel-copy.json",
  "asset_sha256": "64-lowercase-hex",
  "public_url": "https://public.example/post?...exact candidate tags...",
  "published_at": "2026-08-02T15:00:00-04:00",
  "source_kind": "operator_attestation",
  "source_reference_sha256": "64-lowercase-hex",
  "operator_attested": true
}
```

`source_kind` is either `official_platform_receipt` or
`operator_attestation`. Even the former remains a hashed source reference; the
server reports `platform_delivery_verified=false` until an independent platform
verification mechanism exists.

## API and browser

- `POST /v1/runs/{run_id}/publication-receipts` requires the tenant bearer and
  the local operator approval token. `Idempotency-Key` should equal
  `receipt_id`.
- `GET /v1/runs/{run_id}/publication-receipts` returns the tenant-bound
  collection.
- Experiment Lab exposes **Record publication receipt**, which loads a local
  JSON file and submits it after explicit operator authentication.

The API derives campaign, experiment, strategy, attribution-plan, operator, and
approved-asset identities server-side. Client attempts to replace those
identities have no authority. Private/loopback URLs, URL credentials, fragments,
unapproved channel IDs, unknown asset names, asset hash drift, naive timestamps,
missing attribution tags, and reused receipt IDs with different evidence fail
closed.

## Evidence boundary

The receipt asserts only that the authenticated operator supplied a bounded
attestation tied to a public URL and a hash of the supporting source. It records:

- `publication_performed_by_prooflaunch=false`
- `platform_delivery_verified=false`
- `credentials_persisted=false`
- `effect_claim_eligible=false`
- `causal_revenue_claim_eligible=false`

Real effect still requires the separate aggregate outcome and economics
contracts. A baseline is not allowed to masquerade as a ProofLaunch-approved
candidate asset; external control provenance remains a separate experiment
responsibility.
