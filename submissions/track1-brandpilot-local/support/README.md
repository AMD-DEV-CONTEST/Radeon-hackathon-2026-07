# Support templates

Only sanitized, reusable support templates belong here. They must not contain
assigned hostnames, tunnel URLs, access tokens, account or instance identifiers,
private ticket links, private correspondence, raw logs, browser data, or
environment dumps.

Store private reports and correspondence outside the repository in the
designated BrandPilot private-support directory. The `.gitignore` rules exclude
`support/private/`, `support/raw/`, private reports, and filenames that suggest
hostname, tunnel URL, or token content.

Before sharing a sanitized diagnostic, confirm that:

- `hostname` equals `<redacted-radeon-tunnel-hostname>`;
- no resolved IP address is present;
- no URL, token, cookie, header, account data, or private host is present;
- TLS verification was not disabled.
