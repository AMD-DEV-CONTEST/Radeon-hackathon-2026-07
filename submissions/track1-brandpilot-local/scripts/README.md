# Scripts

`check_rc_tunnel_prerequisites.sh` performs a read-only, sanitised check for the
official Radeon Cloud rc-tunnel installer, identity prerequisites, broker
setting presence, local command/version, loopback backend, selected port, and
existing tunnel. It never prints environment values or tunnel configuration.

`download_remote_evidence.py` downloads only allowlisted completed-job evidence
over certificate-verified HTTPS. It accepts the demo token only through
`BRANDPILOT_DEMO_TOKEN`, uses fixed safe filenames, and removes the variable
from its process environment after the attempt.

`bootstrap_radeon_runtime.sh` verifies the fixed Radeon, HIP, PyTorch, and
inference-package boundary using `/opt/venv/bin/python`. With `--install`, it
installs only missing exact non-Torch wheels, preferring a persistent
`brandpilot-wheelhouse`. It supports sanitised JSON through `--output`.

`start_radeon_demo.sh` requires a temporary token in `DEMO_AUTH_TOKEN`, a
verified `PERSISTENT_ROOT`, and a verified `MODEL_CACHE_DIR`. It bootstraps the
runtime, starts FastAPI on loopback only, checks unauthorised and authorised
status behavior, and starts the official `rc-tunnel 0.3.0`.

`stop_radeon_demo.sh` stops the official tunnel and only the recorded BrandPilot
Uvicorn process. It removes temporary PID/log state and does not use broad
process-killing commands.

`diagnose_tunnel_dns.py` performs a bounded DNS, TCP, certificate-verified TLS,
and unauthenticated HTTPS probe for an assigned official tunnel hostname. Its
sanitized JSON removes the hostname and resolved addresses. Private JSON must be
written outside the repository.

`diagnose_tunnel_dns.ps1` provides a Windows-native companion using
`Resolve-DnsName`, conditional `Test-NetConnection`, and optional `curl.exe`
without `-k`. Its default private report is under the current Windows user's
local application-data directory. Never commit a private report.

Future repeatable setup, validation, model-compatibility, and evidence-capture helpers belong here. Scripts must never embed secrets or launch paid GPU resources automatically.
