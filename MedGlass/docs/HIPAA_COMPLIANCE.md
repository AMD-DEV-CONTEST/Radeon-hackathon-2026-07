# MedGlass — HIPAA Compliance Deep-Dive & Roadmap (CIO Brief)

**Audience:** CIO / CISO / Clinical Engineering
**Scope:** MedGlass ambient clinical scribe (MVP → best-in-class)
**Current state:** AMD ROCm / Ubuntu local edge stack; Mentra Live glasses; ngrok tunnel; web dashboard + live page; SOAP notes with S/O/A/P, transcript, case photos, FHIR R4 / CDA exports.

> This document is **not legal advice**. It is an engineering risk assessment and
> a gap-to-remedy roadmap. Engage HIPAA counsel and an external risk assessor
> before production use with live patients.

---

## 1. Executive summary

MedGlass is architecturally **ahead of most ambient scribes on privacy**: every AI
stage (whisper ASR, vision (detection + OCR), and the Qwen LLM that writes SOAP notes) runs
on-premise on an AMD GPU. For the primary clinical path, **PHI never leaves the
clinician's environment** for inference. That is a strong, defensible position.

However, **HIPAA compliance is not yet achieved.** The gaps are not in AI — they are
in the classic domains: authentication, access control, audit logging, encryption at
rest, transmission of PHI over a third-party tunnel, Business Associate Agreements,
retention/disposal, and a documented security risk analysis. None of these are
implemented at production grade today.

**Top 5 actions before any live-patient deployment:**
1. **Risk Analysis** (45 CFR § 164.308(a)(1)(ii)(A)) — document it; everything else flows from it.
2. **Replace any shared single credential** with per-user accounts, salted-hash passwords, MFA, lockout, RBAC, and inactivity timeout.
3. **Encrypt PHI at rest** (notes, transcripts, original photos) and **limit the original-photo hold**; photos are stored as originals, encrypted at rest and gated behind authentication (no blurring is performed).
4. **Bring Mentra SDK / cloud relay and ngrok under BAA + TLS**; turn the tunnel OFF outside demo, or replace with private networking (tailnet/VPN) and a real identity proxy.
5. **Audit logging + retention/disposal** (who viewed/exported each note; purge policy with proof of secure deletion).

---

## 2. HIPAA applicability

MedGlass is a **workflow/product**, not itself a Covered Entity (CE) — unless the
deploying clinic is one (most are). Applicability chain:

