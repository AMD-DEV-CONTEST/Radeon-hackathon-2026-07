"""
THEMIS RAG Indexer
One-time script: indexes OWASP Top 10 and CWE Top 25 into Qdrant.
Run this ONCE before starting the backend:
    python -m backend.rag.indexer
"""

import asyncio
import json
import os
from qdrant_client import AsyncQdrantClient, models

from backend.config import get_settings
from backend.rag.retriever import get_embedding_model, embed_text

settings = get_settings()

# ── OWASP Top 10 2021 Knowledge Base ─────────────────────────
OWASP_TOP_10 = [
    {
        "id": "A01",
        "title": "Broken Access Control",
        "source": "OWASP-A01-2021",
        "category": "security",
        "text": """Broken Access Control occurs when restrictions on what authenticated users are allowed to do 
are not properly enforced. Attackers can exploit these flaws to access unauthorized functionality and/or data.
Common vulnerabilities: path traversal, missing function-level access control, insecure direct object references (IDOR),
bypassing access control checks by modifying the URL or HTML page, or using custom API attack tools.
Mitigation: Implement server-side access control, deny by default, log access control failures, 
rate limit API and controller access, disable web server directory listing.""",
    },
    {
        "id": "A02",
        "title": "Cryptographic Failures",
        "source": "OWASP-A02-2021",
        "category": "security",
        "text": """Cryptographic failures expose sensitive data. Includes: transmitting data in clear text,
using weak cryptographic algorithms (MD5, SHA1, RC4, DES), hardcoded encryption keys, 
missing proper IV, deprecated hash functions for password storage (MD5, SHA1 without salt).
Mitigation: Use strong algorithms (AES-256-GCM, ChaCha20), bcrypt/argon2 for passwords,
TLS 1.2+ for all data in transit, disable caching for sensitive responses.""",
    },
    {
        "id": "A03",
        "title": "Injection",
        "source": "OWASP-A03-2021",
        "category": "security",
        "text": """Injection flaws occur when untrusted data is sent to an interpreter as part of a command or query.
Types: SQL injection, NoSQL injection, OS command injection, LDAP injection, XPath injection, expression language injection.
SQL injection example: query = "SELECT * FROM users WHERE id = " + user_input  — VULNERABLE.
Mitigation: Use parameterized queries, stored procedures, input validation, escape special characters,
use ORM frameworks, principle of least privilege for database accounts.""",
    },
    {
        "id": "A04",
        "title": "Insecure Design",
        "source": "OWASP-A04-2021",
        "category": "security",
        "text": """Insecure design refers to missing or ineffective security controls. Different from implementation bugs.
Includes: missing rate limiting, insecure password recovery (security questions), 
lack of protection for critical business flows, missing multi-factor authentication.
Mitigation: Threat modeling, secure design patterns, reference architectures, security requirements.""",
    },
    {
        "id": "A05",
        "title": "Security Misconfiguration",
        "source": "OWASP-A05-2021",
        "category": "security",
        "text": """Security misconfiguration: default credentials, unnecessary features enabled, verbose error messages,
missing security hardening, improper cloud permissions (S3 bucket public access), CORS misconfiguration,
XML external entity processing enabled, directory listing enabled, default accounts active.
Mitigation: Minimal platform, remove unused features, review cloud storage permissions, 
disable debug in production, implement security headers.""",
    },
    {
        "id": "A06",
        "title": "Vulnerable and Outdated Components",
        "source": "OWASP-A06-2021",
        "category": "security",
        "text": """Using components with known vulnerabilities: outdated libraries, frameworks, 
operating systems without security patches, unsupported or unpatched software.
Mitigation: Inventory components, monitor CVE databases, remove unused dependencies,
implement software composition analysis (SCA), only use components from official sources.""",
    },
    {
        "id": "A07",
        "title": "Identification and Authentication Failures",
        "source": "OWASP-A07-2021",
        "category": "security",
        "text": """Authentication weaknesses: weak passwords allowed, credential stuffing, brute force attacks,
no MFA, weak session IDs, session fixation, predictable tokens, missing logout.
Hardcoded credentials: API_KEY = "abc123" or PASSWORD = "admin" in source code.
Mitigation: MFA, strong password policies, bcrypt/argon2 for password storage,
secure session management, limit failed login attempts.""",
    },
    {
        "id": "A08",
        "title": "Software and Data Integrity Failures",
        "source": "OWASP-A08-2021",
        "category": "security",
        "text": """Insecure deserialization, CI/CD pipeline tampering, auto-update without signature verification,
untrusted data deserialization (pickle.loads, YAML.load without safe_load).
Mitigation: Use digital signatures, verify integrity of packages, 
use safe deserialization methods (json.loads over pickle), SRI for CDN resources.""",
    },
    {
        "id": "A09",
        "title": "Security Logging and Monitoring Failures",
        "source": "OWASP-A09-2021",
        "category": "security",
        "text": """Missing or inadequate logging: failed login attempts not logged, no alerting for suspicious activity,
logs not monitored, log injection vulnerabilities, sensitive data logged (passwords, tokens).
Mitigation: Log login failures, access control failures, server-side validation failures.
Do NOT log passwords, session tokens, or PII. Centralize log management.""",
    },
    {
        "id": "A10",
        "title": "Server-Side Request Forgery",
        "source": "OWASP-A10-2021",
        "category": "security",
        "text": """SSRF: application fetches remote resource from user-supplied URL without validation.
Attackers can force server to make requests to internal services (AWS metadata, internal APIs).
Example: requests.get(url) where url comes from user input.
Mitigation: Validate and sanitize user-supplied URLs, allow-list remote resources,
disable HTTP redirects, segment remote resource access functionality.""",
    },
]

