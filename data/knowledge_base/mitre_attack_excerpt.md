# MITRE ATT&CK excerpt (offline copy for RAG demo)

## T1110 - Brute Force
Adversaries may use brute force techniques to gain access to accounts when
passwords are unknown or when password hashes are obtained. Sub-techniques
include password guessing, password spraying, and credential stuffing.
Common indicator: multiple failed authentication attempts from the same
source IP against SSH, RDP, or web login forms in a short time window.
Recommended response: block source IP, enforce account lockout policies,
enable MFA, review for any successful logins from the same source.

## T1190 - Exploit Public-Facing Application
Adversaries may attempt to exploit a weakness in an Internet-facing
application (e.g. SQL injection, RCE via known CVE) to gain initial access.
Common indicator: unusual query strings, injection payloads in HTTP
parameters, or exploitation attempts matching known CVE signatures.
Recommended response: patch the vulnerable service, enable WAF rules,
isolate the host if compromise is suspected.

## T1046 - Network Service Discovery
Adversaries may attempt to get a listing of services running on remote
hosts, often as reconnaissance before an intrusion attempt.

## T1071 - Application Layer Protocol
Adversaries may communicate using OSI application layer protocols to avoid
detection by blending in with existing traffic.
