# CVE excerpt (offline copy for RAG demo)

## CVE-2024-6387 (regreSSHion)
Severity: 8.1 (High). A signal handler race condition in OpenSSH server
(sshd) allows an unauthenticated remote attacker to achieve remote code
execution as root, under certain conditions, on glibc-based Linux systems.
Affects OpenSSH versions before 4.4p1 (unless patched) and 8.5p1 through
9.7p1. Mitigation: upgrade OpenSSH, or set LoginGraceTime to 0 as a
temporary workaround (has its own tradeoffs).

## CVE-2023-44487 (HTTP/2 Rapid Reset)
Severity: 7.5 (High). Exploits HTTP/2's stream multiplexing and cancellation
features to cause denial of service by rapidly creating and cancelling
requests. Affects most HTTP/2-supporting web servers. Mitigation: apply
vendor patches, add rate limiting on stream resets.