| Actor | Role | Obligation |
|---|---|---|
| Clinic deploying MedGlass | **Covered Entity** (or CE's workforce) | Security & Privacy Rule; BAA with vendors |
| MedGlass team / product owner | **Business Associate** (if PHI access) or **vendor/BAA-holder** | BAA, Security Rule safeguards, Breach Notification to CE |
| MentraOS (cloud STT/session relay) | **Subcontractor BA** | BAA via MedGlass; must sign when cloud relay carries PHI |
| ngrok (public tunnel) | Infrastructure (no PHI content access by design) | Review ngrok's terms/data-handling; prefer egress-only private tunnel |
| AMD (hardware/firmware) | Vendor | Standard enterprise agreements |

**Key nuance:** with `MEDGLASS_USE_OWN_WHISPER=1`, transcription is fully local and
MentraOS Cloud does not receive raw audio — but it **still relays session metadata and
summary speech (TTS) through the cloud**. TTS summaries contain PHI. Treat any cloud
leg in the data flow as PHI-bearing until proven otherwise.

**What counts as PHI in MedGlass today (all present):** patient identifiers
(`patient_id`), full transcript, note text (S/O/A/P), visual findings, case photos
(original JPEGs), provider name, session
timestamps, exported FHIR R4 / CDA documents.

---

## 3. Data map & flows

```
Mentra Live glasses (mic, cam, LED, speaker)
   └─ phone: Mentra app ── MentraOS Cloud (STT, session relay, TTS)   [PHI-bearing]
        │  webhook/WebSocket  (session start/stop, transcript, audio, photos)
        ▼
   Bun app (port 3000)  client/mentraos-app
        │ HTTPS  ingest → vision/process → generate_note
        ▼
   Edge server (FastAPI, 127.0.0.1:8100)
        │  whisper (local ROCm/CPU) · YOLOv8-seg detection · EasyOCR · Qwen LLM
        ▼
   output/notes/*.json + txt   │   output/photos/*.jpg
   (plaintext on disk)          │   output/soap_note.*
```

**PHI at rest:** `output/notes/` (JSON: note, transcript, patient_id, provider,
visual_findings, timestamps) and `output/photos/` (original JPEGs). **Plaintext.**

**PHI in transit:** phone↔Mentra cloud (their TLS), Bun↔edge (localhost, plain HTTP),
browser↔edge via **ngrok HTTPS** (TLS, but third-party tunnel into a clinical LAN).

**Data leaving the organization:** (a) audio + transcript via MentraOS cloud when
cloud STT enabled; (b) TTS summaries; (c) tunnel traffic. All require BAA/controls.

---

## 4. Current posture (verified in code)

| Control | Status today | Risk |
|---|---|---|
| AI inference location | Fully local (AMD ROCm) | ✓ Strong |
| AuthN | Per-user scrypt-hashed accounts (`output/users.json`, 0600); no default credential baked into source (one-time password generated if unset) | 🟢 Good |
| Sessions | `secrets.token_hex(32)` cookie, httponly + SameSite=Lax, double-submit CSRF token, persisted to `output/.sessions.json`, 60-min idle timeout | 🟢 Good |
| MFA / lockout / rate limit | TOTP MFA (RFC 6238 stdlib), per-user lockout (10 fails → 15 min), per-real-IP rate limit | 🟢 Good |
| Authorization/RBAC | Admin/clinician roles; notes delete, `/users*`, `/admin/purge` admin-only | 🟢 Good |
| Inactivity timeout | 60 min idle + session expiry | 🟢 Good |
| Transport (public) | TLS via ngrok; edge on localhost plain HTTP | 🟠 Medium (see #6/#7) |
| TLS (internal) | None on edge (bound to 127.0.0.1) | 🟠 Medium |
| Encryption at rest | AES-256-GCM for notes/photos/keys (`MEDGLASS_ENCRYPT_AT_REST=1`) | 🟢 Good |
| Audit logging | JSONL audit log (`output/audit.log`) with real client IP for login/task/delete/purge/TTS events | 🟢 Good |
| Photo privacy | Originals stored at rest (encrypted); access-gated in UI; no blurring performed | 🟢 Good baseline |
| Data retention / disposal | Startup purge + `POST /admin/purge` (`MEDGLASS_RETENTION_DAYS`) | 🟢 Good |
| Backups | None | 🟠 Medium |
| PHI minimization | Transcript + full note + original photos stored | 🟠 Medium |
| Hardcoded secrets in config | Removed — `login_password` defaults to empty; env-overridable | 🟢 Good |
| CSRF | SameSite=Lax cookie + double-submit `X-CSRF-Token` on state-changing requests | 🟢 Good |
| XSS | EscapeHtml used in JS rendering; user content is note text | 🟢 Low-moderate |

---

## 5. Security Rule safeguards mapped to MedGlass (45 CFR § 164.308/310/312)

### 5.1 Administrative safeguards (§ 164.308)

| Requirement | MVP today | Target |
|---|---|---|
| Security management process / **risk analysis** | ✗ none | Documented RA + remediation plan; annual re-run |
| Risk management / security policies | ✗ | Written policies (access, acceptable use, incident response) |
| Sanction policy / workforce training | ✗ | Training for all users; sanctions documented |
| Information system activity **review** (audit) | ✗ | Automated review of audit logs; alerting |
| Contingency plan (backup, disaster recovery) | ✗ | Encrypted automated backups; restore drill |
| Evaluation | ✗ | Periodic technical + administrative evaluation |
| BA agreements (BAA) | ✗ | BAA with Mentra (cloud), ngrok, any infra vendor |

### 5.2 Physical safeguards (§ 164.310)

| Requirement | MVP today | Target |
|---|---|---|
| Facility access controls | Workstation in clinic | Locked server room/space; access log |
| Workstation use/security | Shared admin desktop | Standardized, locked-down Ubuntu image; auto-lock |
| Device & media controls (disposal/re-use) | ✗ | SSD wipe (NIST 800-88) before reuse/disposal |

### 5.3 Technical safeguards (§ 164.312)

| Requirement | MVP today | Target |
|---|---|---|
| Access control (unique user, RBAC, emergency access) | ✗ shared cred | Per-user; clinician/admin/auditor roles; break-glass |
| **Audit controls** | ✗ | Log all access/export/delete; append-only; WORM-ish |
| Integrity controls | ✗ | Sign/checksum note files; detect tampering |
| Authentication (MFA) | ✗ | TOTP/WebAuthn after password; lockout + throttling |
| **Encryption in transit** | ngrok TLS only | Full TLS everywhere incl. internal; private tunnel |
| **Encryption at rest** | ✗ | Disk-level (LUKS) + app-level PHI encryption |

---

## 6. Privacy Rule — Minimum Necessary (most under-rated for scribes)

Scribes are a poster child for **minimum necessary** violations. Actions required:

- **Store only what the note needs.** Today we retain the *full verbatim transcript*
  and *original photos* indefinitely. Deploy a policy: transcript summarized/deleted
  after note sign-off (configurable N days), original photos dropped or encrypted +
  access-gated after review.
- **Original-photo access gating** (encrypted at rest, auth-gated in UI) already
  aligns with minimum necessary — keep it.
- **Collection limitation:** do not collect beyond the visit (clear session reset,
  which exists) and add explicit consent + patient notice for recording (most states
  require two-party consent).
- **Redaction/consent controls:** allow clinician to redact a transcript line or note
  section before commit (and log the redaction).

---

## 7. Breach Notification Rule (§ 164.400)

- Conduct an **initial 4-factor risk assessment** template: nature/extent of PHI, who
  was the recipient, whether it was actually viewed, mitigation.
- Unencrypted PHI = presumptive breach. **Encryption at rest + transit is therefore
  the cheapest breach-notification mitigation** (breach exception for encrypted data).
- Have an incident response runbook: containment → forensics → CE notification
  (60 days) → workforce training → OCR report if 500+ individuals.

---

## 8. Roadmap: MVP → v1 → v2 → best-in-class

Legend: `P0` = before live patients · `P1` = next 90 days · `P2` = 6–12 mo.

### Phase 0 — MVP (hackathon demo, NO live PHI)
- Demo-only notice; synthetic data only; no real patient names.
- P0 **hardcode a demo splash** "For demonstration — do not enter real patient data."
- Continue local-AI story (already strong).

### Phase 1 — Production-Hardening (P0/P1)
1. **AuthZ/AuthN** (P0):
   - Per-user accounts; passwords hashed (argon2id/bcrypt); salt; constant-time compare.
   - Remove default credential from `config.py`; require `MEDGLASS_LOGIN_*` env/secret manager.
   - MFA (TOTP) optional-first; lockout after 5 attempts; per-IP throttling.
   - Session: DB-backed (SQLite/Postgres) tokens, 15-min idle timeout, CSRF token per session, `Secure` cookie (once TLS internal).
2. **Encryption at rest** (P0):
   - LUKS full-disk on the server.
   - App-level: encrypt `output/notes/*.json` + original photos with envelope encryption (per-note DEK, KEK from secrets manager/HSM); key rotation.
3. **Transmission** (P0):
   - Internal TLS (self-signed cert authority / tailnet mTLS).
   - Replace ngrok for anything clinical: **Tailscale/WireGuard mesh + identity-aware proxy** (or ngrok with a BAA, IP allow-list, and tunnel **off** by default).
4. **Audit** (P0/P1):
   - Append-only audit log: `who, when, what (view/export/delete), note_id, client IP, outcome`; ship to syslog/Wazuh; alert on bulk export/delete.
5. **Data minimization & retention** (P0):
   - Configurable retention; encrypted secure-delete + purge certificate; transcript auto-summary.
6. **Integrity**: file checksums/signatures on note store; tamper alert.

### Phase 2 — Enterprise (P1/P2)
7. **RBAC + roles**: clinician (own + shared patient list), supervisor (all), admin (config), auditor (read-only logs). Scoped note access; patient-consent flag per note.
8. **BAA workflow**: signed BAA with MentraOS cloud; disable cloud STT path by default (`MEDGLASS_USE_OWN_WHISPER=1` default); re-verify TTS relay (route TTS locally with local TTS engine to avoid cloud PHI).
9. **Compliance tooling**: SOC 2 aligned control evidence; vulnerability scanning (trivy/OSV on deps), dependency update pipeline; SBOM.
10. **Monitoring/IR**: SIEM feed, incident runbook, uptime/health SLA, backup + DR drill quarterly, restore tested.
11. **Patching**: unattended-upgrades + quarterly security window; CVE triage SLAs.

### Phase 3 — Best-in-class
12. **Zero-trust**: device attestation, per-patient authorization via EHR/SSO (OIDC/SAML + SCIM), JIT admin.
13. **Privacy engineering**: differential-privacy-style transcript summaries, redaction UI, patient-facing notice + consent management, opt-out registry.
14. **Interoperability & governance**: FHIR R4 store (HAPI/Firely) with provenance; CDA/CCD attestation; SNOMED/LOINC coding; retention integrated with EHR.
15. **Audit automation**: ML-assisted anomaly detection on access patterns; quarterly risk re-assessment; HITRUST or NIST 800-53 mapping; OCR-facing audit readiness.

---

## 9. Concrete engineering backlog (implementable now)

**Status legend:** ✅ implemented in this repo · 🔶 partially / config-driven · ⬜ not started

| # | Item | File/location | Phase | Status |
|---|---|---|---|---|
| 1 | Move password to scrypt (argon2id needs a lib) + per-user table; delete default cred | `src/users.py`, `src/config.py` | P1 | ✅ |
| 2 | Session persistence + idle timeout + CSRF | `src/server.py` | P1 | ✅ (idle 30 min, persisted to `output/.sessions.json`, double-submit CSRF) |
| 3 | Envelope-encrypt note/photo stores | `src/crypto.py`, `src/notes_store.py`, `src/photo_store.py` | P1 | ✅ (AES-256-GCM, key 0600, `MEDGLASS_ENCRYPT_AT_REST=1`) |
| 4 | Audit log middleware + export/delete events | `src/audit.py`, `src/server.py` | P1 | ✅ (JSONL, real client IP via forwarded X-Forwarded-For) |
| 5 | Retention/purge job + secure delete | `src/retention.py` | P1 | ✅ (startup + `POST /admin/purge`; `MEDGLASS_RETENTION_DAYS=365`) |
| 6 | Internal TLS / mTLS (tailnet) | deploy | P1 | 🔶 (edge bound to 127.0.0.1; tunnel is ngrok TLS) |
| 7 | Tunnel-off-by-default + IP allow-list | `client/mentraos-app`, ngrok | P1 | 🔶 (login gate enforced; `MEDGLASS_ALLOWED_IPS` edge middleware implemented, default off) |
| 8 | Rate limiting + lockout | `src/server.py` | P1 | ✅ (30/min per real IP, cleared on success; 10 fails → 15-min lock) |
| 9 | RBAC + roles | `src/users.py`, `src/server.py` | P2 | ✅ (admin/clinician; delete/users/purge admin-only, `/users` API) |
| 10 | Local TTS (no cloud PHI summaries) | `src/server.py` (GET /tts via espeak-ng) + Bun app | P2 | ✅ (glasses no longer speak PHI; dashboard "Speak note" reads notes locally) |
| 11 | Redaction UI + consent flag | dashboard/app.js | P2 | ⬜ |
| 12 | Dependency scanning + SBOM | CI | P2 | ⬜ |
| 13 | TOTP MFA (RFC 6238, stdlib) | `src/totp.py`, `src/server.py`, login UI | P1 | ✅ (`POST /me/mfa/enable`, self-service, login second stage) |

Key files added: `src/crypto.py`, `src/users.py`, `src/audit.py`, `src/retention.py`, `src/totp.py`.

---

## 10. Checklist for the auditor / OCR readiness

- [ ] Signed risk analysis (updated annually)
- [ ] Written security policies + workforce training logs
- [ ] BAAs for every PHI-touching vendor (Mentra, ngrok, hosting)
- [ ] Unique user IDs + MFA; no shared accounts
- [ ] Encryption at rest (LUKS + app-level) and in transit (TLS everywhere)
- [ ] Audit logs enabled, retained ≥ 6 years, reviewed
- [ ] Data retention & disposal policy with purge evidence
- [ ] Breach response runbook + initial risk-assessment template
- [ ] Contingency plan: encrypted backups + tested restore
- [ ] Physical/device controls: locked space, auto-lock, SSD wipe policy
- [ ] Incident & vulnerability management process

---

## 11. Recommended 12-month security investment (high-level)

- **Immediate (< 1 mo):** audit logging, argon2 hashing + MFA, LUKS encryption, tunnel-off default, remove default credential.
- **1–3 mo:** BAA with Mentra, local TTS, RBAC, rate limiting, encrypted backups.
- **3–6 mo:** SOC 2 readiness, SIEM/SOAR feed, dependency SBOM/scanning, DR drill.
- **6–12 mo:** OIDC/SAML SSO + SCIM, FHIR store with provenance, HITRUST/NIST mapping, OCR audit rehearsal.

> Bottom line: MedGlass's local-first AI is a genuine competitive advantage for
> HIPAA. Close the classical security gaps (auth, encryption, audit, BAA,
> retention) in that order, and it becomes a credible production clinical product.
