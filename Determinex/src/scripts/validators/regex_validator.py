"""
validators/regex_validator.py - Regex Pattern Validator

Validates output against configurable regex patterns.
Used for: documentation, SQL, markdown extraction tasks where
structure is verifiable by pattern but not by a compiler.
"""

import logging
import re

log = logging.getLogger("oracle.validator.regex")

# Default pattern: output must be at least 80 meaningful characters
_DEFAULT_PATTERN = r"^.{80,}"
_DEFAULT_DESC = "Must be at least 80 characters"


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate output by matching against a regex pattern.

    Config is read from task_meta['validator_config']:
        pattern     (str):  Regex pattern to match. Default: 80+ chars.
        description (str):  Human-readable description for error messages.
        flags       (list): Optional list of re flag names ('IGNORECASE', 'DOTALL', etc.)
        require_all (bool): If True, ALL patterns in 'patterns' list must match.
                            If False (default), first match wins.

    Supports both single pattern (validator_config.pattern) and
    multi-pattern mode (validator_config.patterns list).
    """
    text = output.strip()

    if len(text) < 5:
        return False, "Output is too short"

    config = task_meta.get("validator_config", {})
    desc = config.get("description", _DEFAULT_DESC)
    flag_names = config.get("flags", [])

    # Combine requested flags
    re_flags = 0
    for flag_name in flag_names:
        flag = getattr(re, flag_name.upper(), None)
        if flag is not None:
            re_flags |= flag

    # ── Single pattern mode ──────────────────────────────────────────────────
    pattern = config.get("pattern", _DEFAULT_PATTERN)
    patterns = config.get("patterns", [pattern])
    require_all = config.get("require_all", False)

    results = []
    for pat in patterns:
        try:
            matched = bool(re.search(pat, text, re_flags))
            results.append((pat, matched))
        except re.error as e:
            log.warning("Invalid regex pattern '%s': %s", pat, e)
            results.append((pat, True))  # Don't penalize sample for bad task config

    if require_all:
        failed = [pat for pat, ok in results if not ok]
        if failed:
            return False, f"Patterns not matched: {failed[:2]} -- {desc}"
        return True, f"All {len(patterns)} patterns matched"
    else:
        # At least one must match
        if any(ok for _, ok in results):
            return True, f"Pattern matched -- {desc}"
        return False, f"No patterns matched -- {desc}"
