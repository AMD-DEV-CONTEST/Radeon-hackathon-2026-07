# Mantis asset authorization request

Status: **draft for project-owner review — not sent; no authorization implied or granted**
Prepared: 2026-07-27 (repository identity corrected 2026-07-27)
Work package: WP-LIC-001
Authority: `third_party/ASSET_LICENSES.md`, `configs/mantis-port-config.json`,
`docs/G3_FAILURE_ATTRIBUTION_SUBMISSION_SPRINT.md`,
`receipts/asset-license-public-audit-20260727-v2/README.md` (current
repository-identity authority; the immutable v1 receipt is superseded for
identity only),
independent read-only `git ls-remote` corroboration performed 2026-07-27.

Current narrow exception: rendered Mantis visuals are user-permitted only in
the demonstration video. This is not an asset-owner grant, a general license,
or a redistribution right. Raw Mantis URDF, meshes, source assets, derived raw
asset files, materializations, and asset payloads remain excluded.

## Purpose

This document converts the dated public-source license audit of the Mantis
robot asset into a concise, user-reviewable permission request and a
submission-safe fallback boundary. It is **not** legal advice, **does not**
invent or assume a license identifier, and **does not** assert that any
permission has been received. It prepares a request; it grants nothing.

Until the asset owner responds in writing, the public submission stays on the
**fallback boundary** in §3, under which no Mantis URDF, mesh, or derived
materialization is redistributed.

## 1. Subject assets and current public licensing state

Repository identity below is corroborated by an independent read-only
`git ls-remote` performed 2026-07-27 (see §1.1, §1.2). The dated audit
`receipts/asset-license-public-audit-20260726-v1/README.md` recorded an
**invalid** revision for `mantis_description` (it conflates another repository's
revision — see §1.1); that immutable receipt is therefore **superseded for
repository identity** by
`receipts/asset-license-public-audit-20260727-v2/README.md`. It is not edited.
Its license-absence conclusion is independently corroborated by the
2026-07-23 audit recorded in `configs/mantis-port-config.json`
(`assets.license_audit`) for the verified revision. None of these observations
grant redistribution rights.

### 1.1 `BlueWorm-EAI-Tech/mantis_description` — primary subject

- Repository: `https://github.com/BlueWorm-EAI-Tech/mantis_description`
- Default branch: `main`
- Verified head revision (`git ls-remote HEAD` and `refs/heads/main`,
  2026-07-27, both identical):
  `b1e154e274fa7cfa8ecdeb10e85145d0c998382e`
- Defective v1-audit value (invalid for this repository):
  `b1e154e274fa7cfa1689904cc986ae9e09c1d35b`. Its suffix
  `1689904cc986ae9e09c1d35b` matches the unrelated `lerobot_mantis_server`
  historical revision (§1.2) and is not a commit on `mantis_description`; the
  v1 receipt is superseded for repository identity by the additive v2
  correction.
- Head commit timestamp: pending re-verification under the v2 correction (the v1
  value `2025-07-07T09:04:05Z` was recorded against the invalid revision).
- GitHub repository `license` field: `null`; no root `LICENSE`, `LICENSE.md`,
  or `COPYING` present (v1; repo-level metadata).
- `package.xml` license text: `TODO: License declaration` — corroborated by the
  independent 2026-07-23 audit in `configs/mantis-port-config.json`
  (`root_license_present: false`, `package_xml_license_text:
  "TODO: License declaration"`) for the verified revision.
- `package.xml` SHA-256
  `591972824b141810ca0fc9f49636707f066ffcec6deb1a06e3bfa8ac41c0efc5`: recorded
  only in the v1 receipt against the invalid revision; pending re-verification
  under the v2 correction.

Licensing conclusion: no redistributable license is detectable on the public
tree (independently corroborated for the verified revision). Redistribution of
the URDF or meshes requires explicit written authorization from the repository
owner. The verified head matches the revision the fixed-base plan was executed
against (`docs/FIXED_BASE_ASSET.md`).

### 1.2 `BlueWorm-EAI-Tech/lerobot_mantis_server` — related subject

- Expected public URL:
  `https://github.com/BlueWorm-EAI-Tech/lerobot_mantis_server`
- Anonymous/public web-page and GitHub-API status (2026-07-26, unchanged):
  HTTP 404 / `Not Found`.
- Configured git transport in this environment resolves the historical revision
  `53953bc9b3c63dfa1689904cc986ae9e09c1d35b` via `git ls-remote`. This is
  **not** public availability and **not** a license grant: the anonymous public
  page remains 404 and no license is published. Reachability through configured
  transport is not used to infer any redistribution right.
- Historical local contract revision (provenance only):
  `53953bc9b3c63dfa1689904cc986ae9e09c1d35b`.

Licensing conclusion: the adapter repository is not established as public or
redistributable. Its frozen semantic interface contract is retained as
provenance only; its source is not vendored. It is not requested for
redistribution in this package; only a publication-status clarification is
requested (§2.6).

## 2. Requested rights

The rights below are **requested**, not assumed. Each is scoped to the Track 3
competition submission described in `submission/README.md` and is conditional on
the asset owner's written grant. For each right the intended use and the
fallback that applies if it is **not** granted are stated.

### 2.1 Source publication

- Requested right: permission to commit the `mantis_description` URDF and mesh
  files into the public competition repository.
