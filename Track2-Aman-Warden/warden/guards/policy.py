"""
YAML Policy-as-Code engine.

Loads security policy rules from YAML files and evaluates
actions/inputs against them. Supports shadow mode (log only).
"""

from __future__ import annotations

import re
import logging
import fnmatch
from pathlib import Path
from typing import Any, Optional

import yaml

from warden.config import Decision

logger = logging.getLogger(__name__)


class PolicyEngine:
    """Evaluates actions and inputs against YAML policy rules."""

    def __init__(self, policy_path: str = "policies/default.yaml"):
        self.policy_path = policy_path
        self.rules: list[dict] = []
        self.shadow_mode: bool = False
        self.policy_name: str = "unknown"
        self._loaded = False

    def load(self) -> bool:
        """Load policy from YAML file."""
        path = Path(self.policy_path)
        if not path.exists():
            logger.warning(f"Policy file not found: {self.policy_path}")
            return False

        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)

            self.policy_name = data.get("name", "unnamed")
            self.shadow_mode = data.get("shadow_mode", False)
            self.rules = data.get("rules", [])
            self._loaded = True
            logger.info(f"Loaded policy '{self.policy_name}' with {len(self.rules)} rules (shadow={self.shadow_mode})")
            return True

        except Exception as e:
            logger.error(f"Failed to load policy: {e}")
            return False

    def evaluate(self, text: str, source: str = "") -> Optional[dict]:
        """
        Evaluate input text against general policy rules (excluding tool_calls scope).
        """
        if not self._loaded:
            return None

        for rule in self.rules:
            if rule.get("scope") == "tool_calls":
                continue
            if self._check_rule(rule, text, source):
                return self._format_result(rule)

        return None

    def evaluate_tool_call(self, tool_name: str, args: dict) -> Optional[dict]:
        """
        Evaluate a tool call and its arguments against policy rules.
        """
        if not self._loaded:
            return None

        for rule in self.rules:
            if rule.get("scope") != "tool_calls":
                continue

            match_config = rule.get("match", {})
            
            # 1. Check tool_name.any_of if specified
            tool_names = match_config.get("tool_name", {}).get("any_of", [])
            if tool_names and tool_name not in tool_names:
                continue

            # 2. Check args.path_matches if specified
            path_matches = match_config.get("args", {}).get("path_matches", [])
            if path_matches:
                matched_path = False
                for arg_val in args.values():
                    if isinstance(arg_val, str):
                        for pat in path_matches:
                            # Use fnmatch or substring match for wildcards
                            if fnmatch.fnmatch(arg_val, pat) or fnmatch.fnmatch(f"/{arg_val.lstrip('/')}", pat) or pat == "/**/*":
                                matched_path = True
                                break
                    if matched_path:
                        break
                if not matched_path:
                    continue

            # 3. Check regex patterns against string arguments
            patterns = match_config.get("patterns", [])
            if patterns:
                matched_pat = False
                regex_flags = re.IGNORECASE if "ignorecase" in rule.get("flags", []) else 0
                for arg_val in args.values():
                    if isinstance(arg_val, str):
                        for pat in patterns:
                            try:
                                if re.search(pat, arg_val, regex_flags):
                                    matched_pat = True
                                    break
                            except re.error:
                                pass
                    if matched_pat:
                        break
                if not matched_pat:
                    continue

            # If we reached here, all specified conditions matched!
            return self._format_result(rule)

        return None

    def _format_result(self, rule: dict) -> Optional[dict]:
        action = rule.get("action", "flag")
        message = rule.get("message", "Policy rule matched")
        rule_name = rule.get("name", "unnamed_rule")

        if self.shadow_mode:
            logger.info(f"[SHADOW] Rule '{rule_name}' would {action}: {message}")
            return None  # Shadow mode never blocks

        return {
            "decision": action,
            "reason": f"Policy rule '{rule_name}': {message}",
            "rule_name": rule_name,
            "is_definitive": action in ("block", "allow"),
        }

    def _check_rule(self, rule: dict, text: str, source: str) -> bool:
        """Check if a single general rule matches the input."""
        match_config = rule.get("match", {})
        regex_flags = re.IGNORECASE if "ignorecase" in rule.get("flags", []) else 0

        # Check pattern matches
        patterns = match_config.get("patterns", [])
        for pattern in patterns:
            try:
                if re.search(pattern, text, regex_flags):
                    return True
            except re.error:
                logger.warning(f"Invalid regex in policy: {pattern}")

        # Check import matches
        imports = match_config.get("imports_any", [])
        for imp in imports:
            if f"import {imp}" in text or f"from {imp}" in text:
                return True

        return False

    def is_loaded(self) -> bool:
        return self._loaded
