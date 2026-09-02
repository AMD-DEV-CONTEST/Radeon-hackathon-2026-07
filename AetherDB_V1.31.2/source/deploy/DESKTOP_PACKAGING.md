# AetherDB Native Desktop Packaging

## Supported graphical package contracts

| Host used for build | Tauri bundles |
|---|---|
| Windows | NSIS |
| macOS | `.app`, DMG |
| Linux | DEB, AppImage |

Each package is host-native. A Windows build does not prove macOS or Linux
packaging, and sidecars must never be copied between operating systems.

## Build flow

1. Install the target host's Tauri prerequisites, Rust, Node 20.19+ and pnpm 10+.
2. Create the project Python virtual environment and install
   `requirements.txt` plus `requirements-desktop-build.txt`.
3. Set `AETHERDB_BUILD_CACHE_ROOT` to an external build/cache disk when needed.
4. Run `pnpm run tauri:build:host` from `frontend/`.

The build performs:

```text
host Python
-> PyInstaller host-native backend
-> sanitized sidecar stage
-> Vue production build
-> target-host Tauri installer
```

## Runtime contract

- Tauri reserves an available `127.0.0.1` port and creates a random handshake.
- The sidecar receives separate read-only resource and writable app-data roots.
- Each desktop instance owns and terminates only its own sidecar.
- API keys and `config.local.yaml` are generated in the operating system's
  private application-data directory.
- Ollama remains an external optional installation.
- BGE-M3 remains AetherDB-owned; packaged weights are release inputs and never
  Git content.

## Acceptance boundary

Windows NSIS and dynamic sidecar smoke have existing local evidence. macOS and
Linux configs and host paths are covered by static/Rust tests, but native
installer acceptance must be run on those operating systems before release.
