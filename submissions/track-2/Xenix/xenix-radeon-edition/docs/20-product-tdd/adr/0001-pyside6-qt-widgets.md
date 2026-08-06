# ADR 0001: Use PySide6 with Qt Widgets

- Status: accepted
- Date: 2026-03-09

## Context

The native branch needs a Windows desktop UI stack that supports rapid local delivery, packaging with PyInstaller, and explicit code-first UI composition. Issue `#46` also constrains the project to PySide and Qt Widgets.

## Decision

Use PySide6 with Qt Widgets for the native desktop shell. Keep UI authoring code-first in Python.

## Consequences

- `src/xenix/main.py`, `src/xenix/app.py`, and `src/xenix/ui/` remain the main bootstrap surface.
- The team can stay in one Python toolchain for UI, services, packaging, and tests.
- UI code stays explicit and diff-friendly for the early native milestones.
- QML is intentionally excluded unless a future issue shows a clear need and accepts the maintenance cost.