# ── CWE Top 25 Knowledge Base ─────────────────────────────────
CWE_TOP_25 = [
    {"id": "CWE-89", "title": "SQL Injection", "category": "security", "source": "CWE-89",
     "text": "SQL injection occurs when user-controlled data is included in SQL queries without proper parameterization. Use prepared statements."},
    {"id": "CWE-79", "title": "Cross-site Scripting (XSS)", "category": "security", "source": "CWE-79",
     "text": "XSS allows attackers to inject client-side scripts. Sanitize output, use Content Security Policy."},
    {"id": "CWE-78", "title": "OS Command Injection", "category": "security", "source": "CWE-78",
     "text": "OS command injection via subprocess, os.system, or shell=True with unsanitized input. Use subprocess with list args, never shell=True with user input."},
    {"id": "CWE-798", "title": "Hardcoded Credentials", "category": "security", "source": "CWE-798",
     "text": "Hardcoded passwords, API keys, or tokens in source code. Use environment variables or secrets management."},
    {"id": "CWE-22", "title": "Path Traversal", "category": "security", "source": "CWE-22",
     "text": "Path traversal via '../' sequences in file paths. Validate and normalize paths, use allowlists."},
    {"id": "CWE-502", "title": "Deserialization of Untrusted Data", "category": "security", "source": "CWE-502",
     "text": "Unsafe deserialization (pickle.loads, yaml.load). Use json.loads or yaml.safe_load instead."},
    {"id": "CWE-287", "title": "Improper Authentication", "category": "security", "source": "CWE-287",
     "text": "Missing or weak authentication. Implement MFA, rate limiting, account lockout."},
    {"id": "CWE-311", "title": "Missing Encryption of Sensitive Data", "category": "security", "source": "CWE-311",
     "text": "Transmitting sensitive data without encryption. Use TLS 1.2+, encrypt at rest."},
    {"id": "CWE-327", "title": "Broken Cryptographic Algorithm", "category": "security", "source": "CWE-327",
     "text": "Using weak/deprecated algorithms: MD5, SHA1, DES, RC4, ECB mode. Use AES-256-GCM, SHA-256+."},
    {"id": "CWE-918", "title": "SSRF", "category": "security", "source": "CWE-918",
     "text": "Server-Side Request Forgery via user-controlled URLs. Validate URLs against allowlist."},
    {"id": "CWE-94", "title": "Code Injection", "category": "security", "source": "CWE-94",
     "text": "Code injection via eval(), exec(), or dynamic code execution with user input."},
    {"id": "CWE-862", "title": "Missing Authorization", "category": "security", "source": "CWE-862",
     "text": "Missing access control checks before performing sensitive operations."},
]


async def create_collection_if_not_exists(client: AsyncQdrantClient):
    """Create Qdrant collection with proper vector config."""
    try:
        await client.get_collection(settings.qdrant_collection)
        print(f"✅ Collection '{settings.qdrant_collection}' already exists")
    except Exception:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=1024,  # BGE-M3 embedding dimension
                distance=models.Distance.COSINE,
            ),
        )
        print(f"✅ Created collection '{settings.qdrant_collection}'")


async def index_documents(client: AsyncQdrantClient, documents: list[dict], start_id: int = 0):
    """Embed and upsert documents into Qdrant."""
    points = []
    for i, doc in enumerate(documents):
        text_to_embed = f"{doc['title']} {doc['text']}"
        vector = embed_text(text_to_embed)
        points.append(
            models.PointStruct(
                id=start_id + i,
                vector=vector,
                payload={
                    "text": doc["text"],
                    "title": doc["title"],
                    "source": doc["source"],
                    "category": doc["category"],
                    "metadata": {"id": doc.get("id", "")},
                },
            )
        )

    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )
    return len(points)


async def main():
    print("THEMIS RAG Indexer — Building knowledge base...")
    client = AsyncQdrantClient(url=settings.qdrant_url)

    # Create collection
    await create_collection_if_not_exists(client)

    # Index OWASP Top 10
    print("Indexing OWASP Top 10...")
    n = await index_documents(client, OWASP_TOP_10, start_id=0)
    print(f"  ✅ Indexed {n} OWASP entries")

    # Index CWE Top 25
    print("Indexing CWE Top 25...")
    n = await index_documents(client, CWE_TOP_25, start_id=1000)
    print(f"  ✅ Indexed {n} CWE entries")

    # Verify
    info = await client.get_collection(settings.qdrant_collection)
    print(f"\n✅ Knowledge base ready: {info.points_count} documents indexed")
    print(f"   Collection: {settings.qdrant_collection}")
    print(f"   Ready for hybrid retrieval!")


if __name__ == "__main__":
    asyncio.run(main())
