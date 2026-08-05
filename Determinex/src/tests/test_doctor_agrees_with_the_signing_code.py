"""`determinex doctor` must predict what the corpus signing code will actually do.

MEASURED 2026-07-31 by running two documented commands back to back:

    $ determinex doctor
      ✗ hmac_key   DETERMINEX_HMAC_KEY not set — corpus rows will not be signed
          → fix: set DETERMINEX_HMAC_KEY=<random 32+ bytes hex> in .env

    $ python scripts/determinex_hive.py new-session --spec my_spec.md --lang rust
      [SAFETY] No DETERMINEX_CORPUS_HMAC_KEY set — using session-ephemeral HMAC key

Two different variable names for one knob, and the diagnostic named the wrong one. Wrong in both
directions:

  * Follow doctor's fix and set DETERMINEX_HMAC_KEY -> doctor turns green while corpus rows stay
    unsigned, because determinex_safety, hive/workspace and corpus/corpus_manager each read
    DETERMINEX_CORPUS_HMAC_KEY directly and consult no settings object. A warning reported as
    resolved that is not resolved is worse than the warning.
  * Set DETERMINEX_CORPUS_HMAC_KEY, the name that actually works -> doctor reports "not set".

And a second, sharper mismatch in the same check: `determinex_safety._load_hmac_key` requires
`bytes.fromhex(raw)` to parse and yield >= 32 BYTES, i.e. 64 hex characters. Doctor compared
`len(key) < 32` against the hex STRING, so a 32-hex-char (16-byte) key was reported ACTIVE and
then silently rejected by the signing code.

These tests pair the two sides for every input class, so the pair cannot drift apart again.
determinex_settings.py already carries a comment about having had this precedence backwards once;
that makes this the third place the same fact is written down.

One honest note on the byte-length case. Checked against the original implementation, the
alias-only and canonical-only tests both fail it, as intended. The short-key test does NOT --
because the old check read only DETERMINEX_HMAC_KEY, it never reached its own length comparison
when the canonical variable was the one set. The string-vs-bytes bug was therefore LATENT, made
live by fixing the variable name. It is guarded here because it is real now, not because it ever
fired.
"""

from __future__ import annotations

import importlib
import secrets
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from determinex_doctor import (  # noqa: E402
    _HMAC_KEY_ENV_NAMES,
    _HMAC_KEY_MIN_BYTES,
    check_hmac_key,
)

CANONICAL, ALIAS = _HMAC_KEY_ENV_NAMES
GOOD_KEY = secrets.token_hex(_HMAC_KEY_MIN_BYTES)  # 64 hex chars = 32 bytes
SHORT_KEY = secrets.token_hex(16)  # 32 hex chars = 16 bytes
NOT_HEX = "z" * 64


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _HMAC_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _signing_key_is_durable(monkeypatch) -> bool:
    """Does the REAL signing code accept the current environment, or fall back to ephemeral?

    Re-imports determinex_safety because it loads the key at module scope into
    `_CORPUS_HMAC_KEY`. Reading the module-level constant of an already-imported module would
    measure whatever the environment was when the test session started, which is not what any of
    these tests are asking about.
    """
    for mod in ("determinex_safety",):
        sys.modules.pop(mod, None)
    safety = importlib.import_module("determinex_safety")
    # _load_hmac_key returns the configured key when usable and a fresh random one otherwise, so
    # two calls agreeing is exactly "the configuration was honoured".
    first = safety._load_hmac_key()
    second = safety._load_hmac_key()
    return first == second


