"""Entity Extraction — extracts named entities from user text.

Entities are typed values pulled out of the command text:
  - PATH: filesystem paths (Windows or Unix)
  - URL: web URLs
  - DOMAIN: bare domains like "github.com"
  - APP: application names
  - SITE: site aliases (amazon, youtube, ...)
  - FILE: filenames
  - SEARCH_QUERY: search query text
  - DURATION: time durations ("5 minutes", "1 hour")
  - NUMBER: numeric values
  - TEXT: visible UI text (for click commands)
  - EMAIL: email addresses
  - USERNAME: usernames

Each entity has a type, value, span (start/end in original text),
confidence, and optional metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Entity:
    """A single extracted entity."""
    type: str
    value: str
    span: Tuple[int, int]
    confidence: float = 1.0
    metadata: Dict = field(default_factory=dict)
    raw_text: str = ""

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "value": self.value,
            "span": list(self.span),
            "confidence": self.confidence,
            "metadata": self.metadata,
            "raw_text": self.raw_text,
        }


class EntityExtractor:
    """Extracts typed entities from user text."""

    SITE_ALIASES = {
        "amazon": "https://www.amazon.com",
        "bing": "https://www.bing.com",
        "chatgpt": "https://chatgpt.com",
        "edge": "https://www.microsoft.com/edge",
        "facebook": "https://www.facebook.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "youtube": "https://www.youtube.com",
    }

    # Delivery channels (capability table, not a hardcoded workflow).
    CHANNELS: Dict[str, List[str]] = {
        "whatsapp": ["whatsapp", "wa", "web.whatsapp.com", "whatsapp web"],
        "gmail": ["gmail", "mail", "email"],
        "slack": ["slack"],
        "telegram": ["telegram", "tg"],
        "signal": ["signal"],
        "discord": ["discord"],
        "messenger": ["messenger"],
    }

    # Channel -> web app URL for the planner.
    CHANNEL_URL: Dict[str, str] = {
        "whatsapp": "https://web.whatsapp.com",
        "gmail": "https://mail.google.com",
        "slack": "https://app.slack.com",
        "telegram": "https://web.telegram.org",
        "signal": "https://signal.org",
        "discord": "https://discord.com/app",
        "messenger": "https://www.messenger.com",
    }

    # Structural words never treated as a contact/person name.
    CONTACT_STOP_WORDS = frozenset({
        "file", "folder", "directory", "desktop", "documents", "downloads",
        "explorer", "browser", "chrome", "edge", "firefox", "gx", "opera",
        "whatsapp", "gmail", "mail", "email", "slack", "telegram", "discord",
        "signal", "messenger", "web", "website", "url", "site", "the", "a",
        "an", "me", "you", "them", "it", "this", "that", "now", "please",
    })

    # Entity patterns: (type, regex, confidence)
    PATTERNS: List[Tuple[str, str, float]] = [
        # URLs (highest priority)
        ("URL", r"https?://[^\s]+", 1.0),
        # Email addresses
        ("EMAIL", r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", 1.0),
        # Windows paths
        ("PATH", r"[Cc]:\\[^\s\"']+", 1.0),
        # Unix paths (absolute)
        ("PATH", r"(?:^|[\s])(/[\w./-]+)", 0.9),
        # Bare domains
        ("DOMAIN", r"\b([a-zA-Z0-9-]+\.(com|org|net|io|gov|edu|co|uk|ca|de))\b", 0.95),
        # Durations
        ("DURATION", r"\b(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b", 1.0),
        # Numbers (skip when part of a filename like "1.txt")
        ("NUMBER", r"\b\d+\b(?!\.\w{2,4}\b)", 0.7),
        # Filenames (heuristic: word.ext)
        ("FILE", r"\b[\w-]+\.(exe|msi|bat|cmd|ps1|py|js|json|txt|pdf|doc|docx|xls|xlsx|ppt|pptx|zip|tar|gz|jpg|png|gif|mp4|mp3)\b", 0.9),
    ]

    # Known app phrases (multi-word)
    KNOWN_APPS = [
        "opera gx browser", "opera gx", "gx browser",
        "google chrome", "microsoft edge", "visual studio code",
        "vs code", "file explorer", "task manager",
        "control panel", "settings app", "windows terminal",
        "powershell", "command prompt", "notepad",
        "calculator", "paint", "word pad",
    ]

    # Words to strip when extracting app names
    APP_STRIP_WORDS = [
        "open", "launch", "start", "run", "close", "quit",
        "app", "application", "program", "the", "a", "an",
        "please", "for me", "now",
    ]

    def __init__(self):
        self._compiled = [
            (etype, re.compile(pattern, re.IGNORECASE), conf)
            for etype, pattern, conf in self.PATTERNS
        ]

    def extract(self, text: str) -> List[Entity]:
        """Extract all entities from text.

        Returns a list of Entity objects sorted by span position.
        """
        if not text:
            return []

        entities: List[Entity] = []
        seen_spans: List[Tuple[int, int]] = []

        # Run regex patterns
        for etype, compiled, conf in self._compiled:
            for m in compiled.finditer(text):
                span = (m.start(), m.end())
                # Skip overlapping spans (keep first/highest-priority)
                if self._overlaps(span, seen_spans):
                    continue
                seen_spans.append(span)

                value = m.group(0)
                metadata = {}

                if etype == "DOMAIN":
                    metadata["scheme"] = "https"
                    metadata["url"] = f"https://{value}"
                elif etype == "DURATION":
                    n = int(m.group(1))
                    unit = m.group(2).lower()
                    ms = self._duration_to_ms(n, unit)
                    metadata = {"amount": n, "unit": unit, "ms": ms}
                elif etype == "PATH":
                    metadata["normalized"] = value.replace("/", "\\") if "\\" not in value else value

                entities.append(Entity(
                    type=etype,
                    value=value,
                    span=span,
                    confidence=conf,
                    metadata=metadata,
                    raw_text=text[span[0]:span[1]],
                ))

        # Extract app names (heuristic)
        app_entity = self._extract_app(text)
        if app_entity:
            entities.append(app_entity)

        # Extract site aliases
        site_entity = self._extract_site_alias(text)
        if site_entity:
            entities.append(site_entity)

        # Extract delivery channel (whatsapp/gmail/slack/...)
        channel_entity = self._extract_channel(text)
        if channel_entity:
            entities.append(channel_entity)

        # Extract a contact/person name
        contact_entity = self._extract_contact(text)
        if contact_entity:
            entities.append(contact_entity)

        # Sort by span position
        entities.sort(key=lambda e: e.span[0])
        return entities

    def extract_by_type(self, text: str, entity_type: str) -> List[Entity]:
        """Extract only entities of a specific type."""
        return [e for e in self.extract(text) if e.type == entity_type]

    def _extract_app(self, text: str) -> Optional[Entity]:
        """Extract an application name from the text."""
        text_lower = text.lower()

        # Check known multi-word apps first
        for phrase in self.KNOWN_APPS:
            pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            m = pattern.search(text_lower)
            if m:
                return Entity(
                    type="APP",
                    value=phrase,
                    span=(m.start(), m.end()),
                    confidence=1.0,
                    metadata={"known": True},
                    raw_text=text[m.start():m.end()],
                )

        # Heuristic: find a word after "open/launch/start/run"
        m = re.search(r"\b(open|launch|start|run)\b\s+(?:the\s+)?(\w+)", text_lower)
        if m:
            app_word = m.group(2)
            # Skip if it's a common verb/noun
            if app_word not in {"it", "a", "an", "the", "up", "down", "file", "folder"}:
                return Entity(
                    type="APP",
                    value=app_word,
                    span=(m.start(2), m.end(2)),
                    confidence=0.7,
                    metadata={"known": False},
                    raw_text=text[m.start(2):m.end(2)],
                )

        return None

    def _extract_site_alias(self, text: str) -> Optional[Entity]:
        """Extract a known site alias (amazon, youtube, ...)."""
        text_lower = text.lower()
        for name, url in self.SITE_ALIASES.items():
            pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
            m = pattern.search(text_lower)
            if m:
                return Entity(
                    type="SITE",
                    value=name,
                    span=(m.start(), m.end()),
                    confidence=1.0,
                    metadata={"url": url},
                    raw_text=text[m.start():m.end()],
                )
        return None

    def _extract_channel(self, text: str) -> Optional[Entity]:
        """Extract a delivery channel (whatsapp/gmail/slack/telegram/...).

        Longest alias first so "web.whatsapp.com" beats "whatsapp".
        """
        text_lower = text.lower()
        for channel, aliases in sorted(
            self.CHANNELS.items(),
            key=lambda kv: -max(len(a) for a in kv[1]),
        ):
            for alias in aliases:
                pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
                m = pattern.search(text_lower)
                if m:
                    return Entity(
                        type="CHANNEL",
                        value=channel,
                        span=(m.start(), m.end()),
                        confidence=1.0,
                        metadata={"url": self.CHANNEL_URL.get(channel, "")},
                        raw_text=text[m.start():m.end()],
                    )
        return None

    def _extract_contact(self, text: str) -> Optional[Entity]:
        """Extract a recipient/person name after 'to/for/@/contact/send to'."""
        patterns = [
            # "contact X", "person X", "user X"
            r"\b(?:contact|person|user)\s+(@?[A-Za-z][A-Za-z0-9_.]{1,})",
            # "@name"
            r"@([A-Za-z][A-Za-z0-9_.]{1,})",
            # "send <...> to X", "send to X", "for X"
            r"\b(?:send|share|transfer)\b(?:[^.]*?)\b(?:to|for)\s+(@?[A-Za-z][A-Za-z0-9_.]{1,})",
            r"\bto\s+(@?[A-Za-z][A-Za-z0-9_.]{1,})",
            r"\bfor\s+(@?[A-Za-z][A-Za-z0-9_.]{1,})",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if not m:
                continue
            candidate = m.group(1).lstrip("@")
            if candidate.lower() in self.CONTACT_STOP_WORDS:
                continue
            return Entity(
                type="CONTACT",
                value=candidate,
                span=(m.start(1), m.end(1)),
                confidence=0.9,
                metadata={"raw_match": m.group(0)},
                raw_text=candidate,
            )
        return None

    def _duration_to_ms(self, n: int, unit: str) -> int:
        """Convert a duration to milliseconds."""
        unit = unit.lower()
        if unit.startswith("sec"):
            return n * 1000
        if unit.startswith("min"):
            return n * 60 * 1000
        if unit.startswith("hour") or unit.startswith("hr"):
            return n * 60 * 60 * 1000
        if unit.startswith("day"):
            return n * 24 * 60 * 60 * 1000
        return n * 1000

    def _overlaps(self, span: Tuple[int, int], existing: List[Tuple[int, int]]) -> bool:
        """Check if a span overlaps with any existing span."""
        s1, e1 = span
        for s2, e2 in existing:
            if not (e1 <= s2 or s1 >= e2):
                return True
        return False
