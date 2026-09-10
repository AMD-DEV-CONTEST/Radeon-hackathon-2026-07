"""SpecStyle secure export plane.

Frozen by architecture contract ``architecture/contracts.md`` section 13.

EXP-001A owns input models, cross-object invariants, pure path planning, and
in-memory generation of canonical manifest, QA, credits, style spec, payload,
and digest documents. It performs no filesystem access, environment capture,
network access, or native syscall. EXP-001B owns the trusted root fd,
stage/write/readback/fsync sequence, native no-replace rename, secure cleanup,
and ``ExportBundle``.

This module contains documentation only: it does not re-export, alias, or
lazy-load any type. Public types are defined directly by
:mod:`specstyle.exporting.manifest` and :mod:`specstyle.exporting.bundle`.
"""