class TestDoctorMatchesTheSigningCode:
    """The pairing. Each case asserts doctor's verdict AND the consumer's behaviour."""

    def test_nothing_set_is_unavailable_and_signing_is_ephemeral(self, monkeypatch):
        assert check_hmac_key().status.startswith("UNAVAIL") or "UNAVAIL" in check_hmac_key().status
        assert _signing_key_is_durable(monkeypatch) is False

    def test_the_canonical_name_with_a_good_key_is_active_and_signing_is_durable(self, monkeypatch):
        monkeypatch.setenv(CANONICAL, GOOD_KEY)
        assert "ACTIVE" in check_hmac_key().status
        assert _signing_key_is_durable(monkeypatch) is True

    def test_the_alias_alone_is_not_reported_active_because_signing_ignores_it(self, monkeypatch):
        """The headline bug. Doctor said ACTIVE (well, it said "not set"); either way it never
        said the thing that is true: the signing code does not read this variable."""
        monkeypatch.setenv(ALIAS, GOOD_KEY)
        check = check_hmac_key()
        assert "ACTIVE" not in check.status, (
            "an alias-only configuration leaves rows signed with an ephemeral key"
        )
        assert CANONICAL in check.detail, "the message must name the variable that actually works"
        assert _signing_key_is_durable(monkeypatch) is False

    def test_a_short_hex_key_is_not_reported_active_because_signing_rejects_it(self, monkeypatch):
        """32 hex chars is 16 bytes. The old check compared 32 against the string length."""
        assert len(SHORT_KEY) == 32 and len(bytes.fromhex(SHORT_KEY)) < _HMAC_KEY_MIN_BYTES
        monkeypatch.setenv(CANONICAL, SHORT_KEY)
        assert "ACTIVE" not in check_hmac_key().status
        assert _signing_key_is_durable(monkeypatch) is False

    def test_a_non_hex_key_is_not_reported_active_because_signing_rejects_it(self, monkeypatch):
        monkeypatch.setenv(CANONICAL, NOT_HEX)
        assert "ACTIVE" not in check_hmac_key().status
        assert _signing_key_is_durable(monkeypatch) is False

    def test_the_canonical_name_wins_when_both_are_set(self, monkeypatch):
        monkeypatch.setenv(CANONICAL, GOOD_KEY)
        monkeypatch.setenv(ALIAS, SHORT_KEY)
        assert "ACTIVE" in check_hmac_key().status
        assert _signing_key_is_durable(monkeypatch) is True


class TestTheNamesAndThresholdComeFromTheConsumer:
    def test_the_canonical_name_is_the_one_the_signing_code_reads(self):
        """If determinex_safety is ever changed to read a different variable, this fails."""
        source = (REPO_ROOT / "scripts" / "determinex_safety.py").read_text(encoding="utf-8")
        assert f'os.environ.get("{CANONICAL}"' in source, (
            f"determinex_safety no longer reads {CANONICAL}; doctor's check is now wrong"
        )

    def test_the_settings_spine_declares_the_same_precedence(self):
        """determinex_settings.hmac_key lists the canonical name FIRST, on purpose."""
        source = (REPO_ROOT / "scripts" / "determinex_settings.py").read_text(encoding="utf-8")
        idx_canonical = source.find(CANONICAL)
        idx_alias = source.find(ALIAS)
        assert idx_canonical != -1 and idx_alias != -1
        assert idx_canonical < idx_alias, (
            "the settings spine must keep the canonical name as the primary alias"
        )

    def test_the_byte_threshold_matches_what_the_signing_code_enforces(self):
        source = (REPO_ROOT / "scripts" / "determinex_safety.py").read_text(encoding="utf-8")
        assert f"len(key) >= {_HMAC_KEY_MIN_BYTES}" in source, (
            f"determinex_safety's minimum key length changed; doctor still checks "
            f"{_HMAC_KEY_MIN_BYTES} bytes"
        )

    def test_the_fix_string_tells_the_user_a_command_that_produces_a_valid_key(self, monkeypatch):
        """The old fix said "<random 32+ bytes hex>", which reads as 32 characters."""
        check = check_hmac_key()
        assert "token_hex(32)" in check.fix, check.fix
        generated = secrets.token_hex(32)
        assert len(bytes.fromhex(generated)) >= _HMAC_KEY_MIN_BYTES
        monkeypatch.setenv(CANONICAL, generated)
        assert "ACTIVE" in check_hmac_key().status, "doctor's own suggested command must satisfy it"