- Intended use: make the submission self-contained and reproducible without a
  private download step.
- Fallback if not granted: the URDF and meshes stay out of the repository;
  reproduction uses the external hash-pinned materialization procedure (§3).

### 2.2 Docker image and runtime materialization

- Requested right: permission to embed the Mantis asset (URDF, meshes, and/or a
  derived materialization) inside the published Docker image and to materialize
  it at runtime during a clean-room reproduction.
- Intended use: let the ROCm container and Genesis runtime load the robot
  without an external fetch.
- Fallback if not granted: the Docker image excludes all Mantis payloads; the
  runtime fetches the asset via the external hash-pinned procedure after an
  explicit local-use acknowledgement.

### 2.3 Derived fixed-base URDF

- Requested right: permission to redistribute the derived fixed-base bimanual
  URDF and its copied/rewritten meshes produced by the read-only plan in
  `configs/fixed-base-plan.json` (profile `mantis_fixed_base_bimanual_v1`,
  19 links / 18 actuated joints; see `docs/FIXED_BASE_ASSET.md`).
- Intended use: ship the exact stationary-manipulation topology the policy was
  trained and evaluated against.
- Fallback if not granted: the derived URDF and meshes remain local-only
  (`distribution_allowed: false`); the submission ships the plan and
  materialization procedure, not their output.

### 2.4 Screenshots

- Requested right: permission to include rendered still images of the Mantis
  robot (simulation frames) in the technical report and submission materials.
- Intended use: illustrate the robot, scene, and task in the written
  deliverables.
- Fallback if not granted: screenshots are replaced with independently authored
  diagrams, text descriptions, or non-Mantis imagery.

### 2.5 Demonstration video

- Requested right: permission to include video footage of the Mantis robot in
  future uses beyond the current narrow demonstration-video permission.
- Intended use: establish explicit owner terms for broader or reusable footage
  rights. The current submission may show rendered Mantis visuals only in its
  demonstration video under the separate user permission recorded above.
- Boundary until granted: the current rendered-video exception does not permit
  raw or derived asset redistribution and does not establish a general license.

### 2.6 Related clarification — adapter publication status

- Requested item: a written statement of the current publication and licensing
  status of `BlueWorm-EAI-Tech/lerobot_mantis_server` (anonymous public page
  404; configured transport resolves the historical revision but grants
  nothing).
- Intended use: confirm whether the historical interface-contract provenance may
  be cited by URL, or whether it must be described only by its frozen local
  revision hash.
- Fallback if not granted: the adapter is referenced only by its historical
  revision hash `53953bc9b3c63dfa1689904cc986ae9e09c1d35b`; no public URL is
  claimed and no source is vendored.

## 3. Submission-safe fallback boundary (active until authorization is received)

No authorization has been received. The submission therefore remains on the
fallback boundary recorded in `submission/README.md` (consistent with the v1
audit's boundary section, whose repository-identity defect does not affect the
include/exclude lists below).

Included without Mantis authorization:

- original project code, numeric contracts, tests, reports, and evidence;
- a hash-checked external download / materialization procedure for
  `mantis_description`;
- independently authored finger/tool overlay primitives authored from scratch
  under the project license, with no Mantis mesh reuse;
- the separately MIT-licensed RoboTwin bowl materialization, with its pinned
  attribution and license file;
- rendered Mantis visuals only in the demonstration video under the current
  narrow user permission, without any raw or derived asset payload.

Excluded without Mantis authorization:

- Mantis URDF and mesh payloads;
- derived fixed-base or rim-support materializations containing Mantis meshes;
- private Mantis adapter source;
- credentials, datasets, checkpoints, and private deployment code.

This boundary is preserved regardless of how any single right in §2 is answered:
a grant for one right (for example, screenshots) does not extend to another
(for example, source publication) unless explicitly stated.

## 4. Response requested from the asset owner

To move any item off the fallback path, the project needs a written response
from the `BlueWorm-EAI-Tech` owner that, for each item in §2, states one of
**granted**, **granted with conditions**, or **not granted**, and identifies the
license or permission terms. The owner may attach any license or permission
identifier of their own choosing; this request does not propose, assume, or
prefer any specific identifier.

## 5. Decision record

To be completed by the project owner when a response is received. An empty
`Status` means the right has not been granted and the §3 fallback governs.

| Item (§2) | Status | Conditions | Evidence reference |
|---|---|---|---|
| 2.1 Source publication | _pending_ | — | — |
| 2.2 Docker / materialization | _pending_ | — | — |
| 2.3 Derived fixed-base URDF | _pending_ | — | — |
| 2.4 Screenshots | _pending_ | — | — |
| 2.5 Demonstration video | _pending_ | — | — |
| 2.6 Adapter publication status | _pending_ | — | — |

## Claim boundary

This document prepares a permission request and a distribution fallback. It
does not grant rights, establish that permission has been received, constitute
legal advice, or commit the asset owner to any position. Repository identity is
corroborated by read-only `git ls-remote` (2026-07-27); the additive v2
receipt supersedes v1 for repository identity only.
Until §5 records a written owner grant for a specific item, the fallback
boundary in §3 governs that item. The separate narrow user permission for
rendered demonstration-video visuals neither fills the pending owner-grant row
nor broadens the raw-asset boundary.
