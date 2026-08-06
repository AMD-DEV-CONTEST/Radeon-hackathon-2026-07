"""
evidence.py

Per-workload evidence store factory.

Each call to new_evidence() returns a fresh, isolated dictionary.
Evidence is NEVER shared between workload investigations.
"""


def new_evidence() -> dict:
    """
    Return a fresh evidence dictionary for one workload investigation.
    Keys are added dynamically as tools execute — no pre-defined schema.
    """
    return {}