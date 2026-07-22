# Third-Party Notices

SignalForge is an original software project that interoperates with third-party models, runtimes,
libraries, fonts, services, and public data sources. Those materials remain governed by their own
licenses and terms. A SignalForge source license does not replace, modify, or broaden any
third-party permission.

This notice describes the pinned direct components and external boundaries of the current release.
Package lockfiles preserve the complete transitive dependency identities. Consult each upstream
distribution for its authoritative license text and notices.

## Model

### Google Gemma 4 26B A4B Instruct QAT Q4_0 GGUF

- Upstream repository: <https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf>
- Model ID: `google/gemma-4-26B-A4B-it-qat-q4_0-gguf`
- Revision: `d1c082be9cf3c8a514acf63b8761f4b41935842e`
- Selected file: `gemma-4-26B_q4_0-it.gguf`
- Selected-file SHA-256: `3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d`
- Repository license declaration: Apache License 2.0

SignalForge does not redistribute model weights. The reproduction script requires the user to
obtain the exact upstream revision independently. Model use remains subject to the authoritative
license and terms published with that upstream revision.

## Local Inference Runtime

### llama.cpp

- Upstream repository: <https://github.com/ggml-org/llama.cpp>
- Revision: `305ba519ab61cdff8044922cba2347826a04453f`
- License: MIT License

SignalForge does not vendor `llama.cpp` source or binaries. The Radeon build script fetches the
hash-pinned upstream revision and builds it locally with ROCm/HIP support.

### AMD ROCm And Radeon Runtime

ROCm, HIP, Radeon drivers, and the AMD OneClick base environment are external platform components.
They are not redistributed in this repository. Their individual upstream licenses and platform
terms remain authoritative.

## Go Modules

The production module identities are pinned by `go.mod` and `go.sum`.

| Component | Version | License |
| --- | --- | --- |
| `github.com/cockroachdb/apd/v3` | `v3.2.3` | Apache License 2.0 |
| `modernc.org/sqlite` | `v1.38.2` | BSD 3-Clause License |

Go resolves additional indirect modules recorded in `go.mod` and `go.sum`. No Go dependency source
is copied into this repository.

## Python Packages

Python packages are optional build, analytics, retrieval, and document-generation dependencies.
They are pinned by the corresponding requirements files and are not vendored.

| Component | Version | License declaration |
| --- | --- | --- |
| `duckdb` | `1.5.4` | MIT License |
| `sentence-transformers` | `5.1.2` | Apache License 2.0 |
| `qdrant-client` | `1.15.1` | Apache License 2.0 |
| `reportlab` | `4.4.9` | BSD License |

## Web Runtime, Tooling, And Fonts

The exact direct and transitive JavaScript package identities are pinned by `web/package-lock.json`.
Dependencies are installed with `npm ci`; `node_modules` and generated `web/dist` output are not
committed.

| Component | Version | License |
| --- | --- | --- |
| `react` | `19.2.8` | MIT License |
| `react-dom` | `19.2.8` | MIT License |
| `@fontsource/ibm-plex-mono` | `5.3.0` | SIL Open Font License 1.1 |
| `@fontsource/newsreader` | `5.3.0` | SIL Open Font License 1.1 |
| `@testing-library/jest-dom` | `6.9.1` | MIT License |
| `@testing-library/react` | `16.3.2` | MIT License |
| `@types/react` | `19.2.17` | MIT License |
| `@types/react-dom` | `19.2.3` | MIT License |
| `@vitejs/plugin-react` | `5.2.0` | MIT License |
| `jsdom` | `26.1.0` | MIT License |
| `typescript` | `5.9.3` | Apache License 2.0 |
| `vite` | `7.3.6` | MIT License |
| `vitest` | `3.2.7` | MIT License |

The IBM Plex Mono and Newsreader font files incorporated by a locally generated web bundle remain
under the SIL Open Font License 1.1 distributed by their Fontsource packages.

## External Data And Services

SignalForge source code contains deterministic synthetic fixtures and bounded, cited public
evidence necessary for reproduction. It does not redistribute raw SEC payloads, proprietary market
feeds, restricted accounting corpora, or user credentials.

- SEC EDGAR data is acquired at runtime from official SEC endpoints under applicable SEC policies.
- FRED and Alpaca integrations are optional bring-your-own-key paths governed by their provider
  terms.
- Investor-relations sources remain company-authored external documents; the public repository
  stores bounded metadata and evidence needed for the demonstrated vertical, not a general mirror.
- Restricted IFRS and other private research corpora are explicitly excluded from this repository.

## Verification

The release auditor rejects bundled model weights, private corpora, populated credential files,
forbidden runtime data, oversized files, and unresolved judge-artifact hashes. Run:

```bash
python3 scripts/audit_public_repo.py --output /tmp/signalforge-release-audit.json
```

This inventory is an engineering compliance aid, not legal advice. When an upstream license or
service term changes, the exact pinned release and its authoritative upstream materials control.
