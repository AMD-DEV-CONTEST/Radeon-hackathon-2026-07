# 🧪 Seeded Vulnerability Benchmark Repository (`themis-test-repo`)

**Repository**: `https://github.com/alchemy-amd/themis-test-repo`  
**Purpose**: Public benchmark repository seeded with 10 OWASP Top 10 vulnerabilities for reproducible judging.

---

## 📋 Seeded Vulnerability Coverage Matrix

| Test ID | CWE ID | Vulnerability Category | Language | Test PR Link | Expected Detection |
|---|---|---|---|---|---|
| `SEED-01` | **CWE-89** | SQL Injection (SQLi) | Python | [PR #1](https://github.com/alchemy-amd/themis-test-repo/pull/1) | CRITICAL |
| `SEED-02` | **CWE-798** | Hardcoded Secret Key | Python | [PR #2](https://github.com/alchemy-amd/themis-test-repo/pull/2) | HIGH |
| `SEED-03` | **CWE-79** | Reflected XSS | JavaScript | [PR #3](https://github.com/alchemy-amd/themis-test-repo/pull/3) | HIGH |
| `SEED-04` | **CWE-22** | Path Traversal | Python | [PR #4](https://github.com/alchemy-amd/themis-test-repo/pull/4) | HIGH |
| `SEED-05` | **CWE-918** | Server-Side Request Forgery (SSRF) | Python | [PR #5](https://github.com/alchemy-amd/themis-test-repo/pull/5) | HIGH |
| `SEED-06` | **CWE-502** | Insecure Deserialization | Python | [PR #6](https://github.com/alchemy-amd/themis-test-repo/pull/6) | HIGH |
| `SEED-07` | **CWE-327** | Broken Cryptography (MD5) | Go | [PR #7](https://github.com/alchemy-amd/themis-test-repo/pull/7) | MEDIUM |
| `SEED-08` | **CWE-862** | Missing Authorization (IDOR) | Python | [PR #8](https://github.com/alchemy-amd/themis-test-repo/pull/8) | HIGH |
| `SEED-09` | **CWE-400** | Resource Exhaustion (DoS Loop) | Python | [PR #9](https://github.com/alchemy-amd/themis-test-repo/pull/9) | MEDIUM |
| `SEED-10` | **CWE-1078** | Code Quality / PEP8 Violations | Python | [PR #10](https://github.com/alchemy-amd/themis-test-repo/pull/10) | LOW |

---

## ⚡ 1-Click Judge Instructions

To run any of the seeded PRs through THEMIS:
1. Open `http://localhost:3000/review`.
2. Enter Target Repository: `octocat/Hello-World` (or `alchemy-amd/themis-test-repo`).
3. Enter PR Number: `1`.
4. Click **Execute Live Analysis** or **⚡ Run Interactive Vulnerability Demo**.
