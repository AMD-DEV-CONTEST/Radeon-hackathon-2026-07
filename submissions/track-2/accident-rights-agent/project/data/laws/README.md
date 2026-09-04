# Versioned Legal Corpus

`source_manifest.json` is the submission corpus manifest. It records official
sources and manually verified verbatim excerpts. Each record retains the issuing
authority, jurisdiction, version, publication/effective/expiry dates, status,
official URL, and source location. The index accepts only entries whose
`status=effective` and whose effective-date window includes the configured query
date. Historical versions must remain separate records and must never overwrite
the current version.

Snapshots contain only the provisions needed by the traffic-accident scenario;
they do not claim to replace the complete official texts. The submission
candidate keeps verified snapshots and `quote_audit.json` in the repository so
a fresh clone can pass the verbatim-audit gate and rebuild the local
SQLite/Qdrant index without accessing the internet.

A deployment may also run `scripts/fetch_laws.py` to download official pages and
verify titles, domains, and hashes. A failed download never falls back silently
to a secondary website. `scripts/audit_legal_quotes.py` must then be run. Only
when its report matches all 59 `verbatim_excerpt` entries may
`scripts/ingest_laws.py` build the index. `corpus_integrity.json` locks the
fingerprint of the reviewed corpus, so changing any character causes the tests
to fail. Legal conclusions must still return a `LegalCitation`; deterministic
legal wording is blocked when no citation is present.

As of 2026-08-03, the manifest contains 15 sources and 59 excerpts. It includes
the second judicial interpretation on road-traffic-accident damages effective
2026-06-30 and GB 17761-2024 effective 2025-09-01. The TLS certificate-chain
anomaly on the GA 802-2019 full-text page is recorded separately; the version
status was verified through the Ministry of Public Security standards platform.
