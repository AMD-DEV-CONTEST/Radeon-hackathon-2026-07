"""Parameter Extraction — converts entities into typed tool parameters.

Each intent has a parameter schema that maps entity types to tool argument
names. The ParameterExtractor:
  - Knows the parameter schema for each intent
  - Pulls entities from EntityExtractor
  - Applies defaults when entities are missing
  - Validates required parameters
  - Returns a typed parameter dict ready for tool execution

This is the bridge between "what the user said" and "what the tool needs".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .entity_extractor import Entity, EntityExtractor


@dataclass
class ParamSpec:
    """Specification for a single parameter."""
    name: str
    entity_type: str  # which entity type to pull from
    required: bool = False
    default: Any = None
    description: str = ""
    validator: Optional[str] = None  # name of validator function
    aliases: List[str] = field(default_factory=list)  # alternate names


@dataclass
class ParamExtractionResult:
    """Result of parameter extraction."""
    params: Dict[str, Any]
    missing: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    used_entities: List[Entity] = field(default_factory=list)


class ParameterExtractor:
    """Extracts typed parameters from entities based on intent schemas."""

    # Intent → list of ParamSpec
    # This is the canonical schema for tool arguments.
    DEFAULT_SCHEMAS: Dict[str, List[ParamSpec]] = {
        "system_status": [],
        "disk_usage": [],
        "ram_usage": [],
        "list_files": [
            ParamSpec("path", "PATH", required=False, default=".", description="Directory to list"),
        ],
        "delete_files": [
            ParamSpec("path", "PATH", required=False, default=".", description="Directory to delete from"),
        ],
        "open_website": [
            ParamSpec("url", "URL", required=True, description="URL to open"),
            ParamSpec("url", "DOMAIN", required=False, description="Bare domain fallback"),
            ParamSpec("url", "SITE", required=False, description="Site alias fallback"),
        ],
        "search_web": [
            ParamSpec("query", "SEARCH_QUERY", required=True, description="Search query"),
        ],
        "browser_close": [],
        "browser_session": [
            ParamSpec("name", "APP", required=False, default="chrome", description="Browser app"),
        ],
        "open_app": [
            ParamSpec("name", "APP", required=True, description="Application name"),
        ],
        "download_file": [
            ParamSpec("url", "URL", required=True, description="Download URL"),
        ],
        "login": [
            ParamSpec("site", "URL", required=False, description="Login site URL"),
            ParamSpec("site", "DOMAIN", required=False, description="Login site domain"),
            ParamSpec("site", "SITE", required=False, description="Login site alias"),
        ],
        "send_email": [
            ParamSpec("to", "EMAIL", required=True, description="Recipient email"),
        ],
        "run_command": [
            ParamSpec("command", "TEXT", required=True, description="Command to run"),
        ],
        "screen_click": [
            ParamSpec("text", "TEXT", required=True, description="Visible UI text"),
        ],
        "screen_scan": [],
    }

    def __init__(self, entity_extractor: Optional[EntityExtractor] = None,
                 custom_schemas: Optional[Dict[str, List[ParamSpec]]] = None):
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.schemas = {**self.DEFAULT_SCHEMAS}
        if custom_schemas:
            for intent, specs in custom_schemas.items():
                if intent in self.schemas:
                    self.schemas[intent].extend(specs)
                else:
                    self.schemas[intent] = list(specs)

    def extract(self, text: str, intent: str) -> ParamExtractionResult:
        """Extract parameters for a given intent from text.

        Returns ParamExtractionResult with params, missing required params,
        and any errors.
        """
        entities = self.entity_extractor.extract(text)
        # Also extract a SEARCH_QUERY entity if not already present
        if not any(e.type == "SEARCH_QUERY" for e in entities):
            sq = self._extract_search_query(text)
            if sq:
                entities.append(sq)
        # And a TEXT entity for click commands
        if not any(e.type == "TEXT" for e in entities):
            tx = self._extract_text(text)
            if tx:
                entities.append(tx)

        specs = self.schemas.get(intent, [])
        params: Dict[str, Any] = {}
        missing: List[str] = []
        errors: List[str] = []
        used: List[Entity] = []

        for spec in specs:
            # Find the first matching entity of the requested type
            match = self._find_entity(entities, spec.entity_type)
            if match:
                params[spec.name] = match.value
                used.append(match)
            elif spec.required:
                missing.append(spec.name)
            elif spec.default is not None:
                params[spec.name] = spec.default

        # Validate
        for name, value in params.items():
            spec = next((s for s in specs if s.name == name), None)
            if spec and spec.validator:
                err = self._validate(value, spec.validator)
                if err:
                    errors.append(f"{name}: {err}")

        return ParamExtractionResult(
            params=params,
            missing=missing,
            errors=errors,
            used_entities=used,
        )

    def _find_entity(self, entities: List[Entity], entity_type: str) -> Optional[Entity]:
        """Find the first entity of a given type."""
        for e in entities:
            if e.type == entity_type:
                return e
        return None

    def _extract_search_query(self, text: str) -> Optional[Entity]:
        """Extract a search query from text."""
        import re
        # Remove common prefixes
        cleaned = re.sub(
            r"\b(search|google|find|look up|lookup|for|on the web|online)\b",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        # Remove browser hints
        cleaned = re.sub(
            r"\b(in|on|with)\s+(chrome|edge|browser|google|bing)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.")
        if cleaned and cleaned.lower() != text.lower():
            return Entity(
                type="SEARCH_QUERY",
                value=cleaned,
                span=(0, len(text)),
                confidence=0.8,
                metadata={"cleaned": True},
                raw_text=cleaned,
            )
        return None

    def _extract_text(self, text: str) -> Optional[Entity]:
        """Extract visible UI text from a click command."""
        import re
        cleaned = re.sub(
            r"\b(click|press|tap|select|button|link|tab|field|on|the)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:\"'")
        if cleaned and cleaned.lower() != text.lower():
            return Entity(
                type="TEXT",
                value=cleaned,
                span=(0, len(text)),
                confidence=0.7,
                metadata={"cleaned": True},
                raw_text=cleaned,
            )
        return None

    def _validate(self, value: Any, validator: str) -> Optional[str]:
        """Run a named validator. Returns error message or None."""
        if validator == "non_empty":
            if not value or (isinstance(value, str) and not value.strip()):
                return "value is empty"
        elif validator == "url":
            if not (isinstance(value, str) and (value.startswith("http://") or value.startswith("https://"))):
                return "not a valid URL"
        elif validator == "path":
            if not isinstance(value, str) or not value.strip():
                return "not a valid path"
        return None

    def register_schema(self, intent: str, specs: List[ParamSpec]) -> None:
        """Register or extend a parameter schema for an intent."""
        if intent in self.schemas:
            self.schemas[intent].extend(specs)
        else:
            self.schemas[intent] = list(specs)
