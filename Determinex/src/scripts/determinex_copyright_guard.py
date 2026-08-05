"""
Determinex Provenance Guard — Copyright Detection + Attribution Auto-Tagging

Two complementary systems in one module:

1. COPYRIGHT GUARD (existing)
   Detects whether generated output reproduces a substantial contiguous chunk
   of an identifiable registered work. Flags and logs.

   Provenance mode (DETERMINEX_PROVENANCE_MODE env var):
     "observe" (default) — log attribution tags, never block corpus ingestion,
                           never raise. Sidecar-only; compiler is the only oracle.
     "enforce"           — verbatim hits on non-permissive-licensed reference sources
                           ALSO produce CopyrightAlerts. Use only on internal
                           proprietary materials where blocking is required.
   The mode flag is a documentation-level boundary: in observe mode the provenance
   guard is explicitly NOT wired into training rewards or corpus filtering.
   In enforce mode callers may gate on blocks_corpus_ingestion.

2. ATTRIBUTION TAGGER (new)
   Detects inspiration/derivation from registered reference sources using
   bigram-level similarity. Any source type (open_source, academic, patent,
   commercial, proprietary, private, unknown) can be registered. When
   similarity exceeds a threshold, an AttributionTag is generated — giving
   direct recognition to the inspiration of looped output.

   Three match tiers:
     "verbatim_reproduction" — ≥50 consecutive token match (copyright territory)
     "substantial_similarity" — ≥30 token match OR ≥25% bigram Jaccard overlap
     "inspiration"            — ≥15% bigram Jaccard overlap (softer signal)

   For every generated output, check_provenance() returns a ProvenanceReport
   that bundles copyright alerts + attribution tags + a formatted reference
   block ready to append to output as comments or markdown.

Design principles (unchanged from original):
- Works on registered works only. Does not crawl the internet.
- Findings produce audit records appended to append-only logs. Never modifies
  corpus records or training weights. Compiler is the only oracle on the code path.
- False negatives acceptable; false positives costly. Thresholds set conservatively.

Usage:
    from determinex_copyright_guard import get_guard

    g = get_guard()

    # Register a protected work (verbatim reproduction guard, existing API)
    g.register("corpus/protected/artist_A_lyrics.txt", label="Artist A — Album 1")

    # Register an inspiration/reference source (new)
    g.register_reference(
        source="corpus/references/ripgrep_readme.txt",
        label="ripgrep — BurntSushi / Andrew Gallant",
        source_type="open_source",
        license="MIT",
        url="https://github.com/BurntSushi/ripgrep",
        authors=["Andrew Gallant"],
        year=2015,
    )

    # Full provenance check (new — returns ProvenanceReport)
    report = g.check_provenance(generated_text, task_id="pb_run_001")
    if report.has_copyright_violation:
        raise RuntimeError("verbatim reproduction detected")
    if report.has_attributions:
        output += "\\n" + report.format_reference_block(style="code_comment")
        g.log_attribution(report)

    # Legacy API still works (returns first CopyrightAlert or None)
    alert = g.check(generated_text, task_id="pb_run_001")
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_AUDIT_LOG = Path(
    os.environ.get(
        "DETERMINEX_COPYRIGHT_AUDIT_LOG",
        "logs/copyright_guard/audit.jsonl",
    )
)
_ATTRIBUTION_LOG = Path(
    os.environ.get(
        "DETERMINEX_ATTRIBUTION_LOG",
        "logs/copyright_guard/attribution.jsonl",
    )
)

# Minimum consecutive-token run for verbatim reproduction (copyright territory)
_MIN_MATCH_TOKENS = int(os.environ.get("DETERMINEX_COPYRIGHT_MIN_TOKENS", "50"))
# Minimum token run for "substantial similarity" tier
_SUBSTANTIAL_TOKEN_THRESHOLD = int(os.environ.get("DETERMINEX_SUBSTANTIAL_TOKENS", "30"))
# Bigram Jaccard threshold for "substantial similarity"
_SUBSTANTIAL_BIGRAM_THRESHOLD = float(os.environ.get("DETERMINEX_SUBSTANTIAL_BIGRAM", "0.25"))
# Bigram Jaccard threshold for "inspiration" (soft signal)
_INSPIRATION_BIGRAM_THRESHOLD = float(os.environ.get("DETERMINEX_INSPIRATION_BIGRAM", "0.15"))

# Provenance sidecar mode.
# "observe" (default): log attribution tags, never gate corpus ingestion, never raise.
# "enforce":           verbatim hits on non-permissive references also produce
#                      CopyrightAlerts and set blocks_corpus_ingestion=True.
_OBSERVE_ONLY: bool = os.environ.get("DETERMINEX_PROVENANCE_MODE", "observe").lower() != "enforce"

# SPDX identifiers for permissive licenses.
# Verbatim reuse of permissive-licensed material WITH attribution is legally expected
# and is the system working correctly — produces AttributionTag, never CopyrightAlert.
_LICENSE_PERMISSIVE = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSD-4-Clause",
        "ISC",
        "Unlicense",
        "0BSD",
        "CC0-1.0",
        "Zlib",
        "WTFPL",
        "MIT OR Unlicense",
        "MIT/Apache-2.0",
    }
)
# SPDX identifiers for copyleft licenses.
# Verbatim reuse triggers an attribution obligation and a warning; in enforce mode also a CopyrightAlert.
_LICENSE_COPYLEFT = frozenset(
    {
        "GPL-2.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "MPL-2.0",
        "EUPL-1.2",
    }
)

# Tokens too common in generated code to carry meaningful attribution signal.
# Bigrams composed entirely of stopword pairs are filtered before Jaccard comparison
# to reduce false positives on argparse scaffolds, error-handling idioms, test boilerplate.
# Scope: calibrated against 47 PB locked tools (see scripts/pb_provenance_calibrate.py).
_BIGRAM_STOPWORDS = frozenset(
    {
        # Python / general programming keywords
        "import",
        "from",
        "def",
        "class",
        "return",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "try",
        "except",
        "with",
        "as",
        "in",
        "is",
        "not",
        "and",
        "or",
        "pass",
        "raise",
        "yield",
        "lambda",
        "self",
        "cls",
        "none",
        "true",
        "false",
        "print",
        "type",
        "int",
        "str",
        "bool",
        "dict",
        "list",
        "set",
        "tuple",
        "len",
        "range",
        "any",
        "all",
        "open",
        "read",
        "write",
        "close",
        # Common identifiers in any project
        "args",
        "kwargs",
        "sys",
        "os",
        "re",
        "json",
        "path",
        "main",
        "log",
        "logger",
        "err",
        "error",
        "msg",
        "result",
        "data",
        "value",
        "name",
        "key",
        "val",
        "out",
        "output",
        "input",
        "text",
        "code",
        "parser",
        "argv",
        "help",
        "description",
        "add",
        "argument",
        # Shell / build ubiquitous tokens
        "echo",
        "exit",
        "mkdir",
        "chmod",
        "cd",
        "cp",
        "mv",
        "rm",
        "bash",
        "sh",
        "exec",
        "eval",
        "run",
        "build",
        "install",
        # English function words that appear in comments
        "the",
        "a",
        "an",
        "to",
        "of",
        "be",
        "by",
        "at",
        "on",
    }
)

# Valid source_type values and their display labels
_SOURCE_TYPE_LABELS: dict[str, str] = {
    "open_source": "open source",
    "academic": "academic paper",
    "patent": "patent",
    "commercial": "commercial software",
    "proprietary": "proprietary IP",
    "private": "private source",
    "unknown": "source",
}

VALID_SOURCE_TYPES = set(_SOURCE_TYPE_LABELS)
VALID_MATCH_TYPES = {"verbatim_reproduction", "substantial_similarity", "inspiration"}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RegisteredWork:
    """A work registered for verbatim-reproduction protection (copyright guard)."""

    label: str
    tokens: list[str]


@dataclass
class ReferenceSource:
    """
    A source registered for attribution/inspiration tracking.

    source_type values:
      "open_source"  — OSS-licensed code or content (include SPDX in license)
      "academic"     — Academic paper, preprint, thesis, conference proceedings
      "patent"       — Patent document (include patent number in url/label)
      "commercial"   — Commercial product or service
      "proprietary"  — Closed/proprietary IP not publicly licensed
      "private"      — Private/confidential material (internal only)
      "unknown"      — License or status not determined
    """

    label: str
    tokens: list[str]
    bigrams: frozenset  # full bigrams — precomputed at register time
    filtered_bigrams: frozenset  # stopword-filtered bigrams — used for Jaccard comparison
    source_type: str = "unknown"
    license: str = "unknown"
    url: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None


@dataclass
class CopyrightAlert:
    """Verbatim reproduction of a protected work detected."""

    task_id: str
    work_label: str
    match_length: int
    output_excerpt: str
    source_excerpt: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __str__(self) -> str:
        return (
            f"[COPYRIGHT ALERT] task={self.task_id} work='{self.work_label}' "
            f"match_tokens={self.match_length}\n"
            f"  output: {self.output_excerpt!r}\n"
            f"  source: {self.source_excerpt!r}"
        )

    def to_dict(self) -> dict:
        return {
            "event": "copyright_displacement",
            "task_id": self.task_id,
            "work_label": self.work_label,
            "match_length": self.match_length,
            "output_excerpt": self.output_excerpt,
            "source_excerpt": self.source_excerpt,
            "timestamp": self.timestamp,
        }


@dataclass
class AttributionTag:
    """
    A source that influenced or inspired generated output.

    match_type:
      "verbatim_reproduction" — ≥MIN_MATCH_TOKENS consecutive token match
      "substantial_similarity" — ≥SUBSTANTIAL_TOKEN_THRESHOLD tokens or ≥SUBSTANTIAL_BIGRAM_THRESHOLD bigram Jaccard
      "inspiration"           — ≥INSPIRATION_BIGRAM_THRESHOLD bigram Jaccard
    """

    task_id: str
    source_label: str
    source_type: str
    license: str
    url: str
    authors: list[str]
    year: int | None
    match_type: str
    similarity_score: float  # 0.0–1.0 (token overlap ratio or bigram Jaccard)
    excerpt: str  # excerpt from output showing the match
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def format_citation(self) -> str:
        """One-line citation string for embedding in output."""
        type_label = _SOURCE_TYPE_LABELS.get(self.source_type, "source")
        author_str = ", ".join(self.authors) if self.authors else ""
        year_str = f" ({self.year})" if self.year else ""
        author_year = f" — {author_str}{year_str}" if author_str else year_str
        url_str = f" | {self.url}" if self.url else ""
        license_str = f" [{self.license}]" if self.license not in ("", "unknown") else ""
        match_pct = f"{self.similarity_score * 100:.1f}%"
        return (
            f"[{type_label}{license_str}] {self.source_label}"
            f"{author_year}{url_str}  ({self.match_type}, {match_pct} overlap)"
        )

    def to_dict(self) -> dict:
        return {
            "event": "attribution_tag",
            "task_id": self.task_id,
            "source_label": self.source_label,
            "source_type": self.source_type,
            "license": self.license,
            "url": self.url,
            "authors": self.authors,
            "year": self.year,
            "match_type": self.match_type,
            "similarity_score": round(self.similarity_score, 4),
            "excerpt": self.excerpt,
            "timestamp": self.timestamp,
        }


@dataclass
class ProvenanceReport:
    """
    Combined result of copyright + attribution checks on a single generated output.

    Always safe to log and append reference blocks from.
    Never raises; invalid states produce empty lists, not exceptions.
    """

    task_id: str
    copyright_alerts: list[CopyrightAlert] = field(default_factory=list)
    attribution_tags: list[AttributionTag] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def has_copyright_violation(self) -> bool:
        """
        True when a genuine copyright concern was detected.

        In observe mode (default): only fires for protected-works hits (Pass 1).
          Reference-source verbatim matches on permissive OSS (MIT, Apache-2.0, etc.)
          never set this — those produce AttributionTags and are the system working.
        In enforce mode: also fires for verbatim hits on non-permissive reference sources.
        """
        return bool(self.copyright_alerts)

    @property
    def blocks_corpus_ingestion(self) -> bool:
        """
        True only in enforce mode when a genuine copyright violation was detected.
        Always False in observe mode (default) — provenance sidecar never gates ingestion;
        the compiler is the only oracle on the training-corpus path.
        """
        if _OBSERVE_ONLY:
            return False
        return bool(self.copyright_alerts)

    @property
    def has_attributions(self) -> bool:
        return bool(self.attribution_tags)

    @property
    def is_clean(self) -> bool:
        """True when no copyright violations and no attributions (completely novel output)."""
        return not self.copyright_alerts and not self.attribution_tags

    def format_reference_block(self, style: str = "markdown") -> str:
        """
        Render all attributions as a formatted reference block.

        style:
          "markdown"      — ## Attribution section (for .md files and docs)
          "code_comment"  — # comment lines (for appending to generated code)
          "json"          — raw JSON string of the tag list
        """
        if not self.attribution_tags and not self.copyright_alerts:
            return ""

        tags = list(self.attribution_tags)

        # Copyright-alerted works are also added as attribution tags with verbatim match type
        alerted_labels = {t.source_label for t in tags}
        for alert in self.copyright_alerts:
            if alert.work_label not in alerted_labels:
                tags.append(
                    AttributionTag(
                        task_id=self.task_id,
                        source_label=alert.work_label,
                        source_type="unknown",
                        license="unknown",
                        url="",
                        authors=[],
                        year=None,
                        match_type="verbatim_reproduction",
                        similarity_score=min(1.0, alert.match_length / max(_MIN_MATCH_TOKENS, 1)),
                        excerpt=alert.output_excerpt,
                    )
                )

        if not tags:
            return ""

        if style == "json":
            return json.dumps([t.to_dict() for t in tags], indent=2, ensure_ascii=False)

        lines: list[str] = []

        if style == "code_comment":
            lines.append("# ── Attribution ─────────────────────────────────────────")
            for tag in tags:
                lines.append(f"#   {tag.format_citation()}")
            lines.append("# ─────────────────────────────────────────────────────────")
        else:  # markdown
            lines.append("## Attribution")
            lines.append("")
            for tag in tags:
                type_label = _SOURCE_TYPE_LABELS.get(tag.source_type, "source")
                lines.append(f"- **[{type_label}]** {tag.source_label}")
                if tag.authors:
                    lines.append(
                        f"  Authors: {', '.join(tag.authors)}"
                        + (f" ({tag.year})" if tag.year else "")
                    )
                if tag.license not in ("", "unknown"):
                    lines.append(f"  License: {tag.license}")
                if tag.url:
                    lines.append(f"  URL: {tag.url}")
                lines.append(
                    f"  Recognition: {tag.match_type} ({tag.similarity_score * 100:.1f}% overlap)"
                )
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "copyright_alerts": [a.to_dict() for a in self.copyright_alerts],
            "attribution_tags": [t.to_dict() for t in self.attribution_tags],
        }


# ---------------------------------------------------------------------------
# Tokenization and similarity helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """NFC-normalize, lowercase, split on whitespace/punctuation boundaries."""
    text = unicodedata.normalize("NFC", text).lower()
    return re.findall(r"[a-z0-9_]+", text)


def _bigrams(tokens: list[str]) -> frozenset:
    """Compute bigram frozenset from token list."""
    return frozenset(zip(tokens, tokens[1:]))


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Jaccard similarity between two frozensets."""
    if not a and not b:
        return 0.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def _longest_common_run(a: list[str], b: list[str]) -> tuple[int, int, int]:
    """
    Return (length, start_in_a, start_in_b) of the longest contiguous token
    run shared between sequences a and b.

    Rolling two-row DP: O(min(|a|, |b|)) memory.
    """
    if not a or not b:
        return 0, 0, 0

    if len(a) < len(b):
        a, b = b, a
        swapped = True
    else:
        swapped = False

    n, m = len(a), len(b)
    best_len = best_i = best_j = 0
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best_len:
                    best_len = curr[j]
                    best_i, best_j = i, j
            else:
                curr[j] = 0
        prev, curr = curr, prev
        for k in range(m + 1):
            curr[k] = 0

    if swapped:
        return best_len, best_j - best_len, best_i - best_len
    return best_len, best_i - best_len, best_j - best_len


