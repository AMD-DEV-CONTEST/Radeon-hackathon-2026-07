# Project license decision record

Decision date: 2026-07-29  
Status: **OWNER DECISION RECORDED — Apache-2.0**  
Scope: original source code and documentation in the public Mantis Track 3
submission

## Owner decision

The project owner selected **Apache License 2.0** for original project source
and documentation. The copyright holder is **Blueworm**, copyright year
**2026**, decision date **2026-07-29**. The owner communicated this selection
during the active project session on 2026-07-29.

- Selected license: `Apache-2.0`
- Copyright holder name: `Blueworm`
- Copyright year: `2026`
- Decision date: `2026-07-29`
- Decision evidence: owner-stated in the active project session on 2026-07-29

The exact canonical Apache License 2.0 text is stored as the root `LICENSE`,
byte-for-byte equal to the plaintext published by the Apache Software Foundation
(SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`,
11358 bytes). No custom header, signature, or project-specific notice was
prepended, appended, or inserted into the canonical license body. The copyright
holder is recorded in this decision and in the user-facing license sections of
`README.md` and `submission/`, not inside the canonical `LICENSE`.

## Scope of the grant

This license applies **only** to original project source code and documentation
that Blueworm has the right to license. It grants rights in that original project
material under Apache-2.0 terms.

## Externalization boundary (preserved)

This decision does **not** license, relicense, or authorize redistribution of
any third-party material. It does not cover and does not convey rights in:

- the Mantis URDF or meshes, or any derived materialization;
- private adapter source;
- the RoboTwin bowl asset (`002_bowl` model 3) and other RoboTwin assets;
- Genesis;
- LeRobot;
- datasets, trained checkpoints, or other third-party material.

Those rights remain governed separately by `third_party/ASSET_LICENSES.md`. In
particular, no redistributable Mantis asset license has been established and no
Mantis owner authorization has been received; Mantis remains an external,
hash-pinned dependency. This record broadens no third-party right and authorizes
no third-party redistribution.

## Practical options considered

| Option | Practical effect | Main consideration |
|---|---|---|
| MIT | Short permissive license; permits reuse, modification, and commercial distribution with attribution and license retention | Does not include an express patent grant |
| Apache-2.0 (selected) | Permissive license with express patent terms and contribution conditions | Longer notice/compliance text |
| Another owner-selected license | Uses terms chosen by the owner | Requires a separate compatibility and publication review |

This table is operational guidance, not legal advice.

## Claim boundary

This record applies the owner-selected project license to original project
material. It is not a clean-room reproduction, a public release, a submitted
pull request, competition acceptance, a G3 pass, or third-party authorization.
The owner decision resolves the project LICENSE promotion blocker: an
independent release-mode packaging build has reached `COMPLETE_RELEASE` as a
local packaging gate (246 allowlisted files, zero content findings, zero
promotion findings, 12/12 local Markdown links resolved, 163 inventoried
provenance paths). That packaging gate does not by itself produce a public
release; the generated release-mode publication audit and the external terminal
receipt are owned separately and not predicted here. This record provides no
legal advice.
