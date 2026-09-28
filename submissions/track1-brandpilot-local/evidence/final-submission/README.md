# Final submission evidence

This directory is the judge-facing index for the sanitized final screenshot
set. It combines new local product screenshots with carefully selected copies
of previously verified Radeon evidence.

| File | What it proves | Verification boundary |
|---|---|---|
| `screenshots/home-desktop.png` | Premium responsive homepage and honest status | Local production frontend |
| `screenshots/studio-desktop.png` | Campaign configuration workflow | Local production frontend |
| `screenshots/results-desktop.png` | Multi-concept mock campaign output | Clearly labelled mock mode |
| `screenshots/review-approved.png` | Human Approved state | Local browser mock workflow |
| `screenshots/architecture-desktop.png` | Mock/experimental architecture boundary | Local production frontend |
| `screenshots/home-mobile.png` | Responsive homepage | Local production frontend |
| `screenshots/studio-mobile.png` | Responsive studio | Local production frontend |
| `screenshots/verified-radeon-environment.png` | Sanitized PyTorch/HIP Radeon device evidence | Recorded Radeon Cloud session |
| `screenshots/verified-radeon-output.png` | Genuine SDXL img2img output | Recorded Radeon Cloud session |
| `screenshots/final-dns-blocker.png` | Sanitized final public DNS failure | Recorded Radeon Cloud/Windows diagnostics |
| `screenshots/no-active-instance.png` | Instance destroyed, no active instance | Recorded Radeon Cloud session |

`screenshot-hashes.json` records SHA-256 for every final PNG. The files exclude
tokens, private hostnames, tunnel URLs, internal paths, account identifiers,
emails, instance IDs, client assets, and browser-profile information.

Original technical evidence remains under `evidence/radeon-session-1/`,
`evidence/radeon-session-2/`, and `evidence/radeon-session-3/`.
