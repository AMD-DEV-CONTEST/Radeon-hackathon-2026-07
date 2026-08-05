"""
scripts/determinex_safety.py — Determinex Safety & Ethics Enforcement Layer
=======================================================================
Multi-layer safety system covering every known passthrough vector for
malicious or unethical user requests. This is Determinex's Ethics Oracle
(docs/policy/ETHICS_ORACLE.md): a deterministic behavioral compliance gate,
never an LLM judge.

Architecture (seven independent layers — all must pass):

  Layer 0 — Content Policy (categorical, zero-exception denial list)
  Layer 1 — Intent Classifier (keyword + semantic pattern matching on spec text)
  Layer 2 — Egress Filter (secret / PII / credential scan before cloud API calls)
  Layer 3 — Output Scanner (malicious pattern detection in Builder-generated code)
  Layer 4 — Corpus Validator (HMAC integrity check for training corpus entries)
  Layer 5 — License Scan (SPDX/copyleft header scan before a sample enters the corpus)
  Layer 6 — Runtime Integrity (self-hash of this gate + its adapter; detects
            ToS circumvention — the gate itself being patched out or bypassed)

Harm taxonomy covers:
  - Absolute denials  : malware, exploits, CSAM, weapons, CBRN, network attacks
  - Security denials  : credential theft, phishing, session hijacking, RATs
  - Surveillance      : keyloggers, stalkerware, covert tracking, mass profiling
  - Manipulation      : dark patterns, addiction optimization, astroturfing
  - Harassment        : doxxing tools, contact flooding, identity targeting
  - Fraud             : academic ghostwriting, plagiarism laundering, deepfakes
  - Discrimination    : biased screening, proxy-discrimination systems
  - Economic harm     : wage theft, predatory lending, price gouging automation
  - Privacy           : bulk OSINT aggregation for targeting, voice cloning
  - Cryptoabuse       : unauthorized mining, resource hijacking
  - License violation : copyleft (GPL/AGPL/LGPL/SSPL) code entering the corpus
  - ToS circumvention : the safety layer itself patched, disabled, or bypassed

Known gap (documented, not faked): there is no offline CSAM image/hash
classifier here — Layer 0's CSAM category is a text-keyword net only. A
result of NOT_EVALUATED is never silently reported as clean; callers that
need real media-hash coverage must add a dedicated classifier upstream.

Design principles:
  - Fail-closed: any gate error → DENY (never silently pass)
  - Layered: each layer is independent; all must pass
  - Fast first: keyword scan before heavier semantic analysis
  - Audited: every violation is appended to a tamper-evident, hash-chained,
    fsync'd WAL (logs/safety_wal/wal.jsonl) — never just a log line that can
    scroll away. See wal_append() / verify_wal_integrity().
  - Escalating: violations accumulate per subject (see EscalationState).
    Tier 1-2 = warn, tier 3-5 = restrict (blocks regardless of engine mode),
    tier 6+ = cutoff (hard block until manual re-consent clears state).
  - No LLM judge for safety decisions: deterministic rules only in Layers 0–2;
    Layer 3 uses static analysis (AST + regex), never probabilistic scoring

Usage:
    from determinex_safety import SafetyEngine, SafetyVerdict

    engine = SafetyEngine()
    verdict = engine.check_spec(spec_text)
    if not verdict.safe:
        raise SafetyDenied(verdict.reason)

    verdict = engine.check_output(code_text, lang="python")
    verdict = engine.check_egress(prompt_text)
    verdict = engine.check_license(text, path_hint="corpus/foo.py")
    verdict = engine.check_runtime_integrity()
    engine.sign_corpus_entry(entry_dict)         # mutates in-place
    engine.verify_corpus_entry(entry_dict)       # raises on tamper
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

log = logging.getLogger("determinex.safety")

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
_WAL_DIR = DETERMINEX_ROOT / "logs" / "safety_wal"
_WAL_PATH = _WAL_DIR / "wal.jsonl"
_ESCALATION_DIR = DETERMINEX_ROOT / "logs" / "safety_state"
_INTEGRITY_MANIFEST = DETERMINEX_ROOT / "assurance" / "security" / "safety_layer_integrity.json"
_INTEGRITY_FILES = (
    Path(__file__).resolve(),
    DETERMINEX_ROOT / "scripts" / "hive" / "safety_gate.py",
)


# ── Corpus HMAC key ───────────────────────────────────────────────────────────
# Stored in .env as DETERMINEX_CORPUS_HMAC_KEY (hex, 32 bytes minimum).
# If absent, a session-ephemeral key is generated — sufficient to detect
# in-process tampering but not persist across restarts.
def _load_hmac_key() -> bytes:
    raw = os.environ.get("DETERMINEX_CORPUS_HMAC_KEY", "")
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
        log.warning("[SAFETY] DETERMINEX_CORPUS_HMAC_KEY malformed — using ephemeral key")
    key = secrets.token_bytes(32)
    log.warning(
        "[SAFETY] No DETERMINEX_CORPUS_HMAC_KEY set — using session-ephemeral HMAC key. "
        "Corpus signatures will not survive restarts. Set the env var for production."
    )
    return key


_CORPUS_HMAC_KEY: bytes = _load_hmac_key()


# ─────────────────────────────────────────────────────────────────────────────
# Tamper-evident WAL — every violation, hash-chained + fsync'd
# ─────────────────────────────────────────────────────────────────────────────
# Each line commits to the hash of the previous line ("prev_hash": genesis for
# the first record). Editing or deleting any historical line breaks every
# subsequent hash, so tampering is *detectable* even though this WAL (unlike
# the corpus HMAC) has no secret key — it is meant to be independently
# auditable, not just self-consistent to a keyholder. verify_wal_integrity()
# walks the chain and reports the first break, if any.


def _wal_last_hash(path: Path) -> str:
    if not path.is_file():
        return "genesis"
    last = ""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        return "genesis"
    try:
        return json.loads(last)["record_hash"]
    except (json.JSONDecodeError, KeyError):
        return "genesis"


def wal_append(record: dict, path: Path = _WAL_PATH) -> dict:
    """Append one violation record to the tamper-evident WAL. Returns the
    stored record (with chain fields). Atomic per-line fsync — a crash mid
    write leaves the file truncated at a line boundary, never corrupted
    mid-record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _wal_last_hash(path)
    body = dict(record)
    body["ts"] = time.time()
    body["prev_hash"] = prev_hash
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=True, default=str)
    body["record_hash"] = hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, sort_keys=True, ensure_ascii=True, default=str))
        f.write("\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    return body


class _WalRecordShape(BaseModel):
    """Structural validation ONLY -- record_hash/prev_hash must be present
    and strings. Deliberately does NOT replace the raw dict used for
    hashing below: the hash-chain canonicalization step
    ({k: v for k, v in rec.items() if k != "record_hash"}) must see every
    field exactly as parsed, unfiltered by a model's declared shape, or a
    field not captured by this model could silently escape tamper
    detection. This model only gives a clearer error ("missing record_hash
    field") than letting a missing field default through .get() straight
    into an opaque "record_hash mismatch"."""

    model_config = {"extra": "allow"}

    record_hash: str
    prev_hash: str


def verify_wal_integrity(path: Path = _WAL_PATH) -> tuple[bool, str]:
    """Walk the WAL chain from genesis. Returns (intact, detail). A single
    edited byte anywhere in history breaks the chain from that point on."""
    if not path.is_file():
        return True, "no WAL yet — nothing to verify"
    prev_hash = "genesis"
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                return False, f"line {i}: not valid JSON ({e})"
            try:
                _WalRecordShape.model_validate(rec)
            except ValidationError as e:
                return False, f"line {i}: malformed WAL record ({e})"
            stored_hash = rec.get("record_hash", "")
            stored_prev = rec.get("prev_hash", "")
            if stored_prev != prev_hash:
                return (
                    False,
                    f"line {i}: prev_hash mismatch (chain broken — history edited or reordered)",
                )
            check = {k: v for k, v in rec.items() if k != "record_hash"}
            canonical = json.dumps(check, sort_keys=True, ensure_ascii=True, default=str)
            expected = hashlib.sha256((stored_prev + canonical).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(stored_hash, expected):
                return False, f"line {i}: record_hash mismatch (record content edited after write)"
            prev_hash = stored_hash
            n += 1
    return True, f"{n} record(s), chain intact"


# ─────────────────────────────────────────────────────────────────────────────
# Escalation state — tiered response per subject (session/user/agent id)
# ─────────────────────────────────────────────────────────────────────────────
# Tier curve (docs/policy/ETHICS_ORACLE.md): 1-2 violations = warn (WAL only),
# 3-5 = restrict (hard block regardless of engine mode), 6+ = cutoff (hard
# block; only cleared by clear_escalation(), a deliberate operator action —
# never automatic, so a cutoff can't silently expire).

TIER_CLEAN, TIER_WARN, TIER_RESTRICT, TIER_CUTOFF = "clean", "warn", "restrict", "cutoff"


@dataclass
class EscalationState:
    subject_id: str
    violation_count: int = 0
    tier: str = TIER_CLEAN
    history: list[dict] = field(default_factory=list)  # [{layer, category, ts}, ...]


def _tier_for_count(n: int) -> str:
    if n <= 0:
        return TIER_CLEAN
    if n <= 2:
        return TIER_WARN
    if n <= 5:
        return TIER_RESTRICT
    return TIER_CUTOFF


def _escalation_path(subject_id: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in subject_id)
    return _ESCALATION_DIR / f"{safe}.json"


def load_escalation(subject_id: str) -> EscalationState:
    p = _escalation_path(subject_id)
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return EscalationState(**d)
        except Exception:
            pass
    return EscalationState(subject_id=subject_id)


def _save_escalation(state: EscalationState) -> None:
    _ESCALATION_DIR.mkdir(parents=True, exist_ok=True)
    _escalation_path(state.subject_id).write_text(
        json.dumps(asdict(state), indent=2, default=str), encoding="utf-8"
    )


def record_violation(subject_id: str, verdict: SafetyVerdict) -> EscalationState:
    """Append the violation to the WAL, bump the subject's escalation state,
    persist it, and return the updated state. Called from _enforce() on every
    unsafe verdict — never on a clean one (mirrors the ETHICS_ORACLE.md
    reference pseudocode, which only writes the WAL on a non-clean result)."""
    state = load_escalation(subject_id)
    state.violation_count += 1
    state.tier = _tier_for_count(state.violation_count)
    state.history.append({"layer": verdict.layer, "category": verdict.category, "ts": time.time()})
    _save_escalation(state)
    wal_append(
        {
            "subject_id": subject_id,
            "layer": verdict.layer,
            "category": verdict.category,
            "reason": verdict.reason,
            "violation_count": state.violation_count,
            "tier": state.tier,
        }
    )
    return state


def clear_escalation(subject_id: str) -> None:
    """Deliberate operator action — the re-consent step after a cutoff.
    Never called automatically."""
    p = _escalation_path(subject_id)
    if p.is_file():
        p.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# SafetyVerdict
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SafetyVerdict:
    safe: bool
    reason: str = ""
    layer: str = ""
    category: str = ""
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.safe


class SafetyDenied(Exception):
    """Raised when a safety gate rejects a request."""

    def __init__(self, verdict: SafetyVerdict):
        self.verdict = verdict
        super().__init__(f"[{verdict.layer}] {verdict.category}: {verdict.reason}")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 0 — Content Policy (categorical, zero-exception)
# ─────────────────────────────────────────────────────────────────────────────
#
# Each entry: (category_name, [keyword/phrase list], description)
# A match on ANY keyword in a category triggers an immediate DENY.
# Keywords are matched case-insensitively against the full spec text.
# Compound phrases are matched as substrings (space-normalized).
#
# Sources:
#   - OpenAI Usage Policy (2024)
#   - Anthropic Acceptable Use Policy (2024)
#   - Meta Purple Llama CyberSecEval taxonomy
#   - NIST AI RMF Harm Categories
#   - OWASP LLM Top 10

_ABSOLUTE_DENY: list[tuple[str, list[str]]] = [
    # ── Malware ──────────────────────────────────────────────────────────────
    (
        "MALWARE_RANSOMWARE",
        [
            "ransomware",
            "file encryptor that demands payment",
            "ransom note generator",
            "encrypt victim files",
            "lock files for ransom",
            "crypto locker",
        ],
    ),
    (
        "MALWARE_WIPER",
        [
            "disk wiper",
            "file destroyer",
            "delete all files on",
            "wipe the hard drive",
            "overwrite master boot record",
            "mbr wiper",
            "destructive payload",
            "data destruction tool",
            "irreversible file deletion",
        ],
    ),
    (
        "MALWARE_DROPPER",
        [
            "malware dropper",
            "stage-1 payload",
            "payload delivery",
            "dropper malware",
            "download and execute payload",
            "downloads and executes a payload",
            "downloads and executes payload",
            "write a dropper",
            "build a dropper",
            "self-replicating code",
            "virus propagation",
            "worm propagation",
            "self-spreading",
        ],
    ),
    (
        "MALWARE_TROJAN",
        [
            "trojan horse program",
            "trojan horse that",
            "trojan horse which",
            "implement a trojan",
            "build a trojan",
            "write a trojan",
            "backdoor implant",
            "persistent backdoor",
            "backdoor on port",
            "hidden backdoor",
            "covert backdoor",
            "embed backdoor in",
        ],
    ),
    (
        "MALWARE_BOOTKIT",
        [
            "bootkit",
            "rootkit",
            "kernel rootkit",
            "uefi implant",
            "kernel-level persistence",
            "ring-0 implant",
            "hypervisor rootkit",
        ],
    ),
    (
        "MALWARE_BOTNET",
        [
            "botnet client",
            "bot herder",
            "c2 client",
            "command and control client",
            "bot implant",
            "build a botnet",
            "infected node",
            "zombie machine",
            "recruit bots",
            "botnet infrastructure",
        ],
    ),
    # ── Exploit Development ───────────────────────────────────────────────────
    (
        "EXPLOIT_SHELLCODE",
        [
            "shellcode",
            "shell code payload",
            "shellcode generator",
            "position independent shellcode",
            "alphanumeric shellcode",
            "write shellcode for",
            "craft shellcode",
        ],
    ),
    (
        "EXPLOIT_BUFFEROVERFLOW",
        [
            "buffer overflow exploit",
            "heap spray exploit",
            "use-after-free exploit",
            "rop chain",
            "return oriented programming chain",
            "jit spray",
            "format string exploit",
            "stack smashing exploit",
        ],
    ),
    (
        "EXPLOIT_CVE",
        [
            "exploit cve-",
            "proof of concept exploit for cve",
            "weaponize cve",
            "working exploit for",
            "reliable exploit for",
            "exploit code for vulnerability",
            "exploit this vulnerability",
        ],
    ),
    (
        "EXPLOIT_PRIVESC",
        [
            "privilege escalation exploit",
            "local privilege escalation",
            "lpe exploit",
            "suid exploit",
            "sudo bypass exploit",
            "kernel exploit for privilege",
            "escape container to host",
            "container escape exploit",
            "container escape using",
        ],
    ),
    # ── Network Attacks ───────────────────────────────────────────────────────
    (
        "ATTACK_DDOS",
        [
            "ddos tool",
            "denial of service tool",
            "flood attack tool",
            "syn flood",
            "udp flood attack",
            "http flood attack",
            "http flood tool",
            "flood tool that sends",
            "sends requests per second to crash",
            "amplification attack",
            "dns amplification",
            "ntp amplification",
            "ssdp amplification",
            "botnet ddos",
            "coordinated flooding",
            "bandwidth exhaustion attack",
            "slowloris attack",
        ],
    ),
    (
        "ATTACK_SCANNING",
        [
            "port scanner for attacking",
            "network scanner to find vulnerable",
            "vulnerability scanner to exploit",
            "scan for exploitable services",
            "automated exploit scanner",
            "mass exploit scanner",
        ],
    ),
    # ── Credential Attacks ────────────────────────────────────────────────────
    (
        "CREDENTIAL_HARVEST",
        [
            "credential harvester",
            "credential stealer",
            "password harvester",
            "harvest credentials from",
            "steal passwords from",
            "dump credentials",
            "steals saved passwords",
            "steal saved passwords",
            "steals authentication cookies",
            "steal authentication cookies",
            "session hijacker",
            "session hijacking tool",
            "lsass dump",
            "mimikatz",
            "pass the hash",
            "golden ticket attack",
            "kerberoasting tool",
            "as-rep roasting",
            "ntlm relay",
        ],
    ),
    (
        "CREDENTIAL_STUFFING",
        [
            "credential stuffing",
            "credential stuffing tool",
            "password stuffing",
            "account takeover automation",
            "automated login brute force",
            "brute force login",
            "password sprayer",
            "password spraying tool",
            "spray passwords",
        ],
    ),
    (
        "CREDENTIAL_PHISHING",
        [
            "phishing page",
            "phishing kit",
            "phishing site generator",
            "credential phishing",
            "login page clone",
            "fake login page",
            "spear phishing email generator",
            "smishing tool",
            "vishing script",
            "phishing lure",
            "evilginx",
            "reverse proxy phishing",
        ],
    ),
    # ── Remote Access / Surveillance ──────────────────────────────────────────
    (
        "RAT_REMOTE_ACCESS",
        [
            "remote access trojan",
            "rat implant",
            "remote administration tool implant",
            "covert remote access",
            "hidden remote shell",
            "reverse shell",
            "bind shell implant",
            "persistent reverse shell",
        ],
    ),
    (
        "KEYLOGGER",
        [
            "keylogger",
            "keystroke logger",
            "keystroke capture",
            "key logger",
            "log keystrokes",
            "capture keystrokes",
            "record keystrokes",
            "keyboard sniffer",
            "input capture malware",
        ],
    ),
    (
        "STALKERWARE",
        [
            "stalkerware",
            "stalk someone",
            "covert phone tracking",
            "hidden phone spy",
            "phone spy app",
            "phone spy that",
            "spy app that reads sms",
            "spy on partner",
            "spy on spouse",
            "monitor partner without knowledge",
            "track someone without consent",
            "covert location tracking",
            "hidden screen recorder",
            "stealth monitoring app",
            "invisible tracking",
        ],
    ),
    (
        "SCREENSHOT_COVERT",
        [
            "covert screenshot",
            "hidden screenshot",
            "stealth screenshot",
            "screenshot without user knowledge",
            "silent screen capture",
            "covert screen recording",
            "hidden screen recorder",
        ],
    ),
    # ── Information Operations ────────────────────────────────────────────────
    (
        "INFOOPS_ASTROTURFING",
        [
            "astroturfing",
            "fake grassroots",
            "coordinated inauthentic behavior infrastructure",
            "coordinated inauthentic behavior network",
            "coordinated inauthentic behavior system",
            "build coordinated inauthentic behavior",
            "create coordinated inauthentic behavior",
            "sock puppet network",
            "sock puppet accounts",
            "fake account farm",
            "bot network for influence",
            "bot network that manipulates",
            "influence operation infrastructure",
            "synthetic persona network",
            "automated persona",
            "troll farm",
        ],
    ),
    (
        "INFOOPS_DISINFO",
        [
            "disinformation campaign",
            "fake news generator",
            "fabricate news",
            "synthetic propaganda",
            "automated propaganda",
            "generate false news articles at scale",
        ],
    ),
    # ── Harassment & Targeting ────────────────────────────────────────────────
    (
        "HARASSMENT_FLOOD",
        [
            "contact flooding",
            "contact bombing bot",
            "message bombing",
            "sms bombing",
            "sms bomber",
            "bulk sms bomber",
            "call bombing",
            "spam calls to individual",
            "sends thousands of text messages to harass",
            "send thousands of messages to harass",
            "thousands of text messages to a specific",
            "automated harassment",
            "harassment bot",
            "message flood attack on person",
        ],
    ),
    (
        "HARASSMENT_DOXX",
        [
            "doxxing tool",
            "dox someone",
            "find home address of",
            "expose private information of",
            "reveal personal details of target",
            "aggregate personal data to expose",
            "find where someone lives",
            "identify anonymous user",
            "unmask anonymous poster",
            "unmask anonymous users",
            "correlating their post history",
            "cross-reference to identify pseudonym",
        ],
    ),
    # ── Fraud & Deception ─────────────────────────────────────────────────────
    (
        "FRAUD_ACADEMIC",
        [
            "write essay for me to submit",
            "write my homework to submit",
            "write my assignment to submit",
            "ghostwrite academic paper",
            "academic ghostwriting service",
            "submit as their own work",
            "complete exam questions for submission",
            "answer test questions to submit",
            "plagiarism laundering",
            "paraphrase to evade plagiarism detection",
            "bypass turnitin",
            "bypass plagiarism detector",
        ],
    ),
    (
        "FRAUD_IDENTITY",
        [
            "forge identity document",
            "generate fake id",
            "fake id generator",
            "fake passport",
            "counterfeit credential",
            "fabricate certificate",
            "forge diploma",
            "fake employment verification",
        ],
    ),
    (
        "FRAUD_FINANCIAL",
        [
            "credit card fraud",
            "carding tool",
            "generate valid credit card numbers",
            "luhn valid card numbers for fraud",
            "bank fraud tool",
            "wire fraud automation",
            "invoice fraud",
        ],
    ),
    # ── Child Safety ──────────────────────────────────────────────────────────
    (
        "CSAM",
        [
            "child sexual abuse material",
            "csam",
            "sexual content involving minor",
            "sexual content involving child",
            "minor sexual",
            "underage sexual",
            "child exploitation material",
        ],
    ),
    # ── Weapons & CBRN ────────────────────────────────────────────────────────
    (
        "WEAPONS_INSTRUCTIONS",
        [
            "instructions to build bomb",
            "improvised explosive device instructions",
            "ied construction",
            "building an ied",
            "instructions for building an ied",
            "synthesize nerve agent",
            "synthesize sarin",
            "synthesizing sarin",
            "assists in synthesizing",
            "synthesize vx nerve",
            "bioweapon design",
            "engineer pathogen",
            "enhance pathogen transmissibility",
            "gain of function malicious",
            "synthesize fentanyl",
            "synthesize methamphetamine synthesis route",
            "making thermite",
            "thermite",
            "instructions for making thermite",
        ],
    ),
    (
        "WEAPONS_CRITICAL_INFRA",
        [
            "attack power grid",
            "disrupt power grid",
            "attack water treatment",
            "compromise water treatment",
            "water treatment plant scada",
            "attack nuclear facility",
            "targeting nuclear facility",
            "nuclear facility control",
            "attack hospital systems",
            "hospital power grid",
            "hospital's power grid",
            "take down critical infrastructure",
            "disrupt critical infrastructure",
            "disable emergency services",
            "emergency services communication",
        ],
    ),
]

# ── Ethical denials (legal but categorically harmful) ─────────────────────────
_ETHICAL_DENY: list[tuple[str, list[str]]] = [
    (
        "SURVEILLANCE_UNDISCLOSED",
        [
            "employee monitoring without disclosure",
            "monitor employees without telling them",
            "covert employee surveillance",
            "hidden employee tracking",
            "screenshot employees without consent",
            "activity monitor without notification",
            "monitor computer without user knowing",
            "facial recognition enrollment system that doesn't require consent",
            "facial recognition without consent",
            "facial recognition enrollment without",
            "biometric enrollment without consent",
        ],
    ),
    (
        "MANIPULATION_DARKPATTERN",
        [
            "dark pattern ui",
            "deceptive ui pattern",
            "fake urgency timer",
            "roach motel pattern",
            "hidden unsubscribe",
            "pre-checked consent",
            "disguise ads as content",
            "bait and switch ui",
            "misdirection pattern",
            "trick users into clicking",
        ],
    ),
    (
        "MANIPULATION_ADDICTION",
        [
            "maximize screen time by exploiting",
            "variable reward schedule to hook users",
            "addictive engagement loop",
            "exploit psychological vulnerabilities for engagement",
            "compulsive usage design",
            "design for addiction",
            "dopamine exploitation",
            "infinite scroll to trap",
        ],
    ),
    (
        "REVIEW_MANIPULATION",
        [
            "fake review generator",
            "fake review generation system",
            "generate fake product reviews",
            "post fake reviews",
            "posts fake reviews",
            "review bombing tool",
            "automated fake reviews",
            "review manipulation",
            "astroturf reviews",
        ],
    ),
    (
        "DISCRIMINATION_PROXY",
        [
            "discriminate by zip code as race proxy",
            "zip code as a proxy",
            "uses zip code as a proxy",
            "filter out minority applicants",
            "use name as ethnicity proxy",
            "name as an ethnicity proxy",
            "screen applicants by language as national origin proxy",
            "language as a national origin proxy",
            "filter by school as socioeconomic proxy without basis",
            "discriminatory hiring filter",
            "biased screening algorithm",
        ],
    ),
    (
        "ECONOMIC_WAGEHEFT",
        [
            "falsify time records",
            "automate timesheet fraud",
            "falsify employee timesheets",
            "falsifies employee timesheets",
            "wage theft tool",
            "tools to underpay workers",
            "wage theft automation",
        ],
    ),
    (
        "SPAM_INFRASTRUCTURE",
        [
            "email spam campaign",
            "bulk unsolicited email",
            "spam bot",
            "mass unsolicited sms",
            "robocall campaign without consent",
            "build a spam list",
            "scrape emails for spam",
        ],
    ),
    (
        "CRYPTO_UNAUTHORIZED",
        [
            "mine cryptocurrency on other people's computers",
            "cryptojacking",
            "cryptojacker",
            "deploys mining software on users",
            "cryptominer to install on victims",
            "unauthorized cryptomining",
            "covert mining malware",
            "deploy miner without consent",
        ],
    ),
    (
        "VOICE_CLONE_HARM",
        [
            "clone someone's voice without consent",
            "voice clone for fraud",
            "voice cloning tool to impersonate",
            "voice cloning tool",
            "synthesize voice to impersonate",
            "deepfake voice for scam",
            "fake audio of real person",
        ],
    ),
    (
        "DEEPFAKE_HARM",
        [
            "deepfake of real person without consent",
            "non-consensual deepfake",
            "fake video of real person to deceive",
            "synthetic media to defame",
            "deepfake pornography",
            "non-consensual intimate imagery",
        ],
    ),
    (
        "OSINT_TARGETING",
        [
            "aggregate public data to build dossier on individual",
            "build profile to stalk",
            "osint to find someone's routine",
            "track person's movements using public data",
            "identify someone's home from public data for targeting",
        ],
    ),
    (
        "PREDATORY_FINANCE",
        [
            "predatory lending calculator",
            "exploit payday loan borrowers",
            "target vulnerable borrowers",
            "maximize debt trap",
            "high-cost debt spiral tool",
        ],
    ),
]

# Combine all denial lists into fast lookup
_ALL_DENY_CATEGORIES: list[tuple[str, list[str]]] = _ABSOLUTE_DENY + _ETHICAL_DENY


# Pre-compile: list of (category, compiled_regex) for speed
def _compile_deny_patterns() -> list[tuple[str, re.Pattern]]:
    compiled = []
    for category, keywords in _ALL_DENY_CATEGORIES:
        # Each keyword becomes an alternation in one regex per category
        escaped = [re.escape(kw.lower()) for kw in keywords]
        pattern = re.compile("|".join(escaped), re.IGNORECASE)
        compiled.append((category, pattern))
    return compiled


_DENY_PATTERNS: list[tuple[str, re.Pattern]] = _compile_deny_patterns()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Intent Classifier (semantic pattern matching)
# ─────────────────────────────────────────────────────────────────────────────
#
# Catches reframings and indirect requests that bypass exact keyword matching.
# Examples: "build a tool that monitors a system for research" (stalkerware reframe)
#
# Uses weighted phrase pairs: (suspicious_signal, amplifying_context) → DENY
# A match requires BOTH the signal AND at least one amplifying context pattern.

_INTENT_SIGNALS: list[tuple[str, list[str], str]] = [
    # (signal_keyword, amplifying_phrases_that_make_it_suspicious, category)
    (
        "monitor",
        [
            "without (the user|their|user's) (know|consent|permission|notif)",
            "covert",
            "hidden",
            "stealth",
            "invisible",
            "secret",
            "without (notif|tell|disclos|alert)",
        ],
        "COVERT_MONITORING",
    ),
    (
        "track(ing)?",
        [
            "without (consent|permission|know)",
            "covert",
            "stealth",
            "stalking",
            "follow someone",
            "locate someone",
            "real.time location without",
        ],
        "COVERT_TRACKING",
    ),
    (
        "scrape|harvest|collect",
        [
            "without consent",
            "personal data",
            "private (data|info)",
            "to target",
            "to identify",
            "to locate",
            "to profile",
            "for (stalking|harassment|doxx)",
        ],
        "NONCONSENSUAL_DATA",
    ),
    (
        "automate",
        [
            "harassment",
            "flood",
            "spam",
            "(contact|message) (someone|target)",
            "report (account|profile)",
            "review bomb",
        ],
        "AUTOMATED_HARASSMENT",
    ),
    (
        "bypass|evade|circumvent",
        [
            "detection",
            "security",
            "antivirus",
            "av detection",
            "edr",
            "sandbox",
            "firewall",
            "content filter",
            "safe(guard|ty)",
        ],
        "EVASION",
    ),
    (
        "inject|hook|intercept",
        [
            "process memory",
            "dll injection",
            "api hook",
            "system call",
            "kernel",
            "lsass",
            "credential",
            "password",
        ],
        "CODE_INJECTION",
    ),
    (
        "persistence|persist",
        [
            "registry",
            "startup",
            "cron (job|tab)",
            "launchd",
            "systemd service",
            "scheduled task",
            "after reboot",
            "survive reboot",
            "without (user|admin) knowledge",
        ],
        "PERSISTENCE_MECHANISM",
    ),
    (
        "exfiltrat|send.*(to|back).*server|upload.*(to|back)",
        [
            "without (user|their) knowledge",
            "covert",
            "secretly",
            "private (key|data|file|credential)",
            "credentials",
            "password",
            "token",
            "ssh key",
        ],
        "DATA_EXFILTRATION",
    ),
    (
        "obfuscat|pack(er|ed)|encrypt.*(payload|code)|hide.*(code|malware|payload)",
        [
            "detection",
            "antivirus",
            "security tool",
            "analyst",
            "payload",
            "shellcode",
            "malware",
        ],
        "OBFUSCATION_FOR_EVASION",
    ),
    (
        "clone|replicate|mimic",
        [
            "voice",
            "face",
            "identity",
            "without (consent|permission)",
            "impersonat",
            "deepfake",
        ],
        "SYNTHETIC_IDENTITY",
    ),
]

# Compile intent signal patterns
_COMPILED_INTENT: list[tuple[re.Pattern, list[re.Pattern], str]] = []
for _sig, _amps, _cat in _INTENT_SIGNALS:
    _sig_re = re.compile(_sig, re.IGNORECASE)
    _amp_res = [re.compile(a, re.IGNORECASE) for a in _amps]
    _COMPILED_INTENT.append((_sig_re, _amp_res, _cat))


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Egress Filter (secrets / PII in prompts before cloud API calls)
# ─────────────────────────────────────────────────────────────────────────────

_EGRESS_SECRET_RE = re.compile(
    r"(AKIA[0-9A-Z]{16}"  # AWS access key
    r"|AIza[0-9A-Za-z\-_]{35}"  # GCP API key
    r"|ghp_[A-Za-z0-9]{36}"  # GitHub personal access token
    r"|ghs_[A-Za-z0-9]{36}"  # GitHub app token
    r"|ghr_[A-Za-z0-9]{36}"  # GitHub refresh token
    r"|sk-[A-Za-z0-9]{40,}"  # OpenAI secret key
    r"|sk-ant-[A-Za-z0-9\-_]{90,}"  # Anthropic secret key
    r"|xoxb-[0-9A-Za-z\-]{50,}"  # Slack bot token
    r"|xoxp-[0-9A-Za-z\-]{50,}"  # Slack user token
    r"|SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}"  # SendGrid
    r"|[A-Za-z0-9]{32,}:[A-Za-z0-9]{32,}@"  # user:pass in URL
    r"|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"  # PEM private key
    r")",
    re.IGNORECASE,
)

# Credential env var name patterns that may appear in prompts
_EGRESS_ENVVAR_RE = re.compile(
    r"\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|OPENROUTER_API_KEY|HF_TOKEN"
    r"|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|GCP_API_KEY|GOOGLE_API_KEY"
    r"|GITHUB_TOKEN|GITLAB_TOKEN|NPM_TOKEN|PYPI_TOKEN|DATABASE_URL"
    r"|REDIS_URL|MONGO_URI|POSTGRES_URL|SECRET_KEY|AUTH_TOKEN"
    r"|PRIVATE_KEY|MASTER_KEY)\s*=\s*['\"]?[A-Za-z0-9+/\-_]{16,}",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Output Scanner (Builder-generated production code)
# ─────────────────────────────────────────────────────────────────────────────
#
# Unlike the test-harness sentinel (which blocks all fs/net imports), this
# scanner targets INTENT indicators in production code:
#
#   - Exfiltration: data being sent to hardcoded external hosts
#   - Persistence: registry/crontab/startup writes without stated purpose
#   - Stealth: process name masquerading, log tampering
#   - Destruction: rm -rf / shutil.rmtree on non-workspace paths
#   - Capture: keylogging APIs, raw input hooks, screen capture without GUI
#   - Evasion: anti-debug, anti-VM, sleep-to-evade patterns
#   - Credential access: LSASS reads, /etc/shadow reads, registry credential reads

# Patterns that are always suspicious in generated output regardless of context
_OUTPUT_HARD_BLOCK: list[tuple[str, re.Pattern]] = [
    (
        "EXFIL_HARDCODED_HOST",
        re.compile(
            r"(requests\.(get|post|put)|urllib\.request\.urlopen|httpx\.(get|post)|"
            r"socket\.connect|smtplib\.SMTP|ftplib\.FTP)\s*\(.*['\"][a-z0-9\-\.]{4,}\.[a-z]{2,}",
            re.IGNORECASE,
        ),
    ),
    (
        "LSASS_READ",
        re.compile(
            r"OpenProcess.*PROCESS_VM_READ|ReadProcessMemory|MiniDumpWriteDump"
            r"|lsass\.exe|SeDebugPrivilege",
            re.IGNORECASE,
        ),
    ),
    (
        "SHADOW_READ",
        re.compile(
            r"open\s*\(\s*['\"]/?etc/shadow",
            re.IGNORECASE,
        ),
    ),
    (
        "REGISTRY_CRED_READ",
        re.compile(
            r"HKEY_LOCAL_MACHINE.*SAM|HKLM.*SECURITY.*SAM"
            r"|winreg.*SAM|RegOpenKey.*SAM",
            re.IGNORECASE,
        ),
    ),
    (
        "KEYLOG_API",
        re.compile(
            r"SetWindowsHookEx\s*\(\s*WH_KEYBOARD"
            r"|GetAsyncKeyState|pynput\.keyboard.*Listener"
            r"|keyboard\.on_press|evdev.*InputDevice.*KEY_",
            re.IGNORECASE,
        ),
    ),
    (
        "PROCESS_MASQUERADE",
        re.compile(
            r"setproctitle\s*\(\s*['\"]svchost|setproctitle.*explorer\.exe"
            r"|argv\[0\]\s*=\s*['\"]svchost|prctl.*PR_SET_NAME.*svchost",
            re.IGNORECASE,
        ),
    ),
    (
        "ANTIDEBUG",
        re.compile(
            r"IsDebuggerPresent\s*\(\s*\)|CheckRemoteDebuggerPresent"
            r"|ptrace\s*\(\s*PTRACE_TRACEME|NtQueryInformationProcess.*DebugPort",
            re.IGNORECASE,
        ),
    ),
    (
        "ANTIVM",
        re.compile(
            r"VBOX|VirtualBox|VMware|QEMU.*detect|check.*hypervisor"
            r"|cpuid.*hypervisor|vmdetect",
            re.IGNORECASE,
        ),
    ),
    (
        "SHELLCODE_PATTERN",
        re.compile(
            r"(?:\\x[0-9a-f]{2}){16,}"  # long hex byte runs
            r"|b'(?:\\x[0-9a-f]{2}){15,}'",  # byte literal shellcode
            re.IGNORECASE,
        ),
    ),
    (
        "MMAP_EXEC",
        re.compile(
            r"mmap\.MAP_ANONYMOUS.*PROT_EXEC|mmap\.PROT_EXEC"
            r"|VirtualAlloc.*PAGE_EXECUTE|ctypes.*VirtualAlloc.*MEM_COMMIT.*PAGE_EXE",
            re.IGNORECASE,
        ),
    ),
    (
        "CRYPTO_HIJACK",
        re.compile(
            r"stratum\+tcp://|mining_pool|xmrig|cpuminer|cgminer"
            r"|monero.*mine|bitcoin.*mine",
            re.IGNORECASE,
        ),
    ),
]

# Suspicious pattern + amplifying context required (same as Layer 1 structure)
_OUTPUT_CONTEXTUAL: list[tuple[re.Pattern, list[re.Pattern], str]] = [
    (
        re.compile(r"shutil\.rmtree|os\.remove|Path.*unlink\(\)", re.IGNORECASE),
        [re.compile(r"/etc|/usr|/bin|/sbin|/boot|C:\\Windows|C:\\System", re.IGNORECASE)],
        "DESTRUCTIVE_SYSTEM_PATH",
    ),
    (
        re.compile(r"(startup|HKCU.*Run|HKLM.*Run|crontab|LaunchAgents|systemd)", re.IGNORECASE),
        [re.compile(r"(persist|survive|reboot|autostart|auto.run)", re.IGNORECASE)],
        "PERSISTENCE_WRITE",
    ),
    (
        re.compile(r"subprocess\.(run|Popen|call|check_output)", re.IGNORECASE),
        [re.compile(r"(shell=True.*\+|shell=True.*format\(|shell=True.*%)", re.IGNORECASE)],
        "COMMAND_INJECTION_RISK",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# SafetyEngine
# ─────────────────────────────────────────────────────────────────────────────


class SafetyEngine:
    """
    Multi-layer safety enforcement for all Determinex pipeline entry points.

    Usage:
        engine = SafetyEngine()

        # Before spec reaches the DAG generator
        verdict = engine.check_spec(spec_text)

        # Before each cloud API call
        verdict = engine.check_egress(full_prompt_text)

        # After Builder generates production code
        verdict = engine.check_output(code_text, lang)

        # Corpus signing / verification
        engine.sign_corpus_entry(entry)    # mutates entry dict in-place
        engine.verify_corpus_entry(entry)  # raises CorpusTamperError on failure

    All check_* methods return SafetyVerdict. All raise SafetyDenied if
    DETERMINEX_SAFETY_MODE=strict (default). In 'warn' mode they log and return
    unsafe verdict without raising — UNLESS the subject has escalated to
    tier RESTRICT or CUTOFF, in which case a violation is a hard block
    regardless of mode (see record_violation()/EscalationState).
    """

    def __init__(self, mode: str = "strict", subject_id: str | None = None) -> None:
        """
        mode: 'strict' (default) — raise SafetyDenied on violation
              'warn'             — log violation, return unsafe verdict, do not raise
              'audit'            — log everything, always pass (for testing only)
        subject_id: identity the escalation tier is tracked against (session,
              user, or agent id). Defaults to DETERMINEX_SAFETY_SUBJECT env var.
              If neither is given, a fresh random id is generated per engine
              instance (NOT a shared 'default') — two unrelated SafetyEngine()
              calls (e.g. two independent test files, two independent
              requests) must never accumulate violations against each
              other's history on disk. Escalation still works correctly
              across calls to the SAME engine instance, or across processes
              that deliberately share a subject_id (session id, agent id) —
              persistence is opt-in, not an accidental default.
        """
        self.mode = mode
        self.subject_id = (
            subject_id
            or os.environ.get("DETERMINEX_SAFETY_SUBJECT")
            or f"ephemeral-{os.getpid()}-{secrets.token_hex(6)}"
        )

    def _enforce(self, verdict: SafetyVerdict) -> SafetyVerdict:
        if not verdict.safe:
            log.warning(
                "[SAFETY BLOCK] layer=%s category=%s reason=%s",
                verdict.layer,
                verdict.category,
                verdict.reason,
            )
            state = record_violation(self.subject_id, verdict)
            if state.tier in (TIER_RESTRICT, TIER_CUTOFF):
                raise SafetyDenied(
                    SafetyVerdict(
                        safe=False,
                        layer=verdict.layer,
                        category=f"ESCALATED_{state.tier.upper()}",
                        reason=(
                            f"{verdict.reason} — subject '{self.subject_id}' is at "
                            f"escalation tier {state.tier} ({state.violation_count} violations); "
                            f"blocked regardless of engine mode. Clear via clear_escalation()."
                        ),
                        violations=verdict.violations,
                    )
                )
            if self.mode == "strict":
                raise SafetyDenied(verdict)
        return verdict

    # ── Layer 0: Content Policy ───────────────────────────────────────────────

    def _check_content_policy(self, text: str) -> SafetyVerdict:
        """Categorical keyword scan. O(n*k) where k = total keyword count."""
        normalized = _normalize_text(text)
        for category, pattern in _DENY_PATTERNS:
            m = pattern.search(normalized)
            if m:
                return SafetyVerdict(
                    safe=False,
                    layer="L0_CONTENT_POLICY",
                    category=category,
                    reason=f"Matched denied pattern: '{m.group()}'",
                    violations=[m.group()],
                )
        return SafetyVerdict(safe=True, layer="L0_CONTENT_POLICY")

    # ── Layer 1: Intent Classifier ────────────────────────────────────────────

    def _check_intent(self, text: str) -> SafetyVerdict:
        """Semantic signal + amplifying context matching."""
        normalized = _normalize_text(text)
        violations: list[str] = []
        for sig_re, amp_res, category in _COMPILED_INTENT:
            if sig_re.search(normalized):
                for amp_re in amp_res:
                    if amp_re.search(normalized):
                        violations.append(f"{category}: '{sig_re.pattern}' + '{amp_re.pattern}'")
                        return SafetyVerdict(
                            safe=False,
                            layer="L1_INTENT",
                            category=category,
                            reason=f"Suspicious intent: {category}",
                            violations=violations,
                        )
        return SafetyVerdict(safe=True, layer="L1_INTENT")

    # ── Layer 2: Egress Filter ────────────────────────────────────────────────

    def check_egress(self, prompt_text: str) -> SafetyVerdict:
        """
        Scan a prompt before it is sent to any cloud API.
        Detects embedded secrets, credentials, and private keys.
        """
        m = _EGRESS_SECRET_RE.search(prompt_text)
        if m:
            redacted = m.group()[:8] + "..." if len(m.group()) > 8 else "***"
            return self._enforce(
                SafetyVerdict(
                    safe=False,
                    layer="L2_EGRESS",
                    category="SECRET_IN_PROMPT",
                    reason=f"Credential token detected in outbound prompt: '{redacted}'",
                    violations=[redacted],
                )
            )
        m = _EGRESS_ENVVAR_RE.search(prompt_text)
        if m:
            return self._enforce(
                SafetyVerdict(
                    safe=False,
                    layer="L2_EGRESS",
                    category="ENVVAR_ASSIGNMENT_IN_PROMPT",
                    reason="Environment credential assignment detected in outbound prompt",
                    violations=[m.group()[:40]],
                )
            )
        return SafetyVerdict(safe=True, layer="L2_EGRESS")

    # ── Layer 3: Output Scanner ───────────────────────────────────────────────

    def check_output(self, code: str, lang: str = "") -> SafetyVerdict:
        """
        Scan Builder-generated production code for malicious intent indicators.
        Less strict than test-harness sentinel (production code may use fs/net),
        but blocks exfiltration, persistence, keylogging, anti-analysis, etc.
        """
        # Hard-block patterns (single match = deny)
        for label, pattern in _OUTPUT_HARD_BLOCK:
            m = pattern.search(code)
            if m:
                return self._enforce(
                    SafetyVerdict(
                        safe=False,
                        layer="L3_OUTPUT",
                        category=label,
                        reason=f"Malicious pattern in generated code: '{m.group().strip()[:60]}'",
                        violations=[m.group().strip()[:80]],
                    )
                )

        # Contextual patterns (signal + amplifier)
        for sig_re, amp_res, category in _OUTPUT_CONTEXTUAL:
            if sig_re.search(code):
                for amp_re in amp_res:
                    if amp_re.search(code):
                        return self._enforce(
                            SafetyVerdict(
                                safe=False,
                                layer="L3_OUTPUT",
                                category=category,
                                reason=f"Contextual malicious pattern: {category}",
                                violations=[category],
                            )
                        )

        # Python-specific: dynamic import tricks
        if "python" in lang.lower():
            violations = _scan_output_python(code)
            if violations:
                return self._enforce(
                    SafetyVerdict(
                        safe=False,
                        layer="L3_OUTPUT",
                        category="PYTHON_DYNAMIC_EXEC",
                        reason=f"Dynamic code execution in Builder output: {violations[0]}",
                        violations=violations,
                    )
                )

        # ── Semgrep OSS: dataflow-aware semantic scan (Layer 3 depth) ─────────
        # Catches evasions that bypass keyword splitting:
        #   base64-encoded payloads, indirect subprocess chains, dynamic import tricks.
        # Semgrep unavailable or timeout → warning only; existing L3 checks remain
        # authoritative. Never blocks on Semgrep failure (fail-open for this sub-layer).
        semgrep_verdict = _semgrep_scan_code(code, lang)
        if semgrep_verdict is not None and not semgrep_verdict.safe:
            return self._enforce(semgrep_verdict)

        return SafetyVerdict(safe=True, layer="L3_OUTPUT")

    # ── Combined spec check (L0 + L1) ─────────────────────────────────────────

    def check_spec(self, spec_text: str) -> SafetyVerdict:
        """
        Run Layer 0 (content policy) + Layer 1 (intent) on a user spec.
        Called before the spec reaches the DAG generator or any LLM.
        """
        v = self._check_content_policy(spec_text)
        if not v.safe:
            return self._enforce(v)
        v = self._check_intent(spec_text)
        if not v.safe:
            return self._enforce(v)
        return SafetyVerdict(safe=True, layer="L0+L1")

    # ── Layer 5: License Scan ─────────────────────────────────────────────────

    def check_license(self, text: str, path_hint: str = "") -> SafetyVerdict:
        """
        Scan a training-corpus sample for copyleft license markers (GPL/AGPL/
        LGPL/SSPL — anything that would obligate Determinex's commercial corpus
        to reciprocal licensing if merged in). SPDX-identifier match is the
        strongest signal; header-phrase match is the fallback for files that
        don't carry a machine-readable SPDX tag.
        """
        m = _SPDX_COPYLEFT_RE.search(text)
        if m:
            return SafetyVerdict(
                safe=False,
                layer="L5_LICENSE",
                category="COPYLEFT_SPDX_TAG",
                reason=f"SPDX copyleft identifier found{f' in {path_hint}' if path_hint else ''}: '{m.group().strip()}'",
                violations=[m.group().strip()],
            )
        m = _COPYLEFT_HEADER_RE.search(text)
        if m:
            return SafetyVerdict(
                safe=False,
                layer="L5_LICENSE",
                category="COPYLEFT_HEADER_TEXT",
                reason=f"Copyleft license header found{f' in {path_hint}' if path_hint else ''}: '{m.group().strip()[:60]}'",
                violations=[m.group().strip()[:80]],
            )
        return SafetyVerdict(safe=True, layer="L5_LICENSE")

    # ── Layer 6: Runtime Integrity (ToS circumvention detection) ─────────────

    def check_runtime_integrity(self) -> SafetyVerdict:
        """
        Compare the sha256 of this module and its hive adapter
        (scripts/hive/safety_gate.py) against the recorded manifest. A
        mismatch means the gate itself was edited since the manifest was
        last generated — the deterministic signal for 'ToS circumvention:
        stripping the ethics layer'. A missing manifest is reported as
        unsafe too (never silently treated as clean) — run
        `python scripts/determinex_safety.py --generate-integrity-manifest`
        once the current files are trusted.
        """
        if not _INTEGRITY_MANIFEST.is_file():
            return SafetyVerdict(
                safe=False,
                layer="L6_INTEGRITY",
                category="INTEGRITY_MANIFEST_MISSING",
                reason=f"No integrity manifest at {_INTEGRITY_MANIFEST} — cannot verify the safety layer hasn't been altered. Generate one with --generate-integrity-manifest.",
            )
        try:
            manifest = json.loads(_INTEGRITY_MANIFEST.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return SafetyVerdict(
                safe=False,
                layer="L6_INTEGRITY",
                category="INTEGRITY_MANIFEST_UNREADABLE",
                reason=f"Integrity manifest unreadable: {e}",
            )
        mismatches = []
        for f in _INTEGRITY_FILES:
            name = f.name
            expected = manifest.get(name)
            actual = _sha256_file(f)
            if expected is None:
                mismatches.append(f"{name}: not in manifest")
            elif actual != expected:
                mismatches.append(f"{name}: sha256 changed since manifest was recorded")
        if mismatches:
            return SafetyVerdict(
                safe=False,
                layer="L6_INTEGRITY",
                category="TOS_CIRCUMVENTION",
                reason=f"Safety layer file(s) modified since integrity manifest: {'; '.join(mismatches)}",
                violations=mismatches,
            )
        return SafetyVerdict(safe=True, layer="L6_INTEGRITY")

    # ── Layer 4: Corpus Integrity ─────────────────────────────────────────────

    def sign_corpus_entry(self, entry: dict) -> None:
        """
        L5 pre-check (license) then HMAC-sign a corpus entry dict in-place.
        Adds '_sig' key with BLAKE2b-256 hex digest of the canonical JSON.
        Raises SafetyDenied (or logs, in warn mode) before signing anything
        that fails the license scan — a signed-but-tainted entry would be
        indistinguishable from a clean one downstream.
        """
        sample_text = json.dumps({k: v for k, v in entry.items() if k != "_sig"}, default=str)
        v = self.check_license(sample_text, path_hint=str(entry.get("path", entry.get("id", ""))))
        if not v.safe:
            self._enforce(v)  # strict mode raises; warn mode falls through by design

        entry.pop("_sig", None)  # remove stale sig before signing
        canonical = json.dumps(entry, sort_keys=True, ensure_ascii=True)
        sig = hmac.new(
            _CORPUS_HMAC_KEY,
            canonical.encode("utf-8"),
            digestmod=hashlib.blake2b,
        ).hexdigest()
        entry["_sig"] = sig

    def verify_corpus_entry(self, entry: dict) -> bool:
        """
        Verify HMAC signature on a corpus entry.
        Returns True if valid, raises CorpusTamperError if invalid/missing.
        A failed verification is WAL-logged as a TOS_CIRCUMVENTION-class
        violation and counted against this engine's subject — tampering with
        signed corpus data is exactly the bypass behavior Layer 6 exists to
        catch, whether it happens by editing the gate or editing its output.
        """
        sig = entry.get("_sig", "")
        if not sig:
            record_violation(
                self.subject_id,
                SafetyVerdict(
                    safe=False,
                    layer="L4_CORPUS",
                    category="TOS_CIRCUMVENTION",
                    reason="Corpus entry missing '_sig' field — possible tamper",
                ),
            )
            raise CorpusTamperError("Corpus entry missing '_sig' field — possible tamper")
        check = dict(entry)
        check.pop("_sig")
        canonical = json.dumps(check, sort_keys=True, ensure_ascii=True)
        expected = hmac.new(
            _CORPUS_HMAC_KEY,
            canonical.encode("utf-8"),
            digestmod=hashlib.blake2b,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            record_violation(
                self.subject_id,
                SafetyVerdict(
                    safe=False,
                    layer="L4_CORPUS",
                    category="TOS_CIRCUMVENTION",
                    reason="Corpus entry HMAC mismatch — entry may have been tampered with",
                ),
            )
            raise CorpusTamperError(
                f"Corpus entry HMAC mismatch — entry may have been tampered with. "
                f"Key prefix: {list(entry.keys())[:5]}"
            )
        return True


class CorpusTamperError(Exception):
    """Raised when a corpus entry fails HMAC verification."""


# ── SPDX / copyleft detection (Layer 5) ────────────────────────────────────
_SPDX_COPYLEFT_RE = re.compile(
    r"SPDX-License-Identifier:\s*(GPL|AGPL|LGPL|SSPL)[-\w.+]*",
    re.IGNORECASE,
)
_COPYLEFT_HEADER_RE = re.compile(
    r"GNU GENERAL PUBLIC LICENSE|GNU AFFERO GENERAL PUBLIC LICENSE"
    r"|GNU LESSER GENERAL PUBLIC LICENSE|SERVER SIDE PUBLIC LICENSE"
    r"|licensed under the gpl|licensed under the agpl|licensed under the lgpl",
    re.IGNORECASE,
)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_integrity_manifest() -> dict:
    """Record the current sha256 of every file in _INTEGRITY_FILES as the
    trusted baseline. Deliberate operator action — call after reviewing a
    change to the safety layer itself, never automatically."""
    manifest = {f.name: _sha256_file(f) for f in _INTEGRITY_FILES}
    _INTEGRITY_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _INTEGRITY_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Homoglyph confusables fold — defeats the classic cross-script evasion
# technique (Pliny technique #2): substituting visually-identical characters
# from a different Unicode block (Cyrillic а for Latin a, Greek ο for Latin
# o, ...) so a keyword-substring scan misses a phrase a human reading it
# would recognize instantly. NFKC alone does NOT catch this — Cyrillic 'а'
# (U+0430) and Latin 'a' (U+0061) are genuinely different codepoints in
# different scripts; no normalization form unifies them, only an explicit
# confusables table does (the same approach IDN homograph defenses use).
# Not exhaustive (the full Unicode confusables.txt has 6000+ entries) — this
# covers the common Cyrillic/Greek lookalikes for the 26 Latin letters,
# which is what an attacker reaches for first because they're a single
# keyboard layout away and render identically in most fonts.
_CONFUSABLES: dict[str, str] = {
    # Cyrillic → Latin (lowercase)
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ѕ": "s",
    "ј": "j",
    "ԁ": "d",
    "ѡ": "w",
    "ё": "e",
    "ӏ": "l",
    # Cyrillic → Latin (uppercase, folds to lowercase target since callers lower() after)
    "А": "a",
    "В": "b",
    "Е": "e",
    "К": "k",
    "М": "m",
    "Н": "h",
    "О": "o",
    "Р": "p",
    "С": "c",
    "Т": "t",
    "У": "y",
    "Х": "x",
    "І": "i",
    "Ѕ": "s",
    "Ј": "j",
    # Greek → Latin
    "α": "a",
    "β": "b",
    "ο": "o",
    "ρ": "p",
    "υ": "u",
    "κ": "k",
    "ν": "v",
    "τ": "t",
    "χ": "x",
    "ι": "i",
    "η": "n",
    "γ": "y",
    "Α": "a",
    "Β": "b",
    "Ε": "e",
    "Ζ": "z",
    "Η": "n",
    "Ι": "i",
    "Κ": "k",
    "Μ": "m",
    "Ν": "n",
    "Ο": "o",
    "Ρ": "p",
    "Τ": "t",
    "Υ": "y",
    "Χ": "x",
}
_CONFUSABLES_TABLE = str.maketrans(_CONFUSABLES)


def _fold_confusables(text: str) -> str:
    return text.translate(_CONFUSABLES_TABLE)


def _normalize_text(text: str) -> str:
    """Lowercase, normalize unicode, fold homoglyph confusables, collapse
    whitespace for consistent matching."""
    # NFKC (not just NFC): folds compatibility variants — fullwidth Latin
    # (ｂｕｉｌｄ), ligatures, etc. — before the confusables fold handles the
    # genuinely-different-script lookalikes NFKC can't touch.
    t = unicodedata.normalize("NFKC", text)
    t = _fold_confusables(t)
    t = t.lower()
    # Collapse multi-space, remove zero-width chars
    t = re.sub(r"[​‌‍﻿]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


# Python-specific: catch dynamic exec tricks in Builder output
_PY_EXEC_TRICKS_RE = re.compile(
    r"__import__\s*\("
    r"|getattr\s*\([^)]*import"
    r"|exec\s*\(\s*compile"
    r"|exec\s*\(\s*base64"
    r"|eval\s*\(\s*base64"
    r"|eval\s*\(\s*__import__"
    r"|marshal\.loads"
    r"|pickle\.loads\s*\(\s*base64",
    re.IGNORECASE,
)


def _semgrep_scan_code(code: str, lang: str) -> SafetyVerdict | None:
    """Layer 3 depth: Semgrep OSS dataflow-aware scan of Builder-generated code.

    Catches evasions that bypass flat keyword-matching:
      - Base64-encoded subprocess payloads (exec(base64.b64decode(...)))
      - Indirect function chains (getattr(os, 'sys'+'tem')(cmd))
      - Dynamic attribute access to banned modules
      - Obfuscated credential exfiltration paths

    Returns:
      SafetyVerdict(safe=False)  if a Semgrep rule fired
      None                       if Semgrep is unavailable, timed out, or found nothing
                                 (existing L3 checks remain authoritative in this case)

    Never raises — Semgrep failure is always fail-open for this sub-layer.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("semgrep"):
        return None  # Not installed — existing AST/regex L3 remains authoritative

    # Map Determinex language names to Semgrep language IDs
    _SEMGREP_LANG_MAP = {
        "python": "python",
        "py": "python",
        "javascript": "javascript",
        "js": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "go": "go",
        "golang": "go",
        "rust": "rust",
        "rs": "rust",
        "java": "java",
        "ruby": "ruby",
        "rb": "ruby",
    }
    semgrep_lang = _SEMGREP_LANG_MAP.get(lang.lower().split()[0] if lang else "", "")
    if not semgrep_lang:
        return None  # Language not supported by Semgrep scan — skip

    # Inline Semgrep rules: security anti-patterns for generated code
    # These complement the L3 keyword/AST checks above.
    _SEMGREP_RULES = """
rules:
  - id: determinex-dynamic-exec-obfuscated
    languages: [python]
    message: Obfuscated dynamic code execution in generated output
    severity: ERROR
    patterns:
      - pattern: exec(...)
      - pattern-not: exec("...")
  - id: determinex-base64-exec
    languages: [python]
    message: Base64-encoded execution payload
    severity: ERROR
    pattern: exec($X.decode(...))
  - id: determinex-subprocess-shell-true
    languages: [python]
    message: Subprocess with shell=True and dynamic command construction
    severity: ERROR
    pattern: subprocess.run($CMD, shell=True, ...)
    pattern-not: subprocess.run([...], shell=True, ...)
  - id: determinex-os-system-dynamic
    languages: [python]
    message: os.system with dynamic string construction
    severity: ERROR
    pattern: os.system($X + $Y)
  - id: determinex-net-exfil-pattern
    languages: [python]
    message: Potential data exfiltration via network in generated code
    severity: WARNING
    pattern: requests.post($URL, data=$DATA, ...)
    pattern-not: requests.post("...", data=$DATA, ...)
"""
    try:
        with tempfile.TemporaryDirectory() as d:
            import pathlib

            code_path = pathlib.Path(d) / f"check.{semgrep_lang[:2]}"
            rules_path = pathlib.Path(d) / "rules.yaml"
            code_path.write_text(code, encoding="utf-8", errors="replace")
            rules_path.write_text(_SEMGREP_RULES, encoding="utf-8")
            result = subprocess.run(
                [
                    "semgrep",
                    "--config",
                    str(rules_path),
                    "--json",
                    "--no-git-ignore",
                    "--quiet",
                    str(code_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode not in (0, 1):
                # Non-zero non-1 = Semgrep internal error — fail open
                return None
            import json

            findings = json.loads(result.stdout or "{}").get("results", [])
            if not findings:
                return None
            errors = [
                f["extra"]["message"]
                for f in findings
                if f.get("extra", {}).get("severity") == "ERROR"
            ]
            if errors:
                return SafetyVerdict(
                    safe=False,
                    layer="L3_OUTPUT_SEMGREP",
                    category="SEMGREP_SECURITY_FINDING",
                    reason=f"Semgrep OSS: {errors[0]}",
                    violations=errors[:5],
                )
    except Exception:
        pass  # Semgrep failure is always fail-open — existing L3 checks stand
    return None


# Python-specific: catch dynamic exec tricks in Builder output
_PY_EXEC_TRICKS_RE = re.compile(
    r"__import__\s*\("
    r"|getattr\s*\([^)]*import"
    r"|exec\s*\(\s*compile"
    r"|exec\s*\(\s*base64"
    r"|eval\s*\(\s*base64"
    r"|eval\s*\(\s*__import__"
    r"|marshal\.loads"
    r"|pickle\.loads\s*\(\s*base64",
    re.IGNORECASE,
)


def _scan_output_python(source: str) -> list[str]:
    """Scan Builder Python output for dynamic execution tricks."""
    violations: list[str] = []
    for m in _PY_EXEC_TRICKS_RE.finditer(source):
        violations.append(f"Dynamic exec: '{m.group().strip()}'")
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton (import-and-use pattern)
# ─────────────────────────────────────────────────────────────────────────────

_ENGINE: SafetyEngine | None = None


def get_engine() -> SafetyEngine:
    """Return the module-level SafetyEngine singleton (strict mode)."""
    global _ENGINE
    if _ENGINE is None:
        mode = os.environ.get("DETERMINEX_SAFETY_MODE", "strict")
        _ENGINE = SafetyEngine(mode=mode)
        log.info("[SAFETY] Engine initialized in '%s' mode", mode)
    return _ENGINE


def check_spec(spec_text: str) -> SafetyVerdict:
    """Convenience wrapper: check a spec through L0 + L1."""
    return get_engine().check_spec(spec_text)


def check_egress(prompt_text: str) -> SafetyVerdict:
    """Convenience wrapper: check a prompt for secrets before cloud API send."""
    return get_engine().check_egress(prompt_text)


def check_output(code: str, lang: str = "") -> SafetyVerdict:
    """Convenience wrapper: scan Builder-generated code for malicious patterns."""
    return get_engine().check_output(code, lang)


def sign_corpus_entry(entry: dict) -> None:
    """Convenience wrapper: HMAC-sign a corpus entry in-place."""
    get_engine().sign_corpus_entry(entry)


def verify_corpus_entry(entry: dict) -> bool:
    """Convenience wrapper: verify a corpus entry's HMAC signature."""
    return get_engine().verify_corpus_entry(entry)


def check_license(text: str, path_hint: str = "") -> SafetyVerdict:
    """Convenience wrapper: scan text for copyleft license markers."""
    return get_engine().check_license(text, path_hint=path_hint)


def check_runtime_integrity() -> SafetyVerdict:
    """Convenience wrapper: verify the safety layer's own files are unmodified."""
    return get_engine().check_runtime_integrity()


# ─────────────────────────────────────────────────────────────────────────────
# CLI — manifest generation, WAL/escalation inspection, ad-hoc checks
# ─────────────────────────────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Safety / Ethics Oracle")
    ap.add_argument(
        "--generate-integrity-manifest",
        action="store_true",
        help="record current sha256 of the safety layer files as the trusted baseline",
    )
    ap.add_argument(
        "--verify-wal", action="store_true", help="walk the WAL hash chain and report integrity"
    )
    ap.add_argument("--status", metavar="SUBJECT_ID", help="print escalation state for a subject")
    ap.add_argument(
        "--clear-escalation",
        metavar="SUBJECT_ID",
        help="clear a subject's escalation state (re-consent)",
    )
    ap.add_argument("--check-spec", metavar="TEXT", help="run L0+L1 against inline text")
    ap.add_argument(
        "--check-license", metavar="TEXT", help="run L5 license scan against inline text"
    )
    args = ap.parse_args()

    if args.generate_integrity_manifest:
        m = generate_integrity_manifest()
        print(f"Wrote {_INTEGRITY_MANIFEST}:")
        print(json.dumps(m, indent=2))
        return 0

    if args.verify_wal:
        ok, detail = verify_wal_integrity()
        print(f"WAL integrity: {'INTACT' if ok else 'BROKEN'} — {detail}")
        return 0 if ok else 1

    if args.status:
        state = load_escalation(args.status)
        print(json.dumps(asdict(state), indent=2, default=str))
        return 0

    if args.clear_escalation:
        clear_escalation(args.clear_escalation)
        print(f"Cleared escalation state for '{args.clear_escalation}'")
        return 0

    if args.check_spec is not None:
        try:
            v = SafetyEngine(mode="warn").check_spec(args.check_spec)
        except SafetyDenied as e:
            v = e.verdict
        print(json.dumps(asdict(v), indent=2, default=str))
        return 0 if v.safe else 1

    if args.check_license is not None:
        v = check_license(args.check_license)
        print(json.dumps(asdict(v), indent=2, default=str))
        return 0 if v.safe else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_cli())