def _tokens_to_excerpt(tokens: list[str], start: int, length: int, max_chars: int = 200) -> str:
    return " ".join(tokens[start : start + length])[:max_chars]


def _license_tier(license_str: str) -> str:
    """Return 'permissive' | 'copyleft' | 'proprietary' | 'unknown'."""
    norm = (license_str or "").strip()
    if not norm or norm.lower() in ("unknown", ""):
        return "unknown"
    if norm.lower() in ("proprietary", "all rights reserved"):
        return "proprietary"
    if norm in _LICENSE_PERMISSIVE:
        return "permissive"
    if norm in _LICENSE_COPYLEFT:
        return "copyleft"
    # Handle compound expressions like "MIT OR Unlicense" or "MIT/Apache-2.0"
    for tok in re.split(r"[\s/,|]+", norm):
        if tok in _LICENSE_PERMISSIVE:
            return "permissive"
        if tok in _LICENSE_COPYLEFT:
            return "copyleft"
    return "unknown"


def _filtered_bigrams(tokens: list[str]) -> frozenset:
    """Bigrams with stopwords removed — more precise inspiration signal for code."""
    meaningful = [t for t in tokens if t not in _BIGRAM_STOPWORDS and len(t) > 2]
    return frozenset(zip(meaningful, meaningful[1:]))


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class CopyrightGuard:
    """
    Maintains a registry of protected works and reference sources.

    - Protected works: verbatim reproduction detection (copyright guard)
    - Reference sources: inspiration/derivation attribution tracking

    Thread-safe for reads; external locking required for concurrent registration.
    """

    def __init__(self) -> None:
        self._works: list[RegisteredWork] = []
        self._references: list[ReferenceSource] = []

    # ------------------------------------------------------------------
    # Registration — protected works (verbatim guard, existing API)
    # ------------------------------------------------------------------

    def register(self, source: str | Path, label: str = "") -> None:
        """
        Register a work for verbatim-reproduction protection.

        source: path to a text file, or a raw string of the work's text.
        label:  human-readable identifier ("Artist A — Song Title").
        """
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
            text = Path(source).read_text(encoding="utf-8", errors="replace")
            label = label or str(source)
        else:
            text = source
            label = label or f"inline_{len(self._works)}"

        tokens = _tokenize(text)
        if not tokens:
            log.warning("[copyright_guard] register: empty token list for '%s'", label)
            return

        self._works.append(RegisteredWork(label=label, tokens=tokens))
        log.info("[copyright_guard] registered protected work '%s' (%d tokens)", label, len(tokens))

    def register_directory(self, path: str | Path, glob: str = "*.txt") -> int:
        """Register all files matching glob in path as protected works. Returns count."""
        count = 0
        for f in Path(path).glob(glob):
            self.register(f)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Registration — reference/inspiration sources (new API)
    # ------------------------------------------------------------------

    def register_reference(
        self,
        source: str | Path,
        label: str = "",
        source_type: str = "unknown",
        license: str = "unknown",
        url: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
    ) -> None:
        """
        Register an inspiration/reference source for attribution tracking.

        source:      path to text file or raw string of the source content.
        label:       human-readable identifier ("ripgrep — BurntSushi").
        source_type: one of: open_source | academic | patent | commercial |
                     proprietary | private | unknown
        license:     SPDX identifier (MIT, Apache-2.0, GPL-3.0) or "proprietary"
                     or "unknown".
        url:         canonical URL (GitHub, arXiv, Google Patents, etc.).
        authors:     list of author names.
        year:        year of creation/publication.
        """
        if source_type not in VALID_SOURCE_TYPES:
            log.warning(
                "[copyright_guard] unknown source_type '%s' for '%s' — using 'unknown'",
                source_type,
                label,
            )
            source_type = "unknown"

        if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
            text = Path(source).read_text(encoding="utf-8", errors="replace")
            label = label or str(source)
        else:
            text = source
            label = label or f"ref_{len(self._references)}"

        tokens = _tokenize(text)
        if not tokens:
            log.warning("[copyright_guard] register_reference: empty token list for '%s'", label)
            return

        bg = _bigrams(tokens)
        fbg = _filtered_bigrams(tokens)
        ref = ReferenceSource(
            label=label,
            tokens=tokens,
            bigrams=bg,
            filtered_bigrams=fbg,
            source_type=source_type,
            license=license,
            url=url,
            authors=list(authors or []),
            year=year,
        )
        self._references.append(ref)
        log.info(
            "[copyright_guard] registered reference '%s' [%s] (%d tokens, %d bigrams, %d filtered)",
            label,
            source_type,
            len(tokens),
            len(bg),
            len(fbg),
        )

    def register_reference_directory(
        self,
        path: str | Path,
        glob: str = "*.txt",
        source_type: str = "unknown",
        license: str = "unknown",
    ) -> int:
        """
        Register all files matching glob in path as reference sources.
        source_type and license apply to all files in the directory.
        Returns count registered.
        """
        count = 0
        for f in Path(path).glob(glob):
            self.register_reference(f, source_type=source_type, license=license)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Checking — legacy API (copyright only)
    # ------------------------------------------------------------------

    def check(self, output_text: str, task_id: str = "") -> CopyrightAlert | None:
        """
        Check output_text against all protected works for verbatim reproduction.

        Returns the first CopyrightAlert found (longest match wins), or None.
        Alert is also written to the audit log.

        This is the existing API — unchanged for backward compatibility.
        """
        output_tokens = _tokenize(output_text)
        if len(output_tokens) < _MIN_MATCH_TOKENS:
            return None

        best_alert: CopyrightAlert | None = None

        for work in self._works:
            match_len, out_start, src_start = _longest_common_run(output_tokens, work.tokens)
            if match_len < _MIN_MATCH_TOKENS:
                continue

            alert = CopyrightAlert(
                task_id=task_id,
                work_label=work.label,
                match_length=match_len,
                output_excerpt=_tokens_to_excerpt(output_tokens, out_start, match_len),
                source_excerpt=_tokens_to_excerpt(work.tokens, src_start, match_len),
            )
            log.warning("%s", alert)
            self._write_audit(alert)

            if best_alert is None or match_len > best_alert.match_length:
                best_alert = alert

        return best_alert

    # ------------------------------------------------------------------
    # Checking — full provenance (new API)
    # ------------------------------------------------------------------

    def check_provenance(self, output_text: str, task_id: str = "") -> ProvenanceReport:
        """
        Run the full provenance pipeline: copyright check + attribution tagging.

        Returns a ProvenanceReport containing:
          - copyright_alerts: verbatim reproduction findings (existing guard)
          - attribution_tags: inspiration/derivation tags from reference sources
            AND from copyright-alerted works (so every finding gets a tag)

        Never raises. Invalid states log warnings and return empty reports.
        """
        report = ProvenanceReport(task_id=task_id)
        output_tokens = _tokenize(output_text)

        if not output_tokens:
            return report

        # Stopword-filtered bigrams for reference-source Jaccard comparison.
        # Reduces false positives on shared boilerplate (argparse scaffolds, error idioms).
        # Scope: against registered references only (currently seeded from corpus/references/).
        output_filtered_bigrams = _filtered_bigrams(output_tokens)

        # --- Pass 1: copyright check against protected works ---
        for work in self._works:
            match_len, out_start, src_start = _longest_common_run(output_tokens, work.tokens)
            if match_len >= _MIN_MATCH_TOKENS:
                alert = CopyrightAlert(
                    task_id=task_id,
                    work_label=work.label,
                    match_length=match_len,
                    output_excerpt=_tokens_to_excerpt(output_tokens, out_start, match_len),
                    source_excerpt=_tokens_to_excerpt(work.tokens, src_start, match_len),
                )
                log.warning("%s", alert)
                self._write_audit(alert)
                report.copyright_alerts.append(alert)

                # Every copyright alert also produces an attribution tag
                score = min(1.0, match_len / max(len(work.tokens), 1))
                tag = AttributionTag(
                    task_id=task_id,
                    source_label=work.label,
                    source_type="unknown",
                    license="unknown",
                    url="",
                    authors=[],
                    year=None,
                    match_type="verbatim_reproduction",
                    similarity_score=score,
                    excerpt=alert.output_excerpt,
                )
                report.attribution_tags.append(tag)
                self._write_attribution_audit(tag)

            elif match_len >= _SUBSTANTIAL_TOKEN_THRESHOLD:
                # Substantial similarity from a protected work — tag it
                score = match_len / max(len(work.tokens), 1)
                tag = AttributionTag(
                    task_id=task_id,
                    source_label=work.label,
                    source_type="unknown",
                    license="unknown",
                    url="",
                    authors=[],
                    year=None,
                    match_type="substantial_similarity",
                    similarity_score=score,
                    excerpt=_tokens_to_excerpt(output_tokens, out_start, match_len),
                )
                report.attribution_tags.append(tag)
                self._write_attribution_audit(tag)

        # --- Pass 2: attribution check against reference sources ---
        # Bigram comparisons use filtered bigrams (stopwords removed) to suppress
        # false positives on shared boilerplate. Scope: registered references only.
        for ref in self._references:
            # Token-level LCS for verbatim / substantial token matches
            match_len, out_start, _ = _longest_common_run(output_tokens, ref.tokens)

            if match_len >= _MIN_MATCH_TOKENS:
                match_type = "verbatim_reproduction"
                score = min(1.0, match_len / max(len(ref.tokens), 1))
                excerpt = _tokens_to_excerpt(output_tokens, out_start, match_len)
            elif match_len >= _SUBSTANTIAL_TOKEN_THRESHOLD:
                match_type = "substantial_similarity"
                score = match_len / max(len(ref.tokens), 1)
                excerpt = _tokens_to_excerpt(output_tokens, out_start, match_len)
            else:
                # Stopword-filtered bigram Jaccard for soft inspiration detection.
                # Using ref.filtered_bigrams mirrors the same stopword removal on both sides.
                jac = _jaccard(output_filtered_bigrams, ref.filtered_bigrams)
                if jac >= _SUBSTANTIAL_BIGRAM_THRESHOLD:
                    match_type = "substantial_similarity"
                    score = jac
                elif jac >= _INSPIRATION_BIGRAM_THRESHOLD:
                    match_type = "inspiration"
                    score = jac
                else:
                    continue  # below all thresholds — no tag

                excerpt = _tokens_to_excerpt(output_tokens, 0, min(30, len(output_tokens)))

            # License-tier determines whether a verbatim hit on a reference is a copyright
            # concern or an expected attribution event.
            # Permissive OSS (MIT, Apache-2.0, etc.): verbatim reuse with attribution
            #   is the system working correctly — tag-only, never a CopyrightAlert.
            # Copyleft / proprietary / unknown + enforce mode: produce CopyrightAlert.
            # Any mode + non-permissive: emit a log warning so the signal isn't buried.
            tier = _license_tier(ref.license)

            if match_type == "verbatim_reproduction":
                if tier == "permissive":
                    log.info(
                        "[attribution] verbatim reuse of permissive source '%s' in task=%s "
                        "(%.1f%% overlap, %s) — tagging only, no alert",
                        ref.label,
                        task_id,
                        score * 100,
                        ref.license,
                    )
                else:
                    log.warning(
                        "[attribution] verbatim_reproduction of non-permissive source '%s' "
                        "in task=%s (%.1f%% overlap, tier=%s)",
                        ref.label,
                        task_id,
                        score * 100,
                        tier,
                    )
                    if not _OBSERVE_ONLY:
                        alert = CopyrightAlert(
                            task_id=task_id,
                            work_label=ref.label,
                            match_length=match_len,
                            output_excerpt=excerpt,
                            source_excerpt=_tokens_to_excerpt(ref.tokens, 0, min(match_len, 50)),
                        )
                        self._write_audit(alert)
                        report.copyright_alerts.append(alert)
            elif match_type == "substantial_similarity":
                log.info(
                    "[attribution] substantial_similarity to '%s' in task=%s (%.1f%% overlap)",
                    ref.label,
                    task_id,
                    score * 100,
                )
            else:
                log.debug(
                    "[attribution] inspiration from '%s' in task=%s (%.1f%% filtered bigram overlap)",
                    ref.label,
                    task_id,
                    score * 100,
                )

            tag = AttributionTag(
                task_id=task_id,
                source_label=ref.label,
                source_type=ref.source_type,
                license=ref.license,
                url=ref.url,
                authors=ref.authors,
                year=ref.year,
                match_type=match_type,
                similarity_score=score,
                excerpt=excerpt,
            )
            report.attribution_tags.append(tag)
            self._write_attribution_audit(tag)

        return report

    def log_attribution(self, report: ProvenanceReport) -> None:
        """
        Write the full provenance report to the attribution audit log as a single record.
        Call this after check_provenance() if you want a consolidated per-output record.
        """
        if report.is_clean:
            return
        try:
            _ATTRIBUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_ATTRIBUTION_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("[copyright_guard] attribution report write failed: %s", exc)

    # ------------------------------------------------------------------
    # Audit logs
    # ------------------------------------------------------------------

    def _write_audit(self, alert: CopyrightAlert) -> None:
        try:
            _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(alert.to_dict(), ensure_ascii=True) + "\n")
        except Exception as exc:
            log.error("[copyright_guard] audit write failed: %s", exc)

    def _write_attribution_audit(self, tag: AttributionTag) -> None:
        try:
            _ATTRIBUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_ATTRIBUTION_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(tag.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("[copyright_guard] attribution write failed: %s", exc)

    def audit_log_path(self) -> Path:
        return _AUDIT_LOG

    def attribution_log_path(self) -> Path:
        return _ATTRIBUTION_LOG

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "provenance_mode": "observe" if _OBSERVE_ONLY else "enforce",
            "protected_works": len(self._works),
            "works": [{"label": w.label, "token_count": len(w.tokens)} for w in self._works],
            "reference_sources": len(self._references),
            "references": [
                {
                    "label": r.label,
                    "source_type": r.source_type,
                    "license": r.license,
                    "license_tier": _license_tier(r.license),
                    "url": r.url,
                    "authors": r.authors,
                    "year": r.year,
                    "token_count": len(r.tokens),
                    "bigram_count": len(r.bigrams),
                    "filtered_bigram_count": len(r.filtered_bigrams),
                }
                for r in self._references
            ],
            "thresholds": {
                "verbatim_min_tokens": _MIN_MATCH_TOKENS,
                "substantial_min_tokens": _SUBSTANTIAL_TOKEN_THRESHOLD,
                "substantial_bigram_jaccard": _SUBSTANTIAL_BIGRAM_THRESHOLD,
                "inspiration_bigram_jaccard": _INSPIRATION_BIGRAM_THRESHOLD,
            },
            "audit_log": str(_AUDIT_LOG),
            "attribution_log": str(_ATTRIBUTION_LOG),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_guard: CopyrightGuard | None = None


def get_guard() -> CopyrightGuard:
    global _guard
    if _guard is None:
        _guard = CopyrightGuard()
        _auto_seed(_guard)
    return _guard


# Alias — callers that import for provenance use the same singleton
get_provenance_guard = get_guard


def _auto_seed(guard: CopyrightGuard) -> None:
    """
    Auto-register works and reference sources from the corpus directories.

    Protected works:   corpus/protected/*.txt  → verbatim copyright guard
    Reference sources: corpus/references/*.txt → attribution tagging only
                       corpus/references/<subdir>/*.txt with metadata from
                       an optional corpus/references/<subdir>/metadata.json
    """
    # Protected works
    protected_dir = Path(
        os.environ.get(
            "DETERMINEX_PROTECTED_WORKS_DIR",
            "corpus/protected",
        )
    )
    if protected_dir.exists():
        count = guard.register_directory(protected_dir, glob="*.txt")
        if count:
            log.info(
                "[copyright_guard] auto-seeded %d protected works from %s", count, protected_dir
            )

    # Reference sources — flat .txt files
    references_dir = Path(
        os.environ.get(
            "DETERMINEX_REFERENCES_DIR",
            "corpus/references",
        )
    )
    if references_dir.exists():
        # Top-level .txt files with default metadata
        count = guard.register_reference_directory(references_dir, glob="*.txt")
        if count:
            log.info(
                "[copyright_guard] auto-seeded %d flat reference sources from %s",
                count,
                references_dir,
            )

        # Subdirectory-based sources with per-dir metadata.json
        for subdir in references_dir.iterdir():
            if not subdir.is_dir():
                continue
            meta_file = subdir / "metadata.json"
            meta: dict = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    log.warning("[copyright_guard] failed to parse %s: %s", meta_file, exc)

            for txt_file in subdir.glob("*.txt"):
                guard.register_reference(
                    txt_file,
                    label=meta.get("label", txt_file.stem),
                    source_type=meta.get("source_type", "unknown"),
                    license=meta.get("license", "unknown"),
                    url=meta.get("url", ""),
                    authors=meta.get("authors", []),
                    year=meta.get("year"),
                )
