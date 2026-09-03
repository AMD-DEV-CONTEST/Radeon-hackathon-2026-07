# Third-party Asset Register

| Component | Revision | Intended use | License status | Distribution status |
|---|---|---|---|---|
| `BlueWorm-EAI-Tech/lerobot_mantis_server` | historical local audit at `53953bc9b3c63dfa1689904cc986ae9e09c1d35b` | Contract reference and potential adapter upstream | Historical checkout metadata recorded Apache-2.0; the anonymous public GitHub page and API return 404 (2026-07-26, unchanged). Configured git transport in this environment resolves the historical revision via `git ls-remote`, but that is not public availability or a license; do not vendor or claim redistribution without owner confirmation | Not vendored |
| `BlueWorm-EAI-Tech/mantis_description` | `b1e154e274fa7cfa8ecdeb10e85145d0c998382e` (verified `git ls-remote` `HEAD` and `refs/heads/main`, 2026-07-27) | Candidate URDF and meshes | No detected license, no root license, `package.xml` says `TODO: License declaration` (corroborated by the 2026-07-23 audit in `configs/mantis-port-config.json` for this revision); explicit owner authorization required. The v1 receipt's recorded revision `b1e154e274fa7cfa1689904cc986ae9e09c1d35b` is invalid for this repository and is superseded for identity by `receipts/asset-license-public-audit-20260727-v2/README.md` | Not vendored; hash-checked external dependency only |
| `wangxunx/franka_fruit_pick_demo` | Pin before use | Architectural reference only | No root license observed during audit | No code or assets copied |
| `TianxingChen/RoboTwin2.0` `objects.zip` / `002_bowl` model 3 | `b5230d8b4c348769f0c2402b73c88852f093b011` | Three-bowl task visual/collision asset | Dataset card declares MIT; preserve Tianxing Chen attribution and exact source hashes | Not vendored in the public candidate; the hash-checked materialization procedure is published. If payloads are later bundled, the verified MIT text and attribution must accompany them |

## Authorization path and evidence

Repository identity for the two `BlueWorm-EAI-Tech` rows is corroborated by an
independent read-only `git ls-remote` performed 2026-07-27. The current
repository-identity authority is
`receipts/asset-license-public-audit-20260727-v2/README.md`. The dated v1 audit
`receipts/asset-license-public-audit-20260726-v1/README.md` is **superseded for
repository identity** because it recorded an invalid `mantis_description`
revision. That receipt is immutable and is not edited. The v1
license-absence conclusion is
independently corroborated by the 2026-07-23 audit in
`configs/mantis-port-config.json` and remains valid. None of these observations
are grants or establish any license.

A draft owner-permission request covering source publication, Docker/runtime
materialization, the derived fixed-base URDF, screenshots, and broader video
rights is staged at `docs/MANTIS_ASSET_AUTHORIZATION_REQUEST.md`. It has not
been sent, grants nothing, and assumes no license identifier. Separately,
rendered Mantis visuals are user-permitted only in the demonstration video;
this is not an asset-owner grant, a general license, or a redistribution right.
Raw Mantis URDF, meshes, source assets, derived raw asset files,
materializations, and asset payloads remain not vendored and externalized.

The project itself also needs an explicit license selected by its owner before
public submission. The bounded decision record is
`docs/PROJECT_LICENSE_DECISION.md`; it cannot relicense any component in this
register.
