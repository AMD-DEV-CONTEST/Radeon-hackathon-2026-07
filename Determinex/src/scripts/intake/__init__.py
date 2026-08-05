"""scripts/intake/ — arbitrary-repository intake subsystem.

Houses the BuildAdapter protocol and BuildAdapterRegistry. Other intake
modules (workspace loader, test discovery, failure parsing) may move here
in future rungs; ``codebase_explorer.py`` currently still owns those.
"""
