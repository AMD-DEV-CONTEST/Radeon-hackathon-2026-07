"""Start Screen-AI over HTTPS for mobile camera access.

Mobile browsers require a secure context for getUserMedia(). Plain LAN HTTP
such as http://10.x.x.x:8000 cannot use the camera, so the QR scanner needs
HTTPS during local pairing.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[3]
BACKEND = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "ai_pc_operator" / "data" / "certs"
CERT_FILE = CERT_DIR / "screen-ai-local.crt"
KEY_FILE = CERT_DIR / "screen-ai-local.key"

sys.path.insert(0, str(BACKEND))


def lan_ips() -> list[str]:
    """Return likely LAN IPv4 addresses for certificate SANs."""
    ips = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def ensure_cert() -> None:
    """Create a local self-signed certificate if one does not exist."""
    if CERT_FILE.exists() and KEY_FILE.exists():
        return

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Screen-AI Local"),
        ]
    )

    alt_names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for ip in lan_ips():
        alt_names.append(x509.IPAddress(ipaddress.ip_address(ip)))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


if __name__ == "__main__":
    ensure_cert()
    print("HTTPS mobile remote:")
    for ip in lan_ips():
        print(f"  https://{ip}:8443/remote/index.html")
    print("PC QR page:")
    print("  https://localhost:8443/remote/pair.html")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8443,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
        log_level="info",
    )
