"""
scripts/hive/constants.py — Shared build-loop constants
========================================================
Single source of truth for tunables used by executor.py, prompt_builder.py,
and any future sub-modules that participate in the build loop.
"""

# Retry / challenge / escalation limits
MAX_RETRIES_PER_STEP = 3
MAX_CHALLENGES_PER_STEP = 2
MIN_CHALLENGE_DELTA = 0.1
MAX_ESCALATIONS_PER_STEP = 1

# Timing
MONITOR_TIMEOUT_SECONDS = 90

# Oscillation detection: same file hash this many consecutive times → DAG cycle
OSCILLATION_THRESHOLD = 3

# Above this line count, force replace_file semantics (small models can't do diffs)
MAX_LINES_BEFORE_FORCE_REPLACE = 300
