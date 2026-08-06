# AMD Track 1 Public Release Policy

This working directory is not the public submission repository. It contains
private runtime state, transfer archives, research workbenches, and evidence
that must not be published by default.

## Public identity

- Team: Banyan
- Application: ProofLaunch
- GitHub submitter: `sylvanccc`
- Official repository destination: `prooflaunch/`
- Pull request title: `Track 1, Banyan, ProofLaunch: Multimodal GTM Studio`
- Submission language: English

## Required public surface

The competition export must contain the complete source required to reproduce
every capability shown in the demo, together with the English environment,
startup, dependency, and verification instructions. It must also contain the
required Project Profile PDF, Demo Video link or file, and Poster/PPT.

## Never publish

- `.prooflaunch-secrets/`
- `.prooflaunch-runtime/`
- `.super-site-10x/`
- `.venv/`, caches, and temporary directories
- provider credentials, cookies, tokens, invitations, or private URLs
- customer data, private teacher outputs, or unlicensed media
- generated transfer archives in `dist/`

## Pre-publication gates

1. Export from an explicit allowlist to `prooflaunch/`; never push this working directory.
2. Scan the export for secrets, personal data, private paths, and non-English
   submission descriptions.
3. Verify every linked file exists in the exported tree.
4. Reproduce the evaluator workflow from a clean environment.
5. Confirm the included Demo Video and independently confirm the live AMD
   Radeon inference receipt before making any completed-hardware claim.
6. Open the official pull request only while the final exported bytes and
   claims match the evidence manifest.

Build and validate the exact public tree with:

```bash
python scripts/build_amd_public_export.py
python scripts/validate_amd_public_export.py dist/amd-track1/prooflaunch
```

Project code is released under the repository's MIT license. That license does
not relicense model weights, datasets, fonts, images, audio, or video; every
non-code asset must retain its own reviewed rights record before export.
