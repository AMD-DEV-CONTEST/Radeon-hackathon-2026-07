# Packaged Backend Staging

`generated/` is created by `scripts/build_desktop_sidecar.py` on the current
host platform. Its contents are ignored by Git and copied into the Tauri
application resources as `backend/`.

The stage contains the PyInstaller runtime plus read-only application assets.
It must never contain API keys, local configuration, databases, logs, backups,
BGE-M3 model binaries, or Ollama binaries.

The sidecar must be built on its target host. Windows produces an `.exe`;
macOS and Linux produce a host-native executable. Cross-compiling and copying a
sidecar from another operating system is not supported.
