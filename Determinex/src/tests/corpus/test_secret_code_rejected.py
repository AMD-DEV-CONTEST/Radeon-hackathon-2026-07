"""
Corpus gate: code containing secrets must be rejected before ingest.

Verifies that the SecretScanner detects embedded API keys, tokens,
private keys, and credentials in source files. Any file with a secret
finding is corpus-rejected regardless of its license.

CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corpus.code_ingest.secret_scanner import is_clean, scan_content, scan_file


class TestSecretScanner:
    def test_openai_key_detected(self):
        code = 'API_KEY = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZaAbBcCdDeEfFgGhHiIjJkK"\n'
        result = scan_content(code, "test_openai.py")
        assert not result.clean, "OpenAI API key must be detected"
        assert any(f.category == "llm_key" for f in result.findings)

    def test_anthropic_key_detected(self):
        code = 'KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz1234567890abcd"\n'
        result = scan_content(code, "test_anthropic.py")
        assert not result.clean, "Anthropic API key must be detected"

    def test_aws_access_key_detected(self):
        code = 'aws_key = "AWS_KEY_PLACEHOLDER1"\n'
        result = scan_content(code, "test_aws.py")
        assert not result.clean, "AWS access key must be detected"
        assert any(f.category == "aws" for f in result.findings)

    def test_private_key_detected(self):
        code = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
        )
        result = scan_content(code, "test_privkey.pem")
        assert not result.clean, "RSA private key must be detected"
        assert any(f.category == "private_key" for f in result.findings)

    def test_database_url_with_credentials_detected(self):
        code = 'DB_URL = "postgres://admin:SuperSecret123@localhost:5432/mydb"\n'
        result = scan_content(code, "config.py")
        assert not result.clean, "Database URL with credentials must be detected"
        assert any(f.category == "database" for f in result.findings)

    def test_slack_token_detected(self):
        code = 'SLACK_TOKEN = "SLACK_TOKEN_PLACEHOLDER"\n'
        result = scan_content(code, "slack_bot.py")
        assert not result.clean
        assert any(f.category == "service_token" for f in result.findings)

    def test_clean_code_passes(self):
        code = """
def calculate_sum(numbers):
    total = 0
    for n in numbers:
        total += n
    return total
"""
        result = scan_content(code, "math_util.py")
        assert result.clean, f"Clean code must pass; findings: {result.findings}"

    def test_placeholder_key_skipped(self):
        """Obvious placeholder values must not be flagged."""
        code = 'API_KEY = "YOUR_API_KEY_HERE"\n'
        result = scan_content(code, "example.py")
        assert result.clean, "Placeholder values must not be flagged as secrets"

    def test_example_key_skipped(self):
        code = "# AWS_KEY_PLACEHOLDER is used in AWS documentation\n"
        result = scan_content(code, "docs.py")
        assert result.clean, "AWS documentation example key must not be flagged"

    def test_file_scan(self, tmp_path):
        """scan_file() must detect secrets in a real file."""
        f = tmp_path / "config.py"
        f.write_text(
            'SECRET_KEY = "sk-ant-api03-realkey12345678901234567890123456789012"\n',
            encoding="utf-8",
        )
        result = scan_file(f)
        assert not result.clean

    def test_is_clean_false_for_secret_file(self, tmp_path):
        f = tmp_path / "secrets.py"
        f.write_text('TOKEN = "ghp_EXAMPLE_NOT_REAL_000000000000000000"\n', encoding="utf-8")
        assert not is_clean(f)

    def test_is_clean_true_for_safe_file(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("def add(a, b): return a + b\n", encoding="utf-8")
        assert is_clean(f)

    def test_jwt_token_detected(self):
        # Real JWT format: header.payload.signature, each base64url, min 20 chars each
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        code = f'auth_token = "{jwt}"\n'
        result = scan_content(code, "auth.py")
        assert not result.clean, "JWT token must be detected"


class TestSecretScannerResult:
    def test_result_has_line_numbers(self):
        code = (
            "line1\nline2\nAPI_KEY='sk-aBcDeFgHiJkLmNoPqRsTuVwXyZaAbBcCdDeEfFgGhHiIjJkK'\nline4\n"
        )
        result = scan_content(code)
        assert any(f.line_number == 3 for f in result.findings)

    def test_result_to_dict(self):
        code = 'KEY="sk-aBcDeFgHiJkLmNoPqRsTuVwXyZaAbBcCdDeEfFgGhHiIjJkK"\n'
        result = scan_content(code)
        d = result.to_dict()
        assert "clean" in d
        assert "finding_count" in d
        assert isinstance(d["categories"], list)
