"""SpecStyle workflow job state machine and local store (WF-001).

Derived and frozen from state transitions in ``architecture/contracts.md``
section 5, value objects in section 2, and invariants in section 4. This module
depends only on :mod:`specstyle.domain` and :mod:`specstyle.errors`. It imports
no generation, verification, repair, exporting, or spec business types, thus
preserving three-plane separation.
"""
