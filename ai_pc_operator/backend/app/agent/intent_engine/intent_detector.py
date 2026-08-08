"""Intent Detection — classifies user text into one or more candidate intents.

This is the first stage of the Intent Engine pipeline. It produces a ranked
list of candidate intents with raw match scores. Downstream stages
(Context Resolution, Confidence Scoring, Ambiguity Resolution) refine
the candidates into a final decision.

Design:
  - Pattern-based with weighted regex matches.
  - Each intent has multiple patterns; each pattern has a weight.
  - Returns ALL matching intents with scores, not just the top one.
  - Supports synonyms and aliases.
  - Supports negation detection ("don't open chrome" → not open_app).
  - Supports multi-intent detection ("open chrome and search X").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class IntentPattern:
    """A single regex pattern with weight and metadata."""
    pattern: str
    weight: float = 1.0
    compiled: Optional[re.Pattern] = None
    tags: List[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self):
        self.compiled = re.compile(self.pattern, re.IGNORECASE)


@dataclass
class IntentCandidate:
    """A candidate intent with its raw score."""
    intent: str
    score: float
    matched_patterns: List[str] = field(default_factory=list)
    matched_spans: List[Tuple[int, int]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class IntentDetector:
    """Detects candidate intents from user text."""

    # Built-in intent definitions with weighted patterns.
    # Weights reflect how strongly a pattern indicates the intent.
    DEFAULT_INTENTS: Dict[str, List[IntentPattern]] = {
        "system_status": [
            IntentPattern(r"\b(check|show|get)\b.*\b(status|health|info)\b", 1.0),
            IntentPattern(r"\bhow is\b.*\b(pc|computer|laptop)\b", 0.9),
            IntentPattern(r"\bsystem\s+(status|info|check)\b", 1.0),
            IntentPattern(r"\b(pc|computer)\s+(status|health)\b", 0.9),
        ],
        "disk_usage": [
            IntentPattern(r"\b(check|show|get)\b.*\b(storage|disk|drive)\b", 1.0),
            IntentPattern(r"\b(disk|storage|drive)\b.*\b(usage|space|free|full)\b", 1.0),
            IntentPattern(r"\bhow much\b.*\b(space|storage)\b", 1.0),
        ],
        "ram_usage": [
            IntentPattern(r"\b(ram|memory)\b.*\b(usage|used|free)\b", 1.0),
            IntentPattern(r"\bhow much\b.*\b(memory|ram)\b", 1.0),
        ],
        "list_files": [
            IntentPattern(r"\b(list|show)\b.*\b(files|folder|directory)\b", 1.0),
            IntentPattern(r"\bwhat('s| is) in\b", 0.8),
            IntentPattern(r"\bcontents of\b", 0.7),
        ],
        "delete_files": [
            IntentPattern(r"\b(delete|remove|clean)\b.*\b(files?|folder|directory)\b", 1.0),
            IntentPattern(r"\bempty\b.*\b(folder|directory|trash)\b", 1.0),
        ],
        "open_website": [
            IntentPattern(r"\b(open|go to|navigate to|visit)\b.*\b(website|url|site)\b", 1.0),
            IntentPattern(r"\b(open|go to|navigate to|visit)\b\s+([a-zA-Z0-9.-]+\.[a-z]{2,})", 1.0),
            IntentPattern(r"\bhttps?://\S+", 1.0),
        ],
        "search_web": [
            IntentPattern(r"\b(search|google|find)\b.*\b(web|internet|online)\b", 1.0),
            IntentPattern(r"\bsearch\b\s+for\b", 1.0),
            IntentPattern(r"\b(search|google|find|look up|lookup)\b.+", 0.6),
            IntentPattern(r"\b(search|google|find|look up|lookup)\b.*\b(in|on|with)\s+(chrome|edge|browser|google|bing)\b", 1.0),
        ],
        "browser_close": [
            IntentPattern(r"\b(close|quit|exit)\b.*\b(browser|chrome|edge|tab)\b", 1.0),
            IntentPattern(r"\b(close|quit|exit)\b\s+(browser|chrome|edge)\b", 1.0),
        ],
        "browser_session": [
            IntentPattern(r"browser[\s_]*session", 1.0),
            IntentPattern(r"\bkeep\s+(browser|session|pc|computer)\s+(awake|alive|open|active)\b", 1.0),
            IntentPattern(r"\bkeep\s+(awake|alive|active)\b.*\b(browser|session)\b", 1.0),
        ],
        "open_app": [
            IntentPattern(r"\b(open|launch|start|run)\b.*\b(app|application|program)\b", 1.0),
            IntentPattern(r"\b(open|launch|start|run)\b\s+\w+", 0.5),
        ],
        "download_file": [
            IntentPattern(r"\b(download|get|fetch)\b.*\b(file|program|app)\b", 1.0),
        ],
        "login": [
            IntentPattern(r"\b(login|sign in|log in)\b.*\b(to|on)\b", 1.0),
            IntentPattern(r"\blogin\b\s+to\b", 1.0),
        ],
        "send_email": [
            IntentPattern(r"\b(send|write|compose)\b.*\b(email|mail|message)\b", 1.0),
        ],
        "run_command": [
            IntentPattern(r"\b(run|execute)\b.*\b(command|script|code)\b", 1.0),
        ],
        "screen_click": [
            IntentPattern(r"\b(click|press|tap|select)\b\s+(.+)", 1.0),
            IntentPattern(r"\b(click|press|tap|select)\b.*\b(button|link|tab|field)\b", 1.0),
        ],
        "screen_scan": [
            IntentPattern(r"\b(scan|show|detect|find)\b.*\b(screen|buttons|ui|controls)\b", 1.0),
            IntentPattern(r"\bwhat\b.*\b(on|in)\b.*\b(screen)\b", 0.9),
        ],
    }

    # Negation cues — if any of these appear before a match, the intent is negated.
    NEGATION_CUES = [
        r"\bdon't\b", r"\bdo not\b", r"\bnever\b",
        r"\bno\b", r"\bnot\b", r"\bstop\b",
    ]

    # Multi-intent separators — text containing these may contain multiple intents.
    MULTI_INTENT_SEPARATORS = [
        r"\band then\b", r"\bthen\b", r"\bafter that\b",
        r"\bafterwards\b", r"\band\b", r"\balso\b",
        r"\bplus\b", r";", r"\.",
    ]

    def __init__(self, custom_intents: Optional[Dict[str, List[IntentPattern]]] = None):
        """Initialize with default intents plus any custom ones."""
        self.intents = {**self.DEFAULT_INTENTS}
        if custom_intents:
            for name, patterns in custom_intents.items():
                if name in self.intents:
                    self.intents[name].extend(patterns)
                else:
                    self.intents[name] = list(patterns)

        # Pre-compile negation cues
        self._negation_re = [re.compile(p, re.IGNORECASE) for p in self.NEGATION_CUES]
        self._multi_intent_re = [re.compile(p, re.IGNORECASE) for p in self.MULTI_INTENT_SEPARATORS]

    def detect(self, text: str) -> List[IntentCandidate]:
        """Detect all candidate intents in the text.

        Returns a list of IntentCandidate sorted by score (descending).
        Empty list means no intent matched.
        """
        if not text or not text.strip():
            return []

        text_lower = text.lower().strip()
        candidates: Dict[str, IntentCandidate] = {}

        for intent_name, patterns in self.intents.items():
            for pattern in patterns:
                matches = list(pattern.compiled.finditer(text_lower))
                if not matches:
                    continue

                if intent_name not in candidates:
                    candidates[intent_name] = IntentCandidate(
                        intent=intent_name,
                        score=0.0,
                        matched_patterns=[],
                        matched_spans=[],
                        tags=list(pattern.tags),
                    )

                cand = candidates[intent_name]
                # Accumulate score per match
                cand.score += pattern.weight * len(matches)
                for m in matches:
                    cand.matched_patterns.append(pattern.pattern)
                    cand.matched_spans.append((m.start(), m.end()))

        # Apply negation penalty
        for cand in candidates.values():
            if self._is_negated(text_lower, cand.matched_spans):
                cand.score *= -0.5  # negative score = likely negated

        # Sort by score descending
        sorted_candidates = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
        return sorted_candidates

    def detect_multi(self, text: str) -> List[List[IntentCandidate]]:
        """Detect intents in each segment of a multi-intent command.

        Splits the text on multi-intent separators and runs detect() on each
        segment. Returns a list of candidate lists, one per segment.
        """
        if not text or not text.strip():
            return []

        segments = self._split_multi_intent(text)
        return [self.detect(seg) for seg in segments if seg.strip()]

    def _is_negated(self, text: str, match_spans: List[Tuple[int, int]]) -> bool:
        """Check if any match span is preceded by a negation cue."""
        for start, _end in match_spans:
            prefix = text[:start]
            for neg_re in self._negation_re:
                if neg_re.search(prefix):
                    # Check that the negation is close (within ~20 chars)
                    last_match = list(neg_re.finditer(prefix))[-1]
                    if start - last_match.end() < 20:
                        return True
        return False

    def _split_multi_intent(self, text: str) -> List[str]:
        """Split text on multi-intent separators."""
        segments = [text]
        for sep_re in self._multi_intent_re:
            new_segments = []
            for seg in segments:
                parts = sep_re.split(seg)
                new_segments.extend(parts)
            segments = new_segments
        return [s.strip() for s in segments if s.strip()]

    def register_intent(self, name: str, patterns: List[IntentPattern]) -> None:
        """Register a new intent or extend an existing one."""
        if name in self.intents:
            self.intents[name].extend(patterns)
        else:
            self.intents[name] = list(patterns)

    def list_intents(self) -> List[str]:
        """List all registered intent names."""
        return list(self.intents.keys())
